"""模拟交易面板 - 下单、委托、统计"""
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
    QFrame, QMessageBox
)
from PySide6.QtCore import Qt, QTimer
from gui.panels.base import BasePanel
from gui.theme import COLORS
from loguru import logger


class PaperTradingPanel(BasePanel):
    """模拟交易面板"""

    def __init__(self, main_window):
        super().__init__(main_window, "模拟交易", "纸盘交易 - 零风险验证策略")
        self._paper_engine = None
        self._account_id = 1
        self._build()
        self._setup_timer()

    def _get_engine(self):
        """延迟获取 paper engine"""
        if self._paper_engine is None:
            engine = getattr(self._main, "paper_engine", None)
            if engine:
                self._paper_engine = engine
                self._account_id = engine.get_default_account_id()
        return self._paper_engine

    def _build(self):
        """构建界面"""
        tabs = QTabWidget()

        # Tab 1: 交易下单
        tab_order = QWidget()
        tab_order_layout = QVBoxLayout(tab_order)
        tab_order_layout.setContentsMargins(16, 16, 16, 16)
        tab_order_layout.setSpacing(12)
        self._build_order_tab(tab_order_layout)
        tabs.addTab(tab_order, "交易下单")

        # Tab 2: 委托记录
        tab_orders = QWidget()
        tab_orders_layout = QVBoxLayout(tab_orders)
        tab_orders_layout.setContentsMargins(16, 16, 16, 16)
        tab_orders_layout.setSpacing(12)
        self._build_orders_tab(tab_orders_layout)
        tabs.addTab(tab_orders, "委托记录")

        # Tab 3: 交易统计
        tab_stats = QWidget()
        tab_stats_layout = QVBoxLayout(tab_stats)
        tab_stats_layout.setContentsMargins(16, 16, 16, 16)
        tab_stats_layout.setSpacing(12)
        self._build_stats_tab(tab_stats_layout)
        tabs.addTab(tab_stats, "交易统计")

        self.add_widget(tabs)

    # ═══════════════════════════════════════════
    # Tab 1: 交易下单
    # ═══════════════════════════════════════════

    def _build_order_tab(self, layout):
        """构建交易下单标签页"""
        # ─── 账户摘要卡片行 ───
        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(12)
        self._card_total_asset = self.make_stat_card("总资产", "0.00", COLORS["accent"])
        self._card_cash = self.make_stat_card("可用资金", "0.00", COLORS["blue"])
        self._card_pos_value = self.make_stat_card("持仓市值", "0.00", COLORS["purple"])
        self._card_total_pnl = self.make_stat_card("总盈亏", "0.00", COLORS["green"])
        summary_row.addWidget(self._card_total_asset)
        summary_row.addWidget(self._card_cash)
        summary_row.addWidget(self._card_pos_value)
        summary_row.addWidget(self._card_total_pnl)
        layout.addLayout(summary_row)

        # ─── 下单表单 ───
        form_card, form_layout = self.make_card("快速下单")
        form_grid = QGridLayout()
        form_grid.setContentsMargins(0, 0, 0, 0)
        form_grid.setSpacing(8)

        # 第一行：代码 + 方向 + 类型
        form_grid.addWidget(QLabel("股票代码"), 0, 0)
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("如 US.AAPL, HK.00700, SH.600519")
        self._code_input.setMinimumWidth(200)
        form_grid.addWidget(self._code_input, 0, 1)

        form_grid.addWidget(QLabel("方向"), 0, 2)
        self._direction_combo = QComboBox()
        self._direction_combo.addItems(["买入", "卖出"])
        self._direction_combo.setFixedWidth(100)
        form_grid.addWidget(self._direction_combo, 0, 3)

        form_grid.addWidget(QLabel("类型"), 0, 4)
        self._order_type_combo = QComboBox()
        self._order_type_combo.addItems(["市价", "限价", "止损"])
        self._order_type_combo.setFixedWidth(100)
        self._order_type_combo.currentIndexChanged.connect(self._on_order_type_changed)
        form_grid.addWidget(self._order_type_combo, 0, 5)

        # 第二行：数量 + 价格 + 预估费用 + 下单按钮
        form_grid.addWidget(QLabel("数量"), 1, 0)
        self._quantity_spin = QSpinBox()
        self._quantity_spin.setRange(1, 9999999)
        self._quantity_spin.setValue(100)
        self._quantity_spin.setSingleStep(100)
        self._quantity_spin.valueChanged.connect(self._update_fee_estimate)
        form_grid.addWidget(self._quantity_spin, 1, 1)

        form_grid.addWidget(QLabel("价格"), 1, 2)
        self._price_input = QDoubleSpinBox()
        self._price_input.setRange(0, 9999999)
        self._price_input.setDecimals(2)
        self._price_input.setValue(0)
        self._price_input.setEnabled(False)  # 默认市价单
        self._price_input.valueChanged.connect(self._update_fee_estimate)
        form_grid.addWidget(self._price_input, 1, 3)

        form_grid.addWidget(QLabel("预估费用"), 1, 4)
        self._fee_label = QLabel("--")
        self._fee_label.setStyleSheet(f"color: {COLORS['yellow']}; font-weight: bold;")
        form_grid.addWidget(self._fee_label, 1, 5)

        place_btn = self.make_primary_btn("下单", self._on_place_order)
        place_btn.setFixedHeight(36)
        form_grid.addWidget(place_btn, 1, 6)

        form_layout.addLayout(form_grid)
        layout.addWidget(form_card)

        # ─── 持仓表格 ───
        pos_card, pos_layout = self.make_card("当前持仓")
        self._pos_table = QTableWidget()
        self._pos_table.setMinimumHeight(200)
        self._pos_table.setColumnCount(8)
        self._pos_table.setHorizontalHeaderLabels([
            "代码", "名称", "数量", "成本价", "现价", "盈亏", "盈亏%", "操作"
        ])
        self._pos_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._pos_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self._pos_table.setColumnWidth(0, 120)
        self._pos_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Fixed)
        self._pos_table.setColumnWidth(7, 80)
        self._pos_table.verticalHeader().setVisible(False)
        self._pos_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._pos_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._pos_table.setAlternatingRowColors(True)
        pos_layout.addWidget(self._pos_table)
        layout.addWidget(pos_card)

        layout.addStretch()

    # ═══════════════════════════════════════════
    # Tab 2: 委托记录
    # ═══════════════════════════════════════════

    def _build_orders_tab(self, layout):
        """构建委托记录标签页"""
        # 过滤器
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(QLabel("状态过滤:"))
        self._order_filter_combo = QComboBox()
        self._order_filter_combo.addItems(["全部", "待成交", "已成交", "已撤销"])
        self._order_filter_combo.setFixedWidth(120)
        self._order_filter_combo.currentIndexChanged.connect(self._refresh_orders_table)
        filter_row.addWidget(self._order_filter_combo)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # 订单表格
        self._orders_table = QTableWidget()
        self._orders_table.setMinimumHeight(200)
        self._orders_table.setColumnCount(11)
        self._orders_table.setHorizontalHeaderLabels([
            "时间", "代码", "方向", "类型", "数量", "价格", "成交价",
            "佣金", "税费", "状态", "操作"
        ])
        self._orders_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._orders_table.horizontalHeader().setSectionResizeMode(10, QHeaderView.Fixed)
        self._orders_table.setColumnWidth(10, 80)
        self._orders_table.verticalHeader().setVisible(False)
        self._orders_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._orders_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._orders_table.setAlternatingRowColors(True)
        layout.addWidget(self._orders_table)

    # ═══════════════════════════════════════════
    # Tab 3: 交易统计
    # ═══════════════════════════════════════════

    def _build_stats_tab(self, layout):
        """构建交易统计标签页"""
        # 统计卡片
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(12)
        self._card_trade_count = self.make_stat_card("总交易次数", "0", COLORS["accent"])
        self._card_filled_count = self.make_stat_card("已成交", "0", COLORS["blue"])
        self._card_win_rate = self.make_stat_card("胜率", "0%", COLORS["green"])
        self._card_realized_pnl = self.make_stat_card("总盈亏", "0.00", COLORS["purple"])
        stats_row.addWidget(self._card_trade_count)
        stats_row.addWidget(self._card_filled_count)
        stats_row.addWidget(self._card_win_rate)
        stats_row.addWidget(self._card_realized_pnl)
        layout.addLayout(stats_row)

        # 交易历史表格
        history_card, history_layout = self.make_card("交易历史")
        self._history_table = QTableWidget()
        self._history_table.setMinimumHeight(200)
        self._history_table.setColumnCount(10)
        self._history_table.setHorizontalHeaderLabels([
            "时间", "订单号", "代码", "方向", "数量", "成交价",
            "金额", "佣金", "税费", "实现盈亏"
        ])
        self._history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._history_table.setAlternatingRowColors(True)
        history_layout.addWidget(self._history_table)
        layout.addWidget(history_card)

        layout.addStretch()

    # ═══════════════════════════════════════════
    # 定时器
    # ═══════════════════════════════════════════

    def _setup_timer(self):
        """设置定时刷新"""
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._on_timer_tick)

    def on_show(self):
        """面板显示时刷新并启动定时器"""
        self._get_engine()
        self._refresh_all()
        self._timer.start()

    def _on_timer_tick(self):
        """定时任务: 尝试成交挂单 + 刷新数据"""
        engine = self._get_engine()
        if not engine:
            return
        # 尝试用缓存行情成交挂单
        if engine._quotes_cache:
            engine.try_fill_orders(engine._quotes_cache)
            engine.update_positions_price(engine._quotes_cache)
        self._refresh_all()

    # ═══════════════════════════════════════════
    # 刷新
    # ═══════════════════════════════════════════

    def _refresh_all(self):
        """刷新所有数据"""
        self._refresh_summary()
        self._refresh_positions()
        self._refresh_orders_table()
        self._refresh_stats()

    def _refresh_summary(self):
        """刷新账户摘要"""
        engine = self._get_engine()
        if not engine:
            return
        summary = engine.get_account_summary(self._account_id)
        self._update_stat(self._card_total_asset, f"{summary['total_asset']:,.2f}")
        self._update_stat(self._card_cash, f"{summary['cash']:,.2f}")
        self._update_stat(self._card_pos_value, f"{summary['positions_value']:,.2f}")

        pnl = summary["total_pnl"]
        pnl_text = f"{pnl:+,.2f} ({summary['pnl_rate']:+.2f}%)"
        color = COLORS["green"] if pnl >= 0 else COLORS["red"]
        self._update_stat(self._card_total_pnl, pnl_text, color)

    def _refresh_positions(self):
        """刷新持仓表格"""
        engine = self._get_engine()
        if not engine:
            return
        positions = engine.get_positions(self._account_id)
        self._pos_table.setRowCount(len(positions))

        for i, pos in enumerate(positions):
            code = pos.get("code", "")
            name = pos.get("name", "")
            qty = pos.get("quantity", 0)
            avg_cost = pos.get("avg_cost", 0)
            current = pos.get("current_price", 0)
            pnl = pos.get("unrealized_pnl", 0)
            pnl_pct = ((current - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

            self._pos_table.setItem(i, 0, QTableWidgetItem(code))
            self._pos_table.setItem(i, 1, QTableWidgetItem(name))

            qty_item = QTableWidgetItem(str(qty))
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._pos_table.setItem(i, 2, qty_item)

            cost_item = QTableWidgetItem(f"{avg_cost:.2f}")
            cost_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._pos_table.setItem(i, 3, cost_item)

            price_item = QTableWidgetItem(f"{current:.2f}")
            price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._pos_table.setItem(i, 4, price_item)

            pnl_color = COLORS["green"] if pnl >= 0 else COLORS["red"]
            pnl_item = QTableWidgetItem(f"{pnl:+.2f}")
            pnl_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            pnl_item.setForeground(self._make_color(pnl_color))
            self._pos_table.setItem(i, 5, pnl_item)

            pct_item = QTableWidgetItem(f"{pnl_pct:+.2f}%")
            pct_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            pct_item.setForeground(self._make_color(pnl_color))
            self._pos_table.setItem(i, 6, pct_item)

            # 卖出按钮
            sell_btn = self.make_danger_btn("卖出")
            sell_btn.setFixedHeight(28)
            sell_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
            sell_btn.clicked.connect(
                lambda checked, c=code, q=qty: self._on_quick_sell(c, q)
            )
            self._pos_table.setCellWidget(i, 7, sell_btn)

    def _refresh_orders_table(self):
        """刷新委托记录表格"""
        engine = self._get_engine()
        if not engine:
            return

        filter_map = {
            "全部": None,
            "待成交": "PENDING",
            "已成交": "FILLED",
            "已撤销": "CANCELLED",
        }
        filter_text = self._order_filter_combo.currentText()
        status_filter = filter_map.get(filter_text)

        orders = engine.get_orders(self._account_id, status=status_filter)
        self._orders_table.setRowCount(len(orders))

        status_labels = {
            "PENDING": "待成交",
            "FILLED": "已成交",
            "CANCELLED": "已撤销",
            "REJECTED": "已拒绝",
        }
        direction_labels = {"BUY": "买入", "SELL": "卖出"}
        type_labels = {"MARKET": "市价", "LIMIT": "限价", "STOP": "止损"}

        for i, order in enumerate(orders):
            self._orders_table.setItem(i, 0, QTableWidgetItem(
                str(order.get("created_at", ""))
            ))
            self._orders_table.setItem(i, 1, QTableWidgetItem(order.get("code", "")))

            direction = order.get("direction", "")
            dir_item = QTableWidgetItem(direction_labels.get(direction, direction))
            dir_color = COLORS["red"] if direction == "BUY" else COLORS["green"]
            dir_item.setForeground(self._make_color(dir_color))
            self._orders_table.setItem(i, 2, dir_item)

            self._orders_table.setItem(i, 3, QTableWidgetItem(
                type_labels.get(order.get("order_type", ""), order.get("order_type", ""))
            ))

            qty_item = QTableWidgetItem(str(order.get("quantity", 0)))
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._orders_table.setItem(i, 4, qty_item)

            price_val = order.get("price") or 0
            price_item = QTableWidgetItem(f"{price_val:.2f}" if price_val else "--")
            price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._orders_table.setItem(i, 5, price_item)

            filled_price = order.get("filled_price") or 0
            fp_item = QTableWidgetItem(f"{filled_price:.2f}" if filled_price else "--")
            fp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._orders_table.setItem(i, 6, fp_item)

            comm_item = QTableWidgetItem(f"{order.get('commission', 0):.2f}")
            comm_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._orders_table.setItem(i, 7, comm_item)

            tax_item = QTableWidgetItem(f"{order.get('tax', 0):.2f}")
            tax_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._orders_table.setItem(i, 8, tax_item)

            status = order.get("status", "")
            status_item = QTableWidgetItem(status_labels.get(status, status))
            if status == "FILLED":
                status_item.setForeground(self._make_color(COLORS["green"]))
            elif status == "PENDING":
                status_item.setForeground(self._make_color(COLORS["yellow"]))
            elif status in ("CANCELLED", "REJECTED"):
                status_item.setForeground(self._make_color(COLORS["text_muted"]))
            self._orders_table.setItem(i, 9, status_item)

            # 操作列: 撤单按钮
            if status == "PENDING":
                cancel_btn = self.make_danger_btn("撤单")
                cancel_btn.setFixedHeight(28)
                cancel_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
                cancel_btn.clicked.connect(
                    lambda checked, oid=order["id"]: self._on_cancel_order(oid)
                )
                self._orders_table.setCellWidget(i, 10, cancel_btn)
            else:
                self._orders_table.setCellWidget(i, 10, QLabel(""))

    def _refresh_stats(self):
        """刷新交易统计"""
        engine = self._get_engine()
        if not engine:
            return

        stats = engine.get_trade_stats(self._account_id)
        self._update_stat(self._card_trade_count, str(stats["total_trades"]))
        self._update_stat(self._card_filled_count, str(stats["filled_count"]))
        self._update_stat(self._card_win_rate, f"{stats['win_rate']:.1f}%")

        pnl = stats["total_realized_pnl"]
        color = COLORS["green"] if pnl >= 0 else COLORS["red"]
        self._update_stat(self._card_realized_pnl, f"{pnl:+,.2f}", color)

        # 刷新交易历史
        logs = engine.get_trade_logs(self._account_id)
        self._history_table.setRowCount(len(logs))

        for i, log in enumerate(logs):
            self._history_table.setItem(i, 0, QTableWidgetItem(
                str(log.get("created_at", ""))
            ))
            self._history_table.setItem(i, 1, QTableWidgetItem(
                str(log.get("order_id", ""))
            ))
            self._history_table.setItem(i, 2, QTableWidgetItem(log.get("code", "")))

            direction = log.get("direction", "")
            dir_item = QTableWidgetItem("买入" if direction == "BUY" else "卖出")
            dir_color = COLORS["red"] if direction == "BUY" else COLORS["green"]
            dir_item.setForeground(self._make_color(dir_color))
            self._history_table.setItem(i, 3, dir_item)

            qty_item = QTableWidgetItem(str(log.get("quantity", 0)))
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._history_table.setItem(i, 4, qty_item)

            price_item = QTableWidgetItem(f"{log.get('price', 0):.2f}")
            price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._history_table.setItem(i, 5, price_item)

            amt_item = QTableWidgetItem(f"{log.get('amount', 0):,.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._history_table.setItem(i, 6, amt_item)

            comm_item = QTableWidgetItem(f"{log.get('commission', 0):.2f}")
            comm_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._history_table.setItem(i, 7, comm_item)

            tax_item = QTableWidgetItem(f"{log.get('tax', 0):.2f}")
            tax_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._history_table.setItem(i, 8, tax_item)

            rpnl = log.get("realized_pnl", 0)
            rpnl_item = QTableWidgetItem(f"{rpnl:+.2f}")
            rpnl_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rpnl_color = COLORS["green"] if rpnl >= 0 else COLORS["red"]
            rpnl_item.setForeground(self._make_color(rpnl_color))
            self._history_table.setItem(i, 9, rpnl_item)

    # ═══════════════════════════════════════════
    # 事件处理
    # ═══════════════════════════════════════════

    def _on_order_type_changed(self, index):
        """订单类型变更时启用/禁用价格输入"""
        is_market = (index == 0)
        self._price_input.setEnabled(not is_market)
        if is_market:
            self._price_input.setValue(0)

    def _update_fee_estimate(self):
        """更新预估费用"""
        engine = self._get_engine()
        if not engine:
            self._fee_label.setText("--")
            return

        code = self._code_input.text().strip()
        if not code:
            self._fee_label.setText("--")
            return

        quantity = self._quantity_spin.value()
        price = self._price_input.value()

        # 如果是市价单，尝试从行情缓存取价格
        if price <= 0:
            quote = engine._quotes_cache.get(code, {})
            if isinstance(quote, dict):
                price = quote.get("price", 0)
        if price <= 0:
            self._fee_label.setText("--")
            return

        direction = "BUY" if self._direction_combo.currentIndex() == 0 else "SELL"
        try:
            fee_info = engine.fee_calc.calculate(code, direction, quantity, price)
            self._fee_label.setText(f"{fee_info['total_cost']:.2f} {fee_info['currency']}")
        except Exception:
            self._fee_label.setText("--")

    def _on_place_order(self):
        """下单"""
        engine = self._get_engine()
        if not engine:
            QMessageBox.warning(self, "提示", "交易引擎未初始化")
            return

        code = self._code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "提示", "请输入股票代码")
            return

        direction = "BUY" if self._direction_combo.currentIndex() == 0 else "SELL"
        type_map = {0: "MARKET", 1: "LIMIT", 2: "STOP"}
        order_type = type_map.get(self._order_type_combo.currentIndex(), "MARKET")
        quantity = self._quantity_spin.value()
        price = self._price_input.value() if order_type != "MARKET" else None

        # 市价单取行情价格
        if order_type == "MARKET":
            quote = engine._quotes_cache.get(code, {})
            if isinstance(quote, dict):
                price = quote.get("price", 0)
            if not price or price <= 0:
                QMessageBox.warning(self, "提示", f"无法获取 {code} 的实时价格，请确保行情已连接")
                return

        if order_type in ("LIMIT", "STOP") and (not price or price <= 0):
            QMessageBox.warning(self, "提示", "限价/止损单需要设置价格")
            return

        order_id = engine.place_order(
            self._account_id, code, direction, quantity,
            order_type=order_type, price=price
        )

        if order_id > 0:
            dir_text = "买入" if direction == "BUY" else "卖出"
            self._main.log(f"下单成功: #{order_id} {dir_text} {code} x{quantity}")
            self._refresh_all()
        else:
            QMessageBox.warning(self, "下单失败", "持仓不足或资金不足")

    def _on_quick_sell(self, code, quantity):
        """快速卖出持仓"""
        engine = self._get_engine()
        if not engine:
            return
        reply = QMessageBox.question(
            self, "确认卖出",
            f"确认市价卖出 {code} x{quantity}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            quote = engine._quotes_cache.get(code, {})
            price = quote.get("price", 0) if isinstance(quote, dict) else 0
            if price <= 0:
                QMessageBox.warning(self, "提示", f"无法获取 {code} 的实时价格")
                return
            order_id = engine.place_order(
                self._account_id, code, "SELL", quantity,
                order_type="MARKET", price=price,
            )
            if order_id > 0:
                self._main.log(f"卖出成功: #{order_id} {code} x{quantity}")
                self._refresh_all()

    def _on_cancel_order(self, order_id):
        """撤销订单"""
        engine = self._get_engine()
        if not engine:
            return
        if engine.cancel_order(order_id):
            self._main.log(f"已撤销订单 #{order_id}")
            self._refresh_all()

    # ═══════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════

    def _update_stat(self, card, value_text, color=None):
        """更新统计卡片数值"""
        for child in card.findChildren(QLabel):
            if child.objectName() == "statValue":
                child.setText(str(value_text))
                if color:
                    child.setStyleSheet(
                        f"color: {color}; font-size: 28px; font-weight: bold;"
                    )
                break

    def _make_color(self, hex_color):
        """从 hex 颜色创建 QColor/QBrush"""
        from PySide6.QtGui import QColor, QBrush
        return QBrush(QColor(hex_color))
