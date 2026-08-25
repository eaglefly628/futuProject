# 项目交接文档

给接手的 AI / 开发者：读完这份就能接着干，不用翻聊天记录。

**更新时间**：2026-08-25
**仓库**：https://github.com/eaglefly628/futuProject （分支 `main`）

---

## 一、项目是什么

个人量化平台，Python + PySide6 桌面应用。

**当前重点：中证 A500 ETF 的技术分析 + 单策略验证。**
不是做自动交易 —— 模拟交易模块只用于验证策略，不接实盘。

```bash
git clone https://github.com/eaglefly628/futuProject.git
cd futuProject
pip install -e .
python main.py
```

---

## 二、用户环境（重要，很多设计取舍源于此）

| 项目 | 情况 |
|------|------|
| 开发机 | macOS（也用过 Windows，两边都要能跑） |
| 网络 | **挂日本代理，网卡级（TUN）** —— 无法用环境变量绕过 |
| Futu 账号 | 港股 LV2、美股 LV3 正常；**上证/深证无权限** |
| OpenD | 10.10.7008，已能自动登录 |

**两条硬约束：**

1. **A 股数据不能走 Futu** —— 账号没有 A 股 ETF 行情权限，API 明确报
   `无权限获取SZ.159338的行情`。这是账号问题，不是代码问题。
2. **国内数据源可能被代理挡住** —— 东财 (`push2his.eastmoney.com`) 在用户机器上
   返回 `ProxyError`。腾讯 (`qt.gtimg.cn`) 实测可通。

所以数据源做成了多路回退，代码里所有 HTTP 客户端默认 `trust_env=False` 绕过系统代理。

---

## 三、当前状态

### 能用的

- **数据采集**：A500 ETF 全周期 K 线，多源自动回退
- **行情图表**：蜡烛图 + 均线 + 成交量 + MACD/KDJ/RSI 副图，滚轮缩放、拖拽平移
- **A500 中心**：采集 + 图表 + 量价分析（5 因子概率预测）一体
- **实时行情**：A 股走腾讯，港美股走 Futu，3 秒刷新 + 价格预警
- **模拟交易**：全市场 CNY 统一账户，A股/港股/美股真实费率
- **策略编辑**：可视化条件 + Python 脚本双模式，13 种指标条件
- **回测**：收益率/最大回撤/夏普/胜率
- **备份恢复**：整库导出 Parquet（比 .db 小 5.7 倍，可进 git）
- **环境诊断**：系统设置 → 🩺 环境诊断，一键查依赖/配置/网络

### 待办

1. **参数可调的单策略** —— 用户明确要过，还没做。
   形式：GUI 里调 MA 周期、RSI 阈值等参数，实时看信号变化，配合回测。
2. **定时采集** —— 1 分钟线所有免费源历史都短（东财约 5 天、Yahoo 7 天），
   靠每天定时跑积累历史是可行路径。数据库已支持增量去重。
3. **QMT 接入**（可选）—— 用户在考虑。迅投 QMT 软件免费，通过券商开通，
   国信证券 iQuant 0 门槛。开通后有实时 + 完整历史 + 实盘接口。

---

## 四、代码结构

```
futuProject/
├── main.py                     GUI 入口
├── config/
│   ├── default.yaml            主配置（提交）
│   └── local.yaml              账号密码（gitignore，deep-merge 覆盖 default）
├── core/
│   ├── client.py               Futu OpenD 客户端
│   ├── opend_launcher.py       OpenD 自动发现/启动/自动登录
│   ├── quote_subscriber.py     Futu 实时订阅
│   └── diagnostics.py          环境诊断（GUI 和 CLI 共用）
├── downloaders/
│   ├── kline_downloader.py     Futu K线（港美股）
│   ├── tick_collector.py       Futu 逐笔
│   ├── eastmoney.py            东财直连（A股，国内网络）
│   ├── yahoo.py                Yahoo（A股，海外网络可通）
│   ├── tencent_quote.py        腾讯实时行情（A股）
│   └── akshare_source.py       A股采集器 + MarketRouter
├── storage/
│   ├── database.py             SQLite，11 张表
│   └── backup.py               Parquet 备份/恢复
├── trading/                    模拟交易 + 费率计算
├── strategy/                   指标 + 策略引擎 + 回测
├── analysis/
│   └── a500_analyzer.py        A500 量价分析 + 趋势预测
├── gui/
│   ├── panels/                 14 个面板
│   └── widgets/chart.py        K线图（纯 QPainter，numpy 优化）
└── scripts/                    诊断和探测脚本
```

---

## 五、数据源策略（核心设计）

