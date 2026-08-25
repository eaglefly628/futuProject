"""策略编辑器面板 - 策略创建、编辑、回测"""
import json
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QWidget,
    QSplitter, QListWidget, QListWidgetItem, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QMessageBox, QGroupBox, QScrollArea, QDateEdit,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFont
from gui.panels.base import BasePanel
from gui.theme import COLORS
from loguru import logger


# 可视化条件中的指标选项
INDICATOR_OPTIONS = [
    ("最新价", "price"),
    ("MA(5)", "ma_5"),
    ("MA(10)", "ma_10"),
    ("MA(20)", "ma_20"),
    ("MA(60)", "ma_60"),
    ("MACD DIF", "macd_dif"),
    ("MACD DEA", "macd_dea"),
    ("RSI(14)", "rsi_14"),
    ("KDJ-K", "kdj_k"),
    ("KDJ-D", "kdj_d"),
    ("BOLL上轨", "boll_upper"),
    ("BOLL下轨", "boll_lower"),
    ("量比", "volume_ratio"),
]

# 操作符选项
OPERATOR_OPTIONS = [
    ("大于", "gt"),
    ("小于", "lt"),
    ("上穿", "cross_up"),
    ("下穿", "cross_down"),
    ("金叉", "golden_cross"),
    ("死叉", "dead_cross"),
]


