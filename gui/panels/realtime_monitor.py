"""实时行情监控面板"""
from datetime import datetime
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QDoubleSpinBox, QMessageBox, QSplitter,
    QFrame, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer
from gui.panels.base import BasePanel
from gui.theme import COLORS
from loguru import logger


class RealtimeMonitorPanel(BasePanel):
    """实时行情监控"""

    # 行情表列定义
    QUOTE_COLUMNS = [
        "代码", "名称", "最新价", "涨跌%", "涨跌额",
        "成交量", "成交额", "振幅%", "最高", "最低",
        "量比", "换手率%", "市盈率",
    ]

    def __init__(self, main_window):
        super().__init__(main_window, "实时行情", "实时监控股票行情数据和价格预警")
        self._quote_subscriber = None
        self._watched_codes = []  # 当前监控的股票代码列表
        self._timer = None
        self._build()

    def _build(self):
        """构建界面"""
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; height: 6px; }")

        # ─── 上部: 行情监控区 ───
        quote_card, quote_layout = self.make_card("行情监控")

        # 工具栏: 添加股票代码
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addWidget(QLabel("股票代码"))
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("如 HK.00700, US.AAPL")
        self._code_input.setMinimumWidth(200)
        self._code_input.returnPressed.connect(self._on_add_stock)
        toolbar.addWidget(self._code_input)

        self._add_btn = self.make_primary_btn("添加", self._on_add_stock)
        toolbar.addWidget(self._add_btn)

        self._import_btn = self.make_primary_btn("从监控列表导入", self._on_import_watchlist)
        toolbar.addWidget(self._import_btn)

        self._remove_btn = self.make_danger_btn("移除", self._on_remove_stock)
        toolbar.addWidget(self._remove_btn)

        toolbar.addStretch()

        # 刷新状态标签
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        toolbar.addWidget(self._status_label)

        quote_layout.addLayout(toolbar)

        # 行情表格
        self._quote_table = QTableWidget()
        self._quote_table.setMinimumHeight(200)
        self._quote_table.setAlternatingRowColors(True)
        self._quote_table.setColumnCount(len(self.QUOTE_COLUMNS))
        self._quote_table.setHorizontalHeaderLabels(self.QUOTE_COLUMNS)
        self._quote_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._quote_table.verticalHeader().setVisible(False)
        self._quote_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._quote_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._quote_table.setSelectionMode(QAbstractItemView.SingleSelection)
        quote_layout.addWidget(self._quote_table)
        splitter.addWidget(quote_card)

        # ─── 下部: 价格预警区 ───
        alert_card, alert_layout = self.make_card("价格预警")

        # 预警设置行
        alert_toolbar = QHBoxLayout()
        alert_toolbar.setContentsMargins(0, 0, 0, 0)
        alert_toolbar.addWidget(QLabel("股票代码"))
        self._alert_code_input = QLineEdit()
        self._alert_code_input.setPlaceholderText("如 HK.00700")
        self._alert_code_input.setMinimumWidth(140)
        alert_toolbar.addWidget(self._alert_code_input)

        alert_toolbar.addWidget(QLabel("条件"))
        self._alert_condition = QComboBox()
        self._alert_condition.addItems(["高于", "低于"])
        self._alert_condition.setMinimumWidth(80)
        alert_toolbar.addWidget(self._alert_condition)

        alert_toolbar.addWidget(QLabel("目标价"))
        self._alert_price_input = QDoubleSpinBox()
        self._alert_price_input.setRange(0.001, 999999.99)
        self._alert_price_input.setDecimals(3)
        self._alert_price_input.setValue(100.0)
        self._alert_price_input.setMinimumWidth(120)
        alert_toolbar.addWidget(self._alert_price_input)

        self._alert_add_btn = self.make_primary_btn("添加预警", self._on_add_alert)
        alert_toolbar.addWidget(self._alert_add_btn)

        self._alert_del_btn = self.make_danger_btn("删除预警", self._on_delete_alert)
        alert_toolbar.addWidget(self._alert_del_btn)

        alert_toolbar.addStretch()
        alert_layout.addLayout(alert_toolbar)

        # 预警表格
        self._alert_table = QTableWidget()
        self._alert_table.setMinimumHeight(200)
        self._alert_table.setAlternatingRowColors(True)
        self._alert_table.setColumnCount(6)
        self._alert_table.setHorizontalHeaderLabels(["ID", "代码", "名称", "条件", "目标价", "状态"])
        self._alert_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._alert_table.verticalHeader().setVisible(False)
        self._alert_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._alert_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._alert_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._alert_table.setMaximumHeight(200)
        alert_layout.addWidget(self._alert_table)
        splitter.addWidget(alert_card)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.add_widget(splitter)

        # ─── 定时刷新 ───
        interval = 3000
        try:
            interval = self._main.config.get("realtime", "refresh_interval") or 3000
        except Exception:
            pass
        self._timer = QTimer(self)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self._on_refresh_tick)

    # ═══════ 事件处理 ═══════

    def on_show(self):
        """面板显示时加载预警列表"""
        self._load_alerts()

    def _on_add_stock(self):
        """添加股票到监控列表"""
        text = self._code_input.text().strip()
        if not text:
            return
        # 支持逗号或空格分隔的多个代码
        codes = [c.strip() for c in text.replace(",", " ").replace("，", " ").split() if c.strip()]
        added = []
        for code in codes:
            code_upper = code.upper()
            if code_upper not in self._watched_codes:
                self._watched_codes.append(code_upper)
                added.append(code_upper)
        if added:
            logger.info(f"添加监控股票: {added}")
            self._code_input.clear()
            self._start_refresh()
            self._do_refresh()

    def _on_remove_stock(self):
        """移除选中的股票"""
        row = self._quote_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在行情表中选中要移除的股票")
            return
        code_item = self._quote_table.item(row, 0)
        if code_item:
            code = code_item.text()
            if code in self._watched_codes:
                self._watched_codes.remove(code)
                logger.info(f"移除监控股票: {code}")
                self._do_refresh()
        if not self._watched_codes:
            self._stop_refresh()
            self._quote_table.setRowCount(0)

    def _on_import_watchlist(self):
        """从配置的监控列表导入股票"""
        try:
            watchlist = self._main.config.get("watchlist") or {}
        except Exception:
            watchlist = {}
        added = []
        for market, codes in watchlist.items():
            if isinstance(codes, list):
                for code in codes:
                    code = str(code).strip()
                    if code and code not in self._watched_codes:
                        self._watched_codes.append(code)
                        added.append(code)
        if added:
            logger.info(f"从监控列表导入: {added}")
            self._start_refresh()
            self._do_refresh()
        else:
            QMessageBox.information(self, "提示", "监控列表为空或所有股票已添加")

    def _start_refresh(self):
        """启动定时刷新"""
        if not self._timer.isActive() and self._watched_codes:
            self._timer.start()
            logger.info("实时行情刷新已启动")

    def _stop_refresh(self):
        """停止定时刷新"""
        if self._timer.isActive():
            self._timer.stop()
            logger.info("实时行情刷新已停止")

    def _on_refresh_tick(self):
        """定时刷新回调"""
        self._do_refresh()

    def _do_refresh(self):
        """执行一次行情刷新"""
        if not self._watched_codes:
            return

        # 获取行情数据
        quotes = {}
        if self._main.is_connected and self._main.client:
            try:
                # 使用 QuoteSubscriber 或直接通过 client 获取快照
                if self._quote_subscriber is None:
                    from core.quote_subscriber import QuoteSubscriber
                    self._quote_subscriber = QuoteSubscriber(self._main.client)
                quotes = self._quote_subscriber.get_snapshot(self._watched_codes)
            except Exception as e:
                logger.warning(f"获取实时行情失败: {e}")

        # 更新行情表格
        self._update_quote_table(quotes)

        # 保存到数据库
        if quotes:
            try:
                self._main.db.save_quotes(list(quotes.values()))
            except Exception as e:
                logger.warning(f"保存行情缓存失败: {e}")

        # 检查价格预警
        if quotes:
            self._check_alerts(quotes)

        # 更新状态
        now = datetime.now().strftime("%H:%M:%S")
        self._status_label.setText(f"最后刷新: {now}  |  监控: {len(self._watched_codes)} 只")

    def _update_quote_table(self, quotes: dict):
        """更新行情表格数据"""
        self._quote_table.setRowCount(len(self._watched_codes))
        for i, code in enumerate(self._watched_codes):
            q = quotes.get(code, {})

            # 代码
            self._set_table_item(self._quote_table, i, 0, code)
            # 名称
            self._set_table_item(self._quote_table, i, 1, str(q.get("name", "")))

            # 最新价
            price = q.get("price")
            price_text = f"{price:.3f}" if price is not None else "--"
            self._set_table_item(self._quote_table, i, 2, price_text, align_right=True)

            # 涨跌% - 通过当前价和前收盘价计算
            prev_close = q.get("prev_close")
            change_rate = None
            change_val = None
            if price is not None and prev_close and prev_close > 0:
                change_val = price - prev_close
                change_rate = (change_val / prev_close) * 100

            # 涨跌%
            if change_rate is not None:
                rate_text = f"{change_rate:+.2f}%"
                color = COLORS["green"] if change_rate >= 0 else COLORS["red"]
            else:
                rate_text = "--"
                color = None
            self._set_table_item(self._quote_table, i, 3, rate_text, color=color, align_right=True)

            # 涨跌额
            if change_val is not None:
                val_text = f"{change_val:+.3f}"
                color = COLORS["green"] if change_val >= 0 else COLORS["red"]
            else:
                val_text = "--"
                color = None
            self._set_table_item(self._quote_table, i, 4, val_text, color=color, align_right=True)

            # 成交量
            volume = q.get("volume")
            vol_text = self._format_volume(volume) if volume is not None else "--"
            self._set_table_item(self._quote_table, i, 5, vol_text, align_right=True)

            # 成交额
            turnover = q.get("turnover")
            to_text = self._format_turnover(turnover) if turnover is not None else "--"
            self._set_table_item(self._quote_table, i, 6, to_text, align_right=True)

            # 振幅%
            amplitude = q.get("amplitude")
            amp_text = f"{amplitude:.2f}%" if amplitude is not None else "--"
            self._set_table_item(self._quote_table, i, 7, amp_text, align_right=True)

            # 最高
            high = q.get("high")
            high_text = f"{high:.3f}" if high is not None else "--"
            self._set_table_item(self._quote_table, i, 8, high_text, align_right=True)

            # 最低
            low = q.get("low")
            low_text = f"{low:.3f}" if low is not None else "--"
            self._set_table_item(self._quote_table, i, 9, low_text, align_right=True)

            # 量比
            volume_ratio = q.get("volume_ratio")
            vr_text = f"{volume_ratio:.2f}" if volume_ratio is not None else "--"
            self._set_table_item(self._quote_table, i, 10, vr_text, align_right=True)

            # 换手率%
            turnover_rate = q.get("turnover_rate")
            tr_text = f"{turnover_rate:.2f}%" if turnover_rate is not None else "--"
            self._set_table_item(self._quote_table, i, 11, tr_text, align_right=True)

            # 市盈率
            pe = q.get("pe_ratio")
            pe_text = f"{pe:.2f}" if pe is not None else "--"
            self._set_table_item(self._quote_table, i, 12, pe_text, align_right=True)

    def _set_table_item(self, table, row, col, text, color=None, align_right=False):
        """设置表格单元格"""
        item = QTableWidgetItem(str(text))
        if align_right:
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if color:
            item.setForeground(Qt.GlobalColor.white)
            from PySide6.QtGui import QColor
            item.setForeground(QColor(color))
        table.setItem(row, col, item)

    @staticmethod
    def _format_volume(vol):
        """格式化成交量"""
        if vol is None:
            return "--"
        if vol >= 1e8:
            return f"{vol / 1e8:.2f}亿"
        elif vol >= 1e4:
            return f"{vol / 1e4:.2f}万"
        return f"{vol:.0f}"

    @staticmethod
    def _format_turnover(val):
        """格式化成交额"""
        if val is None:
            return "--"
        if val >= 1e8:
            return f"{val / 1e8:.2f}亿"
        elif val >= 1e4:
            return f"{val / 1e4:.2f}万"
        return f"{val:.0f}"

    # ═══════ 价格预警 ═══════

    def _on_add_alert(self):
        """添加价格预警"""
        code = self._alert_code_input.text().strip().upper()
        if not code:
            QMessageBox.warning(self, "提示", "请输入股票代码")
            return
        condition = self._alert_condition.currentText()
        target_price = self._alert_price_input.value()

        # 尝试获取股票名称
        name = ""
        if self._quote_subscriber and code in self._quote_subscriber.quotes:
            name = self._quote_subscriber.quotes[code].get("name", "")

        try:
            self._main.db.save_alert(code, name, condition, target_price)
            logger.info(f"添加预警: {code} {condition} {target_price}")
            self._alert_code_input.clear()
            self._load_alerts()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"添加预警失败: {e}")

    def _on_delete_alert(self):
        """删除选中的预警"""
        row = self._alert_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中要删除的预警")
            return
        id_item = self._alert_table.item(row, 0)
        if id_item:
            alert_id = int(id_item.text())
            try:
                self._main.db.delete_alert(alert_id)
                self._load_alerts()
            except Exception as e:
                QMessageBox.warning(self, "错误", f"删除预警失败: {e}")

    def _load_alerts(self):
        """加载预警列表到表格"""
        try:
            alerts = self._main.db.get_alerts()
        except Exception:
            alerts = []

        self._alert_table.setRowCount(len(alerts))
        for i, alert in enumerate(alerts):
            self._alert_table.setItem(i, 0, QTableWidgetItem(str(alert.get("id", ""))))
            self._alert_table.setItem(i, 1, QTableWidgetItem(str(alert.get("code", ""))))
            self._alert_table.setItem(i, 2, QTableWidgetItem(str(alert.get("name", ""))))
            self._alert_table.setItem(i, 3, QTableWidgetItem(str(alert.get("condition", ""))))

            price_item = QTableWidgetItem(f"{alert.get('target_price', 0):.3f}")
            price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._alert_table.setItem(i, 4, price_item)

            triggered = alert.get("triggered", 0)
            if triggered:
                status_text = f"已触发 {alert.get('triggered_at', '')}"
                status_item = QTableWidgetItem(status_text)
                from PySide6.QtGui import QColor
                status_item.setForeground(QColor(COLORS["yellow"]))
            else:
                status_item = QTableWidgetItem("监控中")
                from PySide6.QtGui import QColor
                status_item.setForeground(QColor(COLORS["green"]))
            self._alert_table.setItem(i, 5, status_item)

    def _check_alerts(self, quotes: dict):
        """检查价格预警是否触发"""
        try:
            alerts = self._main.db.get_alerts(triggered=False)
        except Exception:
            return

        for alert in alerts:
            code = alert.get("code", "")
            if code not in quotes:
                continue
            current_price = quotes[code].get("price")
            if current_price is None:
                continue

            target_price = alert.get("target_price", 0)
            condition = alert.get("condition", "")
            triggered = False

            if condition == "高于" and current_price >= target_price:
                triggered = True
            elif condition == "低于" and current_price <= target_price:
                triggered = True

            if triggered:
                alert_id = alert.get("id")
                name = alert.get("name", code)
                try:
                    self._main.db.trigger_alert(alert_id)
                except Exception as e:
                    logger.warning(f"触发预警更新失败: {e}")

                # 弹出通知
                msg = (f"价格预警触发!\n\n"
                       f"股票: {code} {name}\n"
                       f"条件: {condition} {target_price:.3f}\n"
                       f"当前价: {current_price:.3f}")
                logger.info(f"预警触发: {code} {condition} {target_price} 当前价={current_price}")
                self._main.log(f"价格预警: {code} {condition} {target_price}")

                QMessageBox.information(self, "价格预警", msg)
                self._load_alerts()
