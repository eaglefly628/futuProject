"""数据导出面板"""
import os
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QCheckBox, QTextEdit, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt
from gui.panels.base import BasePanel
from gui.theme import COLORS

KTYPE_LIST = ["K_1M", "K_3M", "K_5M", "K_15M", "K_30M", "K_60M", "K_DAY", "K_WEEK", "K_MON"]


class ExportPanel(BasePanel):
    def __init__(self, main_window):
        super().__init__(main_window, "数据导出", "将数据库中的K线数据导出为 Parquet / CSV 文件")
        self._build()

    def _build(self):
        card, layout = self.make_card("导出设置")

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.addWidget(QLabel("股票代码"))
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("如 US.AAPL")
        row1.addWidget(self._code_input)
        row1.addWidget(QLabel("K线类型"))
        self._ktype_combo = QComboBox()
        self._ktype_combo.addItems(KTYPE_LIST)
        self._ktype_combo.setCurrentText("K_DAY")
        row1.addWidget(self._ktype_combo)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        self._parquet_check = QCheckBox("Parquet 格式")
        self._parquet_check.setChecked(True)
        self._csv_check = QCheckBox("CSV 格式")
        self._csv_check.setChecked(True)
        row2.addWidget(self._parquet_check)
        row2.addWidget(self._csv_check)
        row2.addStretch()
        layout.addLayout(row2)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addWidget(self.make_primary_btn("💾 导出", self._on_export))
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self.add_widget(card)

        # ─── 整库备份 / 恢复 ───
        bk_card, bk_layout = self.make_card(
            "整库备份 / 恢复  ·  用于跨设备搬运（Parquet 压缩，体积约为 .db 的 1/6）")

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(QLabel("备份目录"))
        self._backup_input = QLineEdit()
        default_dir = os.path.join(
            os.path.dirname(self._main.config.get("storage", "sqlite_path")), "backup")
        self._backup_input.setText(default_dir)
        path_row.addWidget(self._backup_input, 1)
        browse = self.make_primary_btn("浏览...", self._on_browse_backup)
        browse.setObjectName("")
        path_row.addWidget(browse)
        bk_layout.addLayout(path_row)

        opt_row = QHBoxLayout()
        opt_row.setContentsMargins(0, 0, 0, 0)
        self._zip_check = QCheckBox("备份后打包成 zip")
        opt_row.addWidget(self._zip_check)
        opt_row.addStretch()
        bk_layout.addLayout(opt_row)

        bk_btn_row = QHBoxLayout()
        bk_btn_row.setContentsMargins(0, 0, 0, 0)
        bk_btn_row.addWidget(self.make_primary_btn("📦 备份全部数据", self._on_backup))
        bk_btn_row.addWidget(self.make_primary_btn("📥 从备份恢复", self._on_restore))
        bk_btn_row.addWidget(self.make_primary_btn("🔍 查看备份内容", self._on_inspect))
        bk_btn_row.addStretch()
        bk_layout.addLayout(bk_btn_row)

        tip = QLabel(
            "备份产物是纯文本友好的 Parquet 文件，体积小，可以直接提交到 git；"
            "数据库 .db 本身已被 .gitignore 排除。恢复采用按时间键去重合并，重复导入不会产生重复数据。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:12px;")
        bk_layout.addWidget(tip)

        self.add_widget(bk_card)

        log_card, log_layout = self.make_card("运行结果")
        self._log = QTextEdit()
        self._log.setMinimumHeight(120)
        self._log.setObjectName("logPanel")
        self._log.setReadOnly(True)
        log_layout.addWidget(self._log)
        self.add_widget(log_card)
        self._content_layout.setStretchFactor(log_card, 1)

    # ═══════════════════════════════════════
    #  备份 / 恢复
    # ═══════════════════════════════════════
    def _on_browse_backup(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择备份目录", self._backup_input.text() or os.getcwd())
        if d:
            self._backup_input.setText(d)

    def _log_line(self, msg: str, color: str = None):
        self._log.append(
            f'<span style="color:{color}">{msg}</span>' if color else msg)

    def _on_backup(self):
        out_dir = self._backup_input.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "提示", "请指定备份目录")
            return

        from storage.backup import export_backup, make_archive
        from gui.widgets.worker import WorkerThread

        self._log_line(f"开始备份到 {out_dir} ...", COLORS["accent"])
        want_zip = self._zip_check.isChecked()

        worker = WorkerThread(lambda: None)

        def do_backup():
            r = export_backup(self._main.db, out_dir,
                              progress=lambda m: worker.progress.emit(m))
            if want_zip:
                worker.progress.emit("正在打包 zip ...")
                r["archive"] = make_archive(out_dir)
            return r

        worker._func = do_backup
        self._worker = worker
        worker.progress.connect(lambda m: self._log_line(m))
        worker.finished_ok.connect(self._on_backup_done)
        worker.error.connect(
            lambda e: self._log_line(f"❌ 备份失败: {e}", COLORS["red"]))
        worker.start()

    def _on_backup_done(self, r: dict):
        self._log_line(
            f"✅ 备份完成: {r['files']} 个文件 · {r['rows']:,} 条 · {r['size_mb']} MB",
            COLORS["green"])
        self._log_line(f"   位置: {r['path']}", COLORS["text_secondary"])
        if r.get("archive"):
            self._log_line(f"   压缩包: {r['archive']}", COLORS["text_secondary"])
        self._main.log(f"数据备份完成: {r['rows']:,} 条")

    def _on_inspect(self):
        d = self._backup_input.text().strip()
        try:
            from storage.backup import inspect_backup
            mf = inspect_backup(d)
        except Exception as e:
            self._log_line(f"❌ {e}", COLORS["red"])
            return

        self._log_line(
            f"备份清单  创建于 {mf.get('created_at')}  ·  "
            f"{mf.get('total_files')} 个文件 · {mf.get('total_rows', 0):,} 条",
            COLORS["accent"])
        for e in mf.get("entries", [])[:40]:
            self._log_line(
                f"   {e['code']:14s} {e['ktype']:7s} {e['rows']:>8,} 条   "
                f"{e['start'][:16]} ~ {e['end'][:16]}",
                COLORS["text_secondary"])
        if len(mf.get("entries", [])) > 40:
            self._log_line(f"   ... 其余 {len(mf['entries'])-40} 项省略",
                           COLORS["text_muted"])

    def _on_restore(self):
        d = self._backup_input.text().strip()
        if not d or not os.path.isdir(d):
            QMessageBox.warning(self, "提示", f"备份目录不存在:\n{d}")
            return

        if QMessageBox.question(
                self, "确认恢复",
                f"将从下列目录导入数据到当前数据库：\n{d}\n\n"
                f"已存在的相同K线会被覆盖为备份中的版本，其余数据保留。\n继续？"
        ) != QMessageBox.Yes:
            return

        from storage.backup import import_backup
        from gui.widgets.worker import WorkerThread

        self._log_line(f"开始从 {d} 恢复 ...", COLORS["accent"])

        worker = WorkerThread(lambda: None)
        worker._func = lambda: import_backup(
            self._main.db, d, progress=lambda m: worker.progress.emit(m))
        self._worker = worker
        worker.progress.connect(lambda m: self._log_line(m))
        worker.finished_ok.connect(self._on_restore_done)
        worker.error.connect(
            lambda e: self._log_line(f"❌ 恢复失败: {e}", COLORS["red"]))
        worker.start()

    def _on_restore_done(self, r: dict):
        self._log_line(
            f"✅ 恢复完成: {r['rows']:,} 条 · 共 {r['entries']} 项 · 失败 {r['failed']}",
            COLORS["green"])
        self._main.log(f"数据恢复完成: {r['rows']:,} 条")
        self._main.refresh_status()

    def _on_export(self):
        code = self._code_input.text().strip()
        ktype = self._ktype_combo.currentText()
        if not code:
            QMessageBox.warning(self, "提示", "请输入股票代码")
            return
        if not self._parquet_check.isChecked() and not self._csv_check.isChecked():
            QMessageBox.warning(self, "提示", "请选择至少一种导出格式")
            return

        results = []
        if self._parquet_check.isChecked():
            pdir = self._main.config.get("storage", "parquet_dir")
            path = self._main.db.export_to_parquet(code, ktype, pdir)
            if path:
                results.append(f"Parquet: {path}")

        if self._csv_check.isChecked():
            cdir = self._main.config.get("storage", "csv_dir")
            path = self._main.db.export_to_csv(code, ktype, cdir)
            if path:
                results.append(f"CSV: {path}")

        if results:
            for r in results:
                self._log.append(f'<span style="color:{COLORS["green"]}">✅ {r}</span>')
            self._main.log(f"导出完成: {code} {ktype}")
        else:
            self._log.append(f'<span style="color:{COLORS["yellow"]}">⚠️ 无数据可导出: {code} {ktype}</span>')