class ConditionRow(QWidget):
    """单个条件行"""

    def __init__(self, parent_panel, index=0):
        super().__init__()
        self._parent_panel = parent_panel
        self._index = index
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 指标选择
        self.indicator_combo = QComboBox()
        for label, _value in INDICATOR_OPTIONS:
            self.indicator_combo.addItem(label)
        self.indicator_combo.setFixedWidth(140)
        layout.addWidget(self.indicator_combo)

        # 操作符选择
        self.operator_combo = QComboBox()
        for label, _value in OPERATOR_OPTIONS:
            self.operator_combo.addItem(label)
        self.operator_combo.setFixedWidth(100)
        layout.addWidget(self.operator_combo)

        # 数值输入
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(-999999, 999999)
        self.value_spin.setDecimals(2)
        self.value_spin.setValue(0)
        self.value_spin.setFixedWidth(120)
        layout.addWidget(self.value_spin)

        # 删除按钮
        remove_btn = QPushButton("X")
        remove_btn.setFixedSize(28, 28)
        remove_btn.setStyleSheet(
            f"background-color: {COLORS['red']}; color: #fff; "
            f"border: none; border-radius: 4px; font-weight: bold;"
        )
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.clicked.connect(self._on_remove)
        layout.addWidget(remove_btn)

        layout.addStretch()

    def _on_remove(self):
        """移除此条件行"""
        self._parent_panel._remove_condition_row(self)

    def get_condition(self) -> dict:
        """获取条件数据"""
        ind_idx = self.indicator_combo.currentIndex()
        op_idx = self.operator_combo.currentIndex()
        value = self.value_spin.value()

        ind_key = INDICATOR_OPTIONS[ind_idx][1] if ind_idx < len(INDICATOR_OPTIONS) else "price"
        op_key = OPERATOR_OPTIONS[op_idx][1] if op_idx < len(OPERATOR_OPTIONS) else "gt"

        # 转换为策略引擎能识别的条件格式
        cond = self._convert_to_engine_condition(ind_key, op_key, value)
        return cond

    def _convert_to_engine_condition(self, ind_key, op_key, value) -> dict:
        """将可视化条件转换为引擎条件格式"""
        # 价格相关
        if ind_key == "price":
            if op_key in ("gt", "cross_up"):
                return {"type": "price_above", "params": {"value": value}}
            elif op_key in ("lt", "cross_down"):
                return {"type": "price_below", "params": {"value": value}}

        # MA 交叉
        if ind_key.startswith("ma_"):
            period = int(ind_key.split("_")[1])
            if op_key in ("cross_up", "golden_cross"):
                return {"type": "price_cross_ma", "params": {"period": period, "direction": "up"}}
            elif op_key in ("cross_down", "dead_cross"):
                return {"type": "price_cross_ma", "params": {"period": period, "direction": "down"}}
            elif op_key == "gt":
                return {"type": "price_cross_ma", "params": {"period": period, "direction": "up"}}
            elif op_key == "lt":
                return {"type": "price_cross_ma", "params": {"period": period, "direction": "down"}}

        # MACD
        if ind_key == "macd_dif" or ind_key == "macd_dea":
            if op_key in ("golden_cross", "cross_up"):
                return {"type": "macd_golden_cross", "params": {}}
            elif op_key in ("dead_cross", "cross_down"):
                return {"type": "macd_dead_cross", "params": {}}
            elif op_key == "gt":
                return {"type": "macd_golden_cross", "params": {}}
            elif op_key == "lt":
                return {"type": "macd_dead_cross", "params": {}}

        # RSI
        if ind_key == "rsi_14":
            if op_key in ("gt", "cross_up"):
                return {"type": "rsi_above", "params": {"period": 14, "value": value}}
            elif op_key in ("lt", "cross_down"):
                return {"type": "rsi_below", "params": {"period": 14, "value": value}}

        # KDJ
        if ind_key in ("kdj_k", "kdj_d"):
            if op_key in ("golden_cross", "cross_up"):
                return {"type": "kdj_golden_cross", "params": {}}
            elif op_key in ("dead_cross", "cross_down"):
                return {"type": "kdj_dead_cross", "params": {}}

        # BOLL
        if ind_key == "boll_upper":
            if op_key in ("cross_up", "gt"):
                return {"type": "boll_break_upper", "params": {}}
            elif op_key in ("cross_down", "lt"):
                return {"type": "boll_break_lower", "params": {}}
        if ind_key == "boll_lower":
            if op_key in ("cross_down", "lt"):
                return {"type": "boll_break_lower", "params": {}}
            elif op_key in ("cross_up", "gt"):
                return {"type": "boll_break_upper", "params": {}}

        # 量比
        if ind_key == "volume_ratio":
            if op_key in ("gt", "cross_up"):
                return {"type": "volume_ratio_above", "params": {"value": value}}

        # 默认
        return {"type": "price_above", "params": {"value": value}}

    def set_condition(self, cond: dict):
        """从条件数据恢复 UI 状态"""
        ctype = cond.get("type", "")
        params = cond.get("params", {})

        # 反向映射: 引擎条件 -> 可视化控件状态
        ind_idx = 0
        op_idx = 0
        value = params.get("value", 0)

        if ctype == "price_above":
            ind_idx = 0
            op_idx = 0
        elif ctype == "price_below":
            ind_idx = 0
            op_idx = 1
        elif ctype == "price_cross_ma":
            period = params.get("period", 20)
            period_map = {5: 1, 10: 2, 20: 3, 60: 4}
            ind_idx = period_map.get(period, 3)
            direction = params.get("direction", "up")
            op_idx = 2 if direction == "up" else 3
        elif ctype == "macd_golden_cross":
            ind_idx = 5
            op_idx = 4
        elif ctype == "macd_dead_cross":
            ind_idx = 5
            op_idx = 5
        elif ctype == "rsi_above":
            ind_idx = 7
            op_idx = 0
            value = params.get("value", 70)
        elif ctype == "rsi_below":
            ind_idx = 7
            op_idx = 1
            value = params.get("value", 30)
        elif ctype == "kdj_golden_cross":
            ind_idx = 8
            op_idx = 4
        elif ctype == "kdj_dead_cross":
            ind_idx = 8
            op_idx = 5
        elif ctype == "boll_break_upper":
            ind_idx = 10
            op_idx = 2
        elif ctype == "boll_break_lower":
            ind_idx = 11
            op_idx = 3
        elif ctype == "volume_ratio_above":
            ind_idx = 12
            op_idx = 0
            value = params.get("value", 2.0)

        self.indicator_combo.setCurrentIndex(min(ind_idx, self.indicator_combo.count() - 1))
        self.operator_combo.setCurrentIndex(min(op_idx, self.operator_combo.count() - 1))
        self.value_spin.setValue(value or 0)


