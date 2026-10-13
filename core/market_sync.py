"""应用内后台更新：报价、ETF 名单和增量 K 线。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from core.market_universe import BENCHMARKS, discover_a500, load_universe, save_universe
from gui.widgets.worker import WorkerThread

HK_TIME = timezone(timedelta(hours=8))


def market_open(now):
    minute = now.hour * 60 + now.minute
    return now.weekday() < 5 and (555 <= minute <= 690 or 780 <= minute <= 910)


class MarketSync(QObject):
    universe_changed = Signal(object)
    quotes_updated = Signal(object)
    history_updated = Signal()
    status_changed = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.cache_path = Path(window.db.db_path).parent / "a500_universe.json"
        self.etfs = load_universe(self.cache_path)
        self.quotes = {}
        self.jobs = {}
        self.stopping = False
        self.enabled = bool(window.config.get("market_sync", "enabled", default=True))
        self.quote_timer = QTimer(self)
        self.quote_timer.setInterval(max(3000, int(window.config.get(
            "realtime", "refresh_interval", default=3000))))
        self.quote_timer.timeout.connect(self.refresh_quotes)
        self.history_timer = QTimer(self)
        self.history_timer.setInterval(600000)
        self.history_timer.timeout.connect(self._scheduled_history)
        self.catalog_timer = QTimer(self)
        self.catalog_timer.setInterval(86400000)
        self.catalog_timer.timeout.connect(self.refresh_universe)

    @property
    def codes(self):
        return list(dict.fromkeys([c for c, _ in self.etfs + BENCHMARKS]))

    def start(self):
        if self.enabled:
            self.quote_timer.start()
            self.history_timer.start()
            self.catalog_timer.start()
            self.refresh_quotes(force=True)
            self.refresh_universe()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.window.config.save_local({"market_sync": {"enabled": enabled}})
        if enabled:
            self.start()
        else:
            for timer in (self.quote_timer, self.history_timer, self.catalog_timer):
                timer.stop()
            for worker in self.jobs.values():
                worker.requestInterruption()
            self.status_changed.emit("自动更新已暂停")

    def _job(self, key, function, callback):
        if self.stopping or key in self.jobs:
            return
        worker = WorkerThread(function)
        worker.finished_ok.connect(callback)
        worker.error.connect(lambda message: self.status_changed.emit(f"{key}更新失败：{message}"))
        worker.finished.connect(lambda: self._finished(key))
        self.jobs[key] = worker
        worker.start()

    def _finished(self, key):
        worker = self.jobs.pop(key, None)
        if worker:
            worker.deleteLater()

    def refresh_universe(self):
        def done(items):
            if self.stopping:
                return
            self.etfs = items
            save_universe(self.cache_path, items)
            self.universe_changed.emit(items)
            self.status_changed.emit(f"已同步全市场 A500 名单：{len(items)} 只")
            self.refresh_quotes(force=True)
        self._job("名单", discover_a500, done)
        # 名单任务结束后，无论成功与否都用当前完整缓存采集。
        worker = self.jobs.get("名单")
        if worker:
            worker.finished.connect(self.refresh_history)

    def refresh_quotes(self, force=False):
        if not force and (not self.enabled or not market_open(datetime.now(HK_TIME))):
            return
        codes = self.codes

        def fetch():
            from downloaders.tencent_quote import TencentQuoteClient
            client = TencentQuoteClient(timeout=5)
            try:
                return client.get_quotes(codes)
            finally:
                client.close()

        def done(quotes):
            if self.stopping:
                return
            for quote in quotes.values():
                quote.update(change_val=quote.get("change"),
                             bid_price=quote.get("bid"), ask_price=quote.get("ask"))
            self.quotes.update(quotes)
            self.window.db.save_quotes(list(quotes.values()))
            self.quotes_updated.emit(self.quotes.copy())
            missing = len(codes) - len(quotes)
            self.status_changed.emit(f"行情更新 {datetime.now(HK_TIME):%H:%M:%S} · "
                                     f"{len(quotes)}/{len(codes)} 只" +
                                     (f" · {missing} 只暂无报价" if missing else ""))
        self._job("行情", fetch, done)

    def _scheduled_history(self):
        if self.enabled and market_open(datetime.now(HK_TIME)):
            self.refresh_history()

    def refresh_history(self, force=False):
        if self.stopping or "K线" in self.jobs or (not self.enabled and not force):
            return
        codes = [c for c, _ in BENCHMARKS] + [c for c, _ in self.etfs]
        db_path, config = self.window.db.db_path, self.window.config
        worker = WorkerThread(lambda: None)

        def fetch():
            from storage.database import Database
            from downloaders.akshare_source import AkshareSource
            db = Database(db_path)  # 独立连接，避免与 GUI 共享事务。
            source = AkshareSource(db, config)
            if source._em:
                source._em.timeout = 5
            if source._yahoo:
                source._yahoo.timeout = 5
            saved, failures = 0, []
            try:
                for code in codes:
                    for period, days in [("K_DAY", 3650), ("K_60M", 730)]:
                        if worker.isInterruptionRequested():
                            return saved, failures
                        now = datetime.now(HK_TIME)
                        latest = db.get_latest_time(code, period)
                        # 多取一天覆盖最近未完成的 K 线。
                        start = ((datetime.fromisoformat(str(latest)[:10]) - timedelta(days=1))
                                 if latest else now - timedelta(days=days))
                        try:
                            data = source._fetch(code.split(".")[1], period,
                                                 start.strftime("%Y-%m-%d"),
                                                 now.strftime("%Y-%m-%d"), code_full=code)
                            if data is None or data.empty:
                                failures.append(f"{code} {period}")
                            else:
                                saved += db.save_kline(code, period, data)
                            worker.progress.emit(f"同步 K线：{code} {period}")
                        except Exception:
                            failures.append(f"{code} {period}")
                return saved, failures
            finally:
                for client in (source._em, source._yahoo):
                    if client:
                        client._session.close()
                db.close()

        def done(result):
            if self.stopping:
                return
            saved, failures = result
            self.history_updated.emit()
            self.window.refresh_status()
            self.status_changed.emit(f"K线同步完成：{saved:,} 条 · {len(failures)} 项暂无数据")
            if failures:
                self.window.log("K线暂不可用：" + ", ".join(failures))

        worker._func = fetch
        worker.progress.connect(self.status_changed)
        worker.progress.connect(lambda message: self.history_updated.emit()
                                if not self.stopping else None)
        worker.finished_ok.connect(done)
        worker.error.connect(lambda message: self.status_changed.emit(f"K线同步失败：{message}"))
        worker.finished.connect(lambda: self._finished("K线"))
        self.jobs["K线"] = worker
        worker.start()

    def stop(self):
        self.stopping = True
        for timer in (self.quote_timer, self.history_timer, self.catalog_timer):
            timer.stop()
        for worker in self.jobs.values():
            worker.requestInterruption()

    def is_idle(self):
        return not self.jobs