### K 线采集

`downloaders/akshare_source.py` 的 `AkshareSource._fetch()` 按顺序尝试：

```
1. 东财 (eastmoney.py)   国内网络最好，分钟线历史最全
2. Yahoo (yahoo.py)      挂代理时这条通
3. akshare               兜底，懒加载（import 很慢，别在启动时加载）
```

命中的源记在 `src.last_source`，失败原因记在 `src.last_error`（GUI 靠它显示「为什么 0 条」）。

`MarketRouter` 按市场分流：A 股 → AkshareSource，港美股 → Futu。

采集类方法统一带两个可选参数，一路透传到最底层：
`should_stop`（返回 True 就尽快停）和 `on_progress`（逐步进度回调）。

**也可以手动指定源**，绕过自动回退。三个采集面板（K线下载 / 批量下载 /
A500中心）都有「数据源」下拉，选项来自 `MarketRouter.SOURCE_OPTIONS`：

| key | 说明 |
|-----|------|
| `auto` | 按市场自动路由 + 依次回退（默认） |
| `eastmoney` | 只用东财，失败不回退 —— 方便定位问题 |
| `yahoo` | 只用 Yahoo（挂代理时通常是这条通） |
| `akshare` | 只用 akshare 兜底 |
| `futu` | 强制走 Futu（A 股会因无权限失败，属预期） |

三个采集面板的控件已对齐，都有：数据源下拉、增量模式、停止按钮、
逐步进度、0 条/停止的原因说明。

指定具体源时**不会静默换源**，这样报出来的错就是那个源的真实错误。
调用侧一路透传 `prefer=` 参数：`router.download_history(..., prefer="yahoo")`。

### 实时行情

`gui/panels/realtime_monitor.py` 的 `_do_refresh()`：A 股 → 腾讯，港美股 → Futu。

### 各源历史深度（实测）

| 周期 | 东财 | Yahoo |
|------|------|-------|
| 1分钟 | ~5 交易日 | 7 天 |
| 5/15/30分钟 | 较长 | ~60 天 |
| 60分钟 | 较长 | **~2 年（2712 条，实测）** |
| 日线 | 完整 | 完整（456 条，从 ETF 上市日起） |

用户接受 Yahoo 的 60 分钟 2 年，这是当前主力周期。

---

## 六、踩过的坑（别重复踩）

### 数据正确性

- **`pd.to_datetime` 返回 Index，不是 list。** 和普通 list 混在一个 dict 里构造
  DataFrame 时，pandas 按 Index 对齐而非按位置，**列数据会整体错位**。
  必须 `list(...)` 转换。这个 bug 表现为「某根 K 线的最高价低于开盘价」。
- **Yahoo 对当日未完成/停牌的 K 线返回 `null`**，只过滤 `close` 不够，
  OHLC 任一缺失都要整行丢弃，并校验 high/low 是否包住 open/close。

### 停止 / 取消

- **不要用 `QThread.terminate()` 停任务。** 线程阻塞在 socket 上时它根本不生效
  （点了停止没反应），真生效了又可能停在 SQLite 写一半的位置。
  统一走 `downloaders/cancel.py` 的协作式取消：任务在循环点查 `should_stop()`，
  自己收尾返回。已落库的数据保留不回滚 —— 采集是增量去重的，下次接着补。
- **退避 sleep 必须可打断。** 指数退避动辄十几秒，`time.sleep` 硬睡的话
  点了停止要等它睡完。用 `sleep_unless_stopped()` 分片等待。
- **停止时不要 `wait()`**，会卡住界面。按钮置灰改成「停止中…」，
  线程自己收尾后走正常的完成回调。

### 数据源路由

- **采集面板不要直连 `main.kline_dl`（Futu），要走 `main.router`。**
  写死 Futu 的话，A 股标的会撞上「无权限」返回 0 条。K线下载/批量下载两个面板
  以前就是这么写的，现象是「✅ 下载完成！共 0 条记录」—— 绿色成功，实则啥也没拿到。
- **0 条不是成功。** 下载器返回 0 时要能说清原因，否则用户只能看到一个 0。
  现在 `AkshareSource` / `KlineDownloader` / `MarketRouter` 都带 `last_error`，
  面板据此显示原因 + 一条可照做的建议（换源、装依赖、改周期）。
- **「要不要连 OpenD」应该按实际路由判断**，不是一进面板就拦。
  A 股走免费源根本不需要 OpenD，用 `router.requires_futu(code, prefer)` 判断。

### 网络