class StrategyEditorPanel(BasePanel):
    """策略编辑器面板"""

    def __init__(self, main_window):
        super().__init__(main_window, "策略管理", "创建、编辑和回测交易策略")
        self._strategy_engine = None
        self._current_strategy = None
        self._condition_rows = []
        self._build()

    def _get_engine(self):
        """延迟获取策略引擎"""
        if self._strategy_engine is None:
            self._strategy_engine = getattr(self._main, "strategy_engine", None)
        return self._strategy_engine

    def _build(self):
        """构建界面"""
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background: transparent; width: 6px; }"
        )

        # ─── 左侧: 策略列表 ───
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        new_btn = self.make_primary_btn("新建策略", self._on_new_strategy)
        new_btn.setFixedHeight(32)
        btn_row.addWidget(new_btn)
        del_btn = self.make_danger_btn("删除", self._on_delete_strategy)
        del_btn.setFixedHeight(32)
        btn_row.addWidget(del_btn)
        left_layout.addLayout(btn_row)

        # 策略列表
        self._strategy_list = QListWidget()
        self._strategy_list.setMinimumWidth(200)
        self._strategy_list.setMaximumWidth(260)
        self._strategy_list.currentRowChanged.connect(self._on_strategy_selected)
        left_layout.addWidget(self._strategy_list)

        splitter.addWidget(left_panel)

        # ─── 右侧: 策略编辑区 ───
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(12)

        # 使用 ScrollArea 包裹右侧内容
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        self._editor_layout = QVBoxLayout(scroll_content)
        self._editor_layout.setContentsMargins(0, 0, 8, 8)
        self._editor_layout.setSpacing(12)
        self._build_editor(self._editor_layout)
        scroll.setWidget(scroll_content)
        right_layout.addWidget(scroll)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self.add_widget(splitter)

    def _build_editor(self, layout):
        """构建编辑区"""
        # ─── 策略名称 ───
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.addWidget(QLabel("策略名称:"))
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("输入策略名称")
        name_row.addWidget(self._name_input)
        layout.addLayout(name_row)

        # ─── 目标股票 ───
        target_card, target_layout = self.make_card("目标股票")
        target_row = QHBoxLayout()
        target_row.setContentsMargins(0, 0, 0, 0)
        self._target_input = QLineEdit()
        self._target_input.setPlaceholderText("输入股票代码，如 US.AAPL")
        self._target_input.returnPressed.connect(self._on_add_target)
        target_row.addWidget(self._target_input)
        add_target_btn = self.make_primary_btn("添加", self._on_add_target)
        add_target_btn.setFixedHeight(32)
        target_row.addWidget(add_target_btn)
        target_layout.addLayout(target_row)

        self._target_list = QListWidget()
        self._target_list.setMaximumHeight(100)
        target_layout.addWidget(self._target_list)

        remove_target_btn = self.make_danger_btn("移除选中", self._on_remove_target)
        remove_target_btn.setFixedHeight(28)
        target_layout.addWidget(remove_target_btn)
        layout.addWidget(target_card)

        # ─── 模式切换 ───
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.addWidget(QLabel("策略模式:"))
        self._visual_mode_btn = QPushButton("可视化模式")
        self._visual_mode_btn.setCheckable(True)
        self._visual_mode_btn.setChecked(True)
        self._visual_mode_btn.setCursor(Qt.PointingHandCursor)
        self._visual_mode_btn.clicked.connect(lambda: self._switch_mode("visual"))
        mode_row.addWidget(self._visual_mode_btn)

        self._script_mode_btn = QPushButton("Python脚本模式")
        self._script_mode_btn.setCheckable(True)
        self._script_mode_btn.setCursor(Qt.PointingHandCursor)
        self._script_mode_btn.clicked.connect(lambda: self._switch_mode("script"))
        mode_row.addWidget(self._script_mode_btn)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # ─── 可视化模式区域 ───
        self._visual_widget = QWidget()
        visual_layout = QVBoxLayout(self._visual_widget)
        visual_layout.setContentsMargins(0, 0, 0, 0)
        visual_layout.setSpacing(8)
        self._build_visual_mode(visual_layout)
        layout.addWidget(self._visual_widget)

        # ─── 脚本模式区域 ───
        self._script_widget = QWidget()
        script_layout = QVBoxLayout(self._script_widget)
        script_layout.setContentsMargins(0, 0, 0, 0)
        script_layout.setSpacing(8)
        self._build_script_mode(script_layout)
        self._script_widget.hide()
        layout.addWidget(self._script_widget)

        # ─── 操作按钮 ───
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        save_btn = self.make_primary_btn("保存", self._on_save)
        save_btn.setFixedHeight(36)
        action_row.addWidget(save_btn)

        self._toggle_btn = QPushButton("启用")
        self._toggle_btn.setFixedHeight(36)
        self._toggle_btn.setStyleSheet(
            f"background-color: {COLORS['green']}; color: #fff; "
            f"border: none; border-radius: 6px; font-weight: bold; padding: 8px 20px;"
        )
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._on_toggle)
        action_row.addWidget(self._toggle_btn)

        backtest_btn = QPushButton("回测")
        backtest_btn.setFixedHeight(36)
        backtest_btn.setStyleSheet(
            f"background-color: {COLORS['purple']}; color: #fff; "
            f"border: none; border-radius: 6px; font-weight: bold; padding: 8px 20px;"
        )
        backtest_btn.setCursor(Qt.PointingHandCursor)
        backtest_btn.clicked.connect(self._on_backtest)
        action_row.addWidget(backtest_btn)

        action_row.addStretch()
        layout.addLayout(action_row)

        # ─── 回测参数 ───
        bt_params_card, bt_params_layout = self.make_card("回测参数")
        bt_params_row = QHBoxLayout()
        bt_params_row.setContentsMargins(0, 0, 0, 0)
        bt_params_row.addWidget(QLabel("起始日期:"))
        self._bt_start_date = QDateEdit()
        self._bt_start_date.setCalendarPopup(True)
        self._bt_start_date.setDate(QDate.currentDate().addMonths(-6))
        self._bt_start_date.setDisplayFormat("yyyy-MM-dd")
        bt_params_row.addWidget(self._bt_start_date)

        bt_params_row.addWidget(QLabel("结束日期:"))
        self._bt_end_date = QDateEdit()
        self._bt_end_date.setCalendarPopup(True)
        self._bt_end_date.setDate(QDate.currentDate())
        self._bt_end_date.setDisplayFormat("yyyy-MM-dd")
        bt_params_row.addWidget(self._bt_end_date)

        bt_params_row.addWidget(QLabel("初始资金:"))
        self._bt_cash_spin = QDoubleSpinBox()
        self._bt_cash_spin.setRange(10000, 100000000)
        self._bt_cash_spin.setValue(1000000)
        self._bt_cash_spin.setDecimals(0)
        self._bt_cash_spin.setSingleStep(100000)
        self._bt_cash_spin.setPrefix("CNY ")
        bt_params_row.addWidget(self._bt_cash_spin)
        bt_params_row.addStretch()
        bt_params_layout.addLayout(bt_params_row)
        layout.addWidget(bt_params_card)

        # ─── 回测结果区域 (初始隐藏) ───
        self._backtest_result_widget = QWidget()
        bt_layout = QVBoxLayout(self._backtest_result_widget)
        bt_layout.setContentsMargins(0, 0, 0, 0)
        bt_layout.setSpacing(12)
        self._build_backtest_result(bt_layout)
        self._backtest_result_widget.hide()
        layout.addWidget(self._backtest_result_widget)

        layout.addStretch()

    def _build_visual_mode(self, layout):
        """构建可视化条件模式"""
        cond_card, cond_layout = self.make_card("触发条件")

        # 逻辑组合
        logic_row = QHBoxLayout()
        logic_row.setContentsMargins(0, 0, 0, 0)
        logic_row.addWidget(QLabel("条件逻辑:"))
        self._logic_combo = QComboBox()
        self._logic_combo.addItems(["AND (全部满足)", "OR (任一满足)"])
        self._logic_combo.setFixedWidth(180)
        logic_row.addWidget(self._logic_combo)
        logic_row.addStretch()
        cond_layout.addLayout(logic_row)

        # 条件行容器
        self._conditions_container = QVBoxLayout()
        self._conditions_container.setSpacing(6)
        cond_layout.addLayout(self._conditions_container)

        # 添加条件按钮
        add_cond_btn = QPushButton("+ 添加条件")
        add_cond_btn.setFixedHeight(32)
        add_cond_btn.setStyleSheet(
            f"background-color: {COLORS['bg_hover']}; border: 1px dashed {COLORS['border_light']}; "
            f"border-radius: 6px; color: {COLORS['text_secondary']};"
        )
        add_cond_btn.setCursor(Qt.PointingHandCursor)
        add_cond_btn.clicked.connect(self._on_add_condition)
        cond_layout.addWidget(add_cond_btn)

        layout.addWidget(cond_card)

        # ─── 执行动作 ───
        action_card, action_layout = self.make_card("执行动作")
        action_grid = QGridLayout()
        action_grid.setContentsMargins(0, 0, 0, 0)
        action_grid.setSpacing(8)

        action_grid.addWidget(QLabel("方向:"), 0, 0)
        self._action_direction = QComboBox()
        self._action_direction.addItems(["买入 (BUY)", "卖出 (SELL)"])
        self._action_direction.setFixedWidth(160)
        action_grid.addWidget(self._action_direction, 0, 1)

        action_grid.addWidget(QLabel("数量:"), 0, 2)
        self._action_quantity = QSpinBox()
        self._action_quantity.setRange(1, 9999999)
        self._action_quantity.setValue(100)
        self._action_quantity.setSingleStep(100)
        action_grid.addWidget(self._action_quantity, 0, 3)

        action_grid.addWidget(QLabel("止损%:"), 1, 0)
        self._stop_loss_spin = QDoubleSpinBox()
        self._stop_loss_spin.setRange(0, 50)
        self._stop_loss_spin.setDecimals(1)
        self._stop_loss_spin.setValue(5.0)
        self._stop_loss_spin.setSuffix(" %")
        action_grid.addWidget(self._stop_loss_spin, 1, 1)

        action_grid.addWidget(QLabel("止盈%:"), 1, 2)
        self._take_profit_spin = QDoubleSpinBox()
        self._take_profit_spin.setRange(0, 100)
        self._take_profit_spin.setDecimals(1)
        self._take_profit_spin.setValue(10.0)
        self._take_profit_spin.setSuffix(" %")
        action_grid.addWidget(self._take_profit_spin, 1, 3)

        action_layout.addLayout(action_grid)
        layout.addWidget(action_card)

    def _build_script_mode(self, layout):
        """构建脚本模式"""
        script_card, script_layout = self.make_card("Python 策略脚本")

        # 模板按钮
        template_btn = QPushButton("插入模板代码")
        template_btn.setFixedHeight(28)
        template_btn.setStyleSheet(f"font-size: 11px;")
        template_btn.setCursor(Qt.PointingHandCursor)
        template_btn.clicked.connect(self._on_insert_template)
        script_layout.addWidget(template_btn)

        # 脚本编辑区
        self._script_edit = QPlainTextEdit()
        self._script_edit.setMinimumHeight(300)
        mono_font = QFont("SF Mono", 12)
        mono_font.setStyleHint(QFont.Monospace)
        self._script_edit.setFont(mono_font)
        self._script_edit.setPlaceholderText(
            "# 在此编写策略脚本\n"
            "# 可用变量: quote, kline_df, indicators, account, code\n"
            "# 设置 result['signal'] = 'buy' 或 'sell' 来触发交易\n"
            "# 设置 result['quantity'] = 数量\n"
            "# 设置 result['price'] = 价格 (可选)\n"
        )
        script_layout.addWidget(self._script_edit)
        layout.addWidget(script_card)

    def _build_backtest_result(self, layout):
        """构建回测结果区域"""
        # 统计卡片
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(12)
        self._bt_card_return = self.make_stat_card("收益率", "--", COLORS["accent"])
        self._bt_card_drawdown = self.make_stat_card("最大回撤", "--", COLORS["red"])
        self._bt_card_sharpe = self.make_stat_card("夏普比率", "--", COLORS["blue"])
        self._bt_card_winrate = self.make_stat_card("胜率", "--", COLORS["green"])
        self._bt_card_trades = self.make_stat_card("交易次数", "--", COLORS["purple"])
        stats_row.addWidget(self._bt_card_return)
        stats_row.addWidget(self._bt_card_drawdown)
        stats_row.addWidget(self._bt_card_sharpe)
        stats_row.addWidget(self._bt_card_winrate)
        stats_row.addWidget(self._bt_card_trades)
        layout.addLayout(stats_row)

        # 交易记录表
        trades_card, trades_layout = self.make_card("回测交易记录")
        self._bt_trades_table = QTableWidget()
        self._bt_trades_table.setMinimumHeight(200)
        self._bt_trades_table.setColumnCount(8)
        self._bt_trades_table.setHorizontalHeaderLabels([
            "日期", "代码", "方向", "数量", "价格", "金额", "费用", "盈亏"
        ])
        self._bt_trades_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._bt_trades_table.verticalHeader().setVisible(False)
        self._bt_trades_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._bt_trades_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._bt_trades_table.setAlternatingRowColors(True)
        self._bt_trades_table.setMaximumHeight(250)
        trades_layout.addWidget(self._bt_trades_table)
        layout.addWidget(trades_card)

    # ═══════════════════════════════════════════
    # 事件处理
    # ═══════════════════════════════════════════

    def on_show(self):
        """面板显示时刷新"""
        self._refresh_strategy_list()

    def _refresh_strategy_list(self):
        """刷新策略列表"""
        engine = self._get_engine()
        if not engine:
            return

        self._strategy_list.clear()
        strategies = engine.load_strategies()

        for strat in strategies:
            name = strat.get("name", "未命名")
            enabled = strat.get("enabled", False)
            prefix = "[ON] " if enabled else "[OFF] "
            item = QListWidgetItem(prefix + name)
            if enabled:
                item.setForeground(self._make_color(COLORS["green"]))
            else:
                item.setForeground(self._make_color(COLORS["text_secondary"]))
            item.setData(Qt.UserRole, strat["id"])
            self._strategy_list.addItem(item)

    def _on_strategy_selected(self, row):
        """策略列表选择变化"""
        if row < 0:
            self._current_strategy = None
            return
        item = self._strategy_list.item(row)
        if not item:
            return
        strategy_id = item.data(Qt.UserRole)
        engine = self._get_engine()
        if not engine:
            return
        strategies = engine.load_strategies()
        for s in strategies:
            if s["id"] == strategy_id:
                self._current_strategy = s
                self._load_strategy_to_editor(s)
                break

    def _load_strategy_to_editor(self, strat: dict):
        """将策略数据加载到编辑器"""
        self._name_input.setText(strat.get("name", ""))

        # 目标股票
        self._target_list.clear()
        for code in strat.get("target_codes", []):
            self._target_list.addItem(code)

        # 模式
        mode = strat.get("mode", "visual")
        self._switch_mode(mode)

        # 可视化条件
        self._clear_condition_rows()
        conditions = strat.get("conditions", {})
        logic = conditions.get("logic", "AND")
        self._logic_combo.setCurrentIndex(0 if logic == "AND" else 1)

        for item in conditions.get("items", []):
            row = self._add_condition_row()
            row.set_condition(item)

        # 动作
        action = strat.get("action", {})
        direction = action.get("direction", "BUY")
        self._action_direction.setCurrentIndex(0 if direction == "BUY" else 1)
        self._action_quantity.setValue(int(action.get("quantity", 100)))
        self._stop_loss_spin.setValue(float(action.get("stop_loss_pct", 5.0)))
        self._take_profit_spin.setValue(float(action.get("take_profit_pct", 10.0)))

        # 脚本
        self._script_edit.setPlainText(strat.get("script", ""))

        # 启用/停用按钮
        enabled = strat.get("enabled", False)
        self._update_toggle_btn(enabled)

    def _update_toggle_btn(self, enabled):
        """更新启用/停用按钮状态"""
        if enabled:
            self._toggle_btn.setText("停用")
            self._toggle_btn.setStyleSheet(
                f"background-color: {COLORS['red']}; color: #fff; "
                f"border: none; border-radius: 6px; font-weight: bold; padding: 8px 20px;"
            )
        else:
            self._toggle_btn.setText("启用")
            self._toggle_btn.setStyleSheet(
                f"background-color: {COLORS['green']}; color: #fff; "
                f"border: none; border-radius: 6px; font-weight: bold; padding: 8px 20px;"
            )

    def _switch_mode(self, mode):
        """切换可视化/脚本模式"""
        if mode == "visual":
            self._visual_widget.show()
            self._script_widget.hide()
            self._visual_mode_btn.setChecked(True)
            self._script_mode_btn.setChecked(False)
        else:
            self._visual_widget.hide()
            self._script_widget.show()
            self._visual_mode_btn.setChecked(False)
            self._script_mode_btn.setChecked(True)

    # ─── 条件行管理 ───

    def _on_add_condition(self):
        """添加条件行"""
        self._add_condition_row()

    def _add_condition_row(self) -> ConditionRow:
        """添加一个条件行并返回"""
        row = ConditionRow(self, len(self._condition_rows))
        self._condition_rows.append(row)
        self._conditions_container.addWidget(row)
        return row

    def _remove_condition_row(self, row: ConditionRow):
        """移除条件行"""
        if row in self._condition_rows:
            self._condition_rows.remove(row)
            self._conditions_container.removeWidget(row)
            row.deleteLater()

    def _clear_condition_rows(self):
        """清空所有条件行"""
        for row in self._condition_rows[:]:
            self._conditions_container.removeWidget(row)
            row.deleteLater()
        self._condition_rows.clear()

    # ─── 目标股票 ───

    def _on_add_target(self):
        """添加目标股票"""
        code = self._target_input.text().strip()
        if not code:
            return
        # 检查重复
        for i in range(self._target_list.count()):
            if self._target_list.item(i).text() == code:
                return
        self._target_list.addItem(code)
        self._target_input.clear()

    def _on_remove_target(self):
        """移除选中的目标股票"""
        current = self._target_list.currentRow()
        if current >= 0:
            self._target_list.takeItem(current)

    # ─── 策略操作 ───

    def _on_new_strategy(self):
        """新建策略"""
        engine = self._get_engine()
        if not engine:
            QMessageBox.warning(self, "提示", "策略引擎未初始化")
            return

        new_strat = {
            "name": "新策略",
            "mode": "visual",
            "target_codes": [],
            "conditions": {"logic": "AND", "items": []},
            "action": {
                "direction": "BUY",
                "quantity": 100,
                "stop_loss_pct": 5.0,
                "take_profit_pct": 10.0,
            },
            "script": "",
            "enabled": False,
            "account_id": 1,
        }
        sid = engine.save_strategy(new_strat)
        new_strat["id"] = sid
        self._main.log(f"已创建新策略 #{sid}")
        self._refresh_strategy_list()

        # 选中新策略
        for i in range(self._strategy_list.count()):
            item = self._strategy_list.item(i)
            if item.data(Qt.UserRole) == sid:
                self._strategy_list.setCurrentRow(i)
                break

    def _on_delete_strategy(self):
        """删除策略"""
        if not self._current_strategy:
            QMessageBox.warning(self, "提示", "请先选择一个策略")
            return
        engine = self._get_engine()
        if not engine:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确认删除策略 \"{self._current_strategy.get('name', '')}\"?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            engine.delete_strategy(self._current_strategy["id"])
            self._main.log(f"已删除策略 #{self._current_strategy['id']}")
            self._current_strategy = None
            self._refresh_strategy_list()

    def _on_save(self):
        """保存策略"""
        if not self._current_strategy:
            QMessageBox.warning(self, "提示", "请先选择或创建一个策略")
            return
        engine = self._get_engine()
        if not engine:
            return

        strat = self._current_strategy.copy()
        strat["name"] = self._name_input.text().strip() or "未命名"

        # 目标股票
        targets = []
        for i in range(self._target_list.count()):
            targets.append(self._target_list.item(i).text())
        strat["target_codes"] = targets

        # 模式
        is_visual = self._visual_mode_btn.isChecked()
        strat["mode"] = "visual" if is_visual else "script"

        # 可视化条件
        logic = "AND" if self._logic_combo.currentIndex() == 0 else "OR"
        items = [row.get_condition() for row in self._condition_rows]
        strat["conditions"] = {"logic": logic, "items": items}

        # 动作
        strat["action"] = {
            "direction": "BUY" if self._action_direction.currentIndex() == 0 else "SELL",
            "quantity": self._action_quantity.value(),
            "stop_loss_pct": self._stop_loss_spin.value(),
            "take_profit_pct": self._take_profit_spin.value(),
        }

        # 脚本
        strat["script"] = self._script_edit.toPlainText()

        engine.save_strategy(strat)
        self._main.log(f"策略 \"{strat['name']}\" 已保存")
        self._refresh_strategy_list()

        # 重新选中
        for i in range(self._strategy_list.count()):
            item = self._strategy_list.item(i)
            if item.data(Qt.UserRole) == strat["id"]:
                self._strategy_list.setCurrentRow(i)
                break

    def _on_toggle(self):
        """启用/停用策略"""
        if not self._current_strategy:
            QMessageBox.warning(self, "提示", "请先选择一个策略")
            return
        engine = self._get_engine()
        if not engine:
            return

        current_enabled = self._current_strategy.get("enabled", False)
        new_enabled = not current_enabled
        engine.toggle_strategy(self._current_strategy["id"], new_enabled)
        self._current_strategy["enabled"] = new_enabled
        self._update_toggle_btn(new_enabled)

        state = "启用" if new_enabled else "停用"
        self._main.log(f"策略 \"{self._current_strategy.get('name', '')}\" 已{state}")
        self._refresh_strategy_list()

    def _on_insert_template(self):
        """插入脚本模板"""
        template = '''# 策略脚本模板
# 可用变量:
#   quote: dict - 当前行情 {price, volume, ...}
#   kline_df: DataFrame - 历史 K 线 (open, high, low, close, volume)
#   indicators: IndicatorEngine - 技术指标计算
#   account: dict - 账户信息 {cash, total_asset, ...}
#   code: str - 当前股票代码
#   result: dict - 设置交易信号

# 计算指标
ma5 = indicators.ma(kline_df, period=5)
ma20 = indicators.ma(kline_df, period=20)

# 判断金叉
if len(ma5) >= 2 and len(ma20) >= 2:
    if ma5.iloc[-2] <= ma20.iloc[-2] and ma5.iloc[-1] > ma20.iloc[-1]:
        result["signal"] = "buy"
        result["quantity"] = 100
        result["price"] = quote["price"]

    # 判断死叉
    if ma5.iloc[-2] >= ma20.iloc[-2] and ma5.iloc[-1] < ma20.iloc[-1]:
        result["signal"] = "sell"
        result["quantity"] = 100
        result["price"] = quote["price"]
'''
        self._script_edit.setPlainText(template)

    # ─── 回测 ───

    def _on_backtest(self):
        """执行回测"""
        if not self._current_strategy:
            QMessageBox.warning(self, "提示", "请先保存策略")
            return

        # 先保存
        self._on_save()

        engine = self._get_engine()
        if not engine:
            QMessageBox.warning(self, "提示", "策略引擎未初始化")
            return

        # 获取目标股票
        targets = []
        for i in range(self._target_list.count()):
            targets.append(self._target_list.item(i).text())
        if not targets:
            QMessageBox.warning(self, "提示", "请添加目标股票")
            return

        start_date = self._bt_start_date.date().toString("yyyy-MM-dd")
        end_date = self._bt_end_date.date().toString("yyyy-MM-dd")
        initial_cash = self._bt_cash_spin.value()

        try:
            from trading.fee_calculator import FeeCalculator
            from strategy.indicators import IndicatorEngine
            from strategy.backtester import Backtester

            fee_calc = FeeCalculator(self._main.config)
            ind = IndicatorEngine()
            backtester = Backtester(self._main.db, fee_calc, ind)

            bt_result = backtester.run(
                self._current_strategy, targets,
                start_date, end_date, initial_cash
            )

            self._show_backtest_result(bt_result)
            self._main.log(
                f"回测完成: 收益率={bt_result.total_return:.2f}%, "
                f"最大回撤={bt_result.max_drawdown:.2f}%, "
                f"交易次数={bt_result.total_trades}"
            )
        except Exception as e:
            logger.error(f"回测失败: {e}")
            QMessageBox.critical(self, "回测失败", str(e))

    def _show_backtest_result(self, bt_result):
        """显示回测结果"""
        self._backtest_result_widget.show()

        # 更新统计卡片
        ret_color = COLORS["green"] if bt_result.total_return >= 0 else COLORS["red"]
        self._update_stat(self._bt_card_return, f"{bt_result.total_return:+.2f}%", ret_color)
        self._update_stat(self._bt_card_drawdown, f"{bt_result.max_drawdown:.2f}%")
        self._update_stat(self._bt_card_sharpe, f"{bt_result.sharpe_ratio:.2f}")
        self._update_stat(self._bt_card_winrate, f"{bt_result.win_rate:.1f}%")
        self._update_stat(self._bt_card_trades, str(bt_result.total_trades))

        # 填充交易记录表
        trades = bt_result.trades
        self._bt_trades_table.setRowCount(len(trades))

        for i, trade in enumerate(trades):
            self._bt_trades_table.setItem(i, 0, QTableWidgetItem(trade.get("date", "")))
            self._bt_trades_table.setItem(i, 1, QTableWidgetItem(trade.get("code", "")))

            direction = trade.get("direction", "")
            dir_item = QTableWidgetItem("买入" if direction == "BUY" else "卖出")
            dir_color = COLORS["red"] if direction == "BUY" else COLORS["green"]
            dir_item.setForeground(self._make_color(dir_color))
            self._bt_trades_table.setItem(i, 2, dir_item)

            qty_item = QTableWidgetItem(str(trade.get("quantity", 0)))
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._bt_trades_table.setItem(i, 3, qty_item)

            price_item = QTableWidgetItem(f"{trade.get('price', 0):.2f}")
            price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._bt_trades_table.setItem(i, 4, price_item)

            amt_item = QTableWidgetItem(f"{trade.get('amount', 0):,.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._bt_trades_table.setItem(i, 5, amt_item)

            fees_item = QTableWidgetItem(f"{trade.get('fees', 0):.2f}")
            fees_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._bt_trades_table.setItem(i, 6, fees_item)

            pnl = trade.get("pnl", 0)
            pnl_item = QTableWidgetItem(f"{pnl:+.2f}")
            pnl_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            pnl_color = COLORS["green"] if pnl >= 0 else COLORS["red"]
            pnl_item.setForeground(self._make_color(pnl_color))
            self._bt_trades_table.setItem(i, 7, pnl_item)

    # ═══════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════

    def _update_stat(self, card, value_text, color=None):
        """更新统计卡片"""
        for child in card.findChildren(QLabel):
            if child.objectName() == "statValue":
                child.setText(str(value_text))
                if color:
                    child.setStyleSheet(
                        f"color: {color}; font-size: 28px; font-weight: bold;"
                    )
                break

    def _make_color(self, hex_color):
        """从 hex 颜色创建 QBrush"""
        from PySide6.QtGui import QColor, QBrush
        return QBrush(QColor(hex_color))