- **东财的 `requests.get()` 不带 User-Agent 会被直接断连**。必须带完整浏览器头。
- **`_fetch` 里把所有源的异常都 catch 掉，外层的重试退避就失效了。**
  原来只有 akshare 路径的异常能触发重试，东财限流/连接重置其实从没退避过。
  现在的做法是：所有源试完一轮后，若全失败且其中有瞬时错误（`RETRIABLE_HINTS`），
  才抛给外层退避重试。**不能在东财失败时立刻抛** —— auto 模式下东财在本机常年
  ProxyError，先抛的话每次都要空退避 4 轮才轮得到 Yahoo。
- **akshare 的分钟线接口会先调 `get_market_id()` 多打一次请求**，
  所以我们自己拼 `secid`（`SH→1.`、`SZ→0.`），零额外请求。
- **所有国内源默认绕过系统代理**（`trust_env=False` + `proxies={}`），
  失败才回退走代理。

### OpenD

- **macOS 上 `.app` 运行时路径会被随机化**，OpenD 找不到自己的 `FutuOpenD.xml`，
  导致「记住密码」存不住、命令行参数也可能不生效。
  解法：把凭据写进 XML + 用 `-cfg_file` 传绝对路径（`opend_launcher.py` 已实现）。
- **`-console=0` 会关掉交互式控制台**，登录进度和验证码提示全都收不到，
  表现为连接无限期挂起。**必须 `-console=1`**。
- **不要靠解析 stdout 判断「登录成功」** —— macOS 上 OpenD 用自己的 TTY 窗口，
  我们的管道收不到。正确做法是**直接试 `get_global_state()`，返回 RET_OK 才算就绪**。
- **端口开着 ≠ OpenD 可用**，可能是上一个实例残留。启动前先探测端口。

### GUI

- **`BasePanel` 的内容区必须放在 `QScrollArea` 里**，否则窗口一小控件就被压到重叠
  （macOS 字体度量更大，先暴露）。
- **QSS 的 `padding` 和布局 `contentsMargins` 会叠加**，卡片内边距统一走
  `BasePanel.CARD_MARGIN`，QSS 里不要写 padding。
- **`QFrame.VLine` 不认 QSS 的 `color`**，要用 `background-color` + 固定宽度。
- **图表绘制不要用 `df.iloc[i]`** —— 每次构造 Series，5000 根时 196ms。
  改成 numpy 数组后 1.8ms（106 倍）。可见窗口做了缓存，见 `chart.py:_ensure_cache`。
- **akshare 必须懒加载**，模块级 import 会让 GUI 启动卡十几秒。
- **勾选框禁用另一个控件时，一定要写明为什么。** 「自动计算起始日期」会 disable
  「开始日期」，没提示的话看起来就像是坏了 / 不能改。现在下面有一行动态说明，
  直接算出这次实际会从哪天开始拉。

### 诊断

- **结论要按「有没有源能用」下，不是「东财通不通」。** doctor 以前东财不通就报
  「A股数据无法下载」，但用户机器上 Yahoo 是通的，结论是错的。现在
  `Report.a_share_ok` / `usable_sources` 汇总所有源，并直接告诉用户该选哪个。

---

## 七、诊断工具

出问题先跑这些，别猜：

```bash
python -m scripts.doctor          # 环境全面自检（GUI: 系统设置 → 🩺 环境诊断）
python -m scripts.test_em SZ.159338      # 东财各周期能否拉取
python -m scripts.test_1m_depth SZ.159338  # 各源 1 分钟线实际历史深度
python -m scripts.diagnose               # Futu API 权限诊断
```

---

## 八、A500 ETF 标的

代码在 `gui/panels/a500_center.py:A500_ETFS`，11 只。主力是：

- `SZ.159338` 中证A500ETF（国泰，规模最大）
- `SH.512050` A500ETF（华夏）

---

## 九、约定

- **提交信息用英文**，代码注释和 UI 文案用中文
- **不要把 `.db` 提交进 git** —— 用 Parquet 备份（`data/backup/` 已在 gitignore 白名单里）
- `config/local.yaml` 存账号密码，已 gitignore，不要提交
- 改完跑一遍 `python -m scripts.doctor` 确认没弄坏环境

---

## 十、当前未解决的问题

1. **东财在用户机器上不可达**（ProxyError）。已用 Yahoo 绕过，
   但东财的分钟线历史更长，如果用户改了代理规则可以切回去 ——
   现在下载面板的「数据源」下拉可以直接切，不用改代码。
2. **1 分钟线历史都很短**，免费源普遍如此。要长历史只能付费或自己积累。
3. **用户 Futu 账号无 A 股权限**，A 股永远走不了 Futu 这条路，除非他去买行情权限。
