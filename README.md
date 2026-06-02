# US Stock Signal

Strategy research log: [docs/strategy_research_log.md](docs/strategy_research_log.md). 每轮高收益策略搜索、验证指标、采纳/拒绝原因都应记录到这里，方便后续做多 profile 评分和信号触发机制。

Current tuned default: `entry_buffer_pct=0.0`. The 365-day strategy search selected this over the previous `0.002` trigger buffer because it improved single-position compound return.

Current tuned default: `pending_signal_expiry_trading_days=1`. The high-yield search favored a faster one-day entry window for higher single-position compound return and lower tested drawdown.

Current tuned default: `take_profit_2_atr_multiple=7.0`. The focused high-yield search improved single-position compound return versus the previous `6.0` TP2 target without increasing tested single-position drawdown.

Current active signal profile: `aggressive_150_60` with `top_n=2`, `min_momentum_20_pct=150`, and `min_momentum_5_pct=60`. The `balanced_120_80` profile is retained in the strategy log for later comparison, but the active trigger is the higher-return 40-sample profile.

Retained comparison profile: `balanced_120_80`. It performed better on expanded 80/120 samples, but is not the current active trigger profile.

Current tuned default: `min_stop_pct=0.02` and `max_stop_pct=0.02`. The stop-width sweep favored a fixed 2% stop, improving tested compound return and reducing single-position drawdown versus the previous 4% cap.

Current tuned default: `max_gap_pct=80` and `max_price=100`. The price-action sweep favored excluding extreme signal-day gaps and high-price/reverse-split-like outliers, improving tested compound return and reducing single-position drawdown.

美股短线多头推荐与跟踪提醒系统。当前只做研究提醒，不自动交易，不接 IBKR 持仓，不管理真实仓位。

## 当前策略

默认启用更激进的高收益模式：

- 触发模式：`high_yield_breakout`
- 扫描范围：不传 `--max-symbols` 时，从 DuckDB 已入库的全市场日线构造快照
- 入选门槛：综合分 `>= 80`
- 候选池：先看综合分前 `100`
- 二次过滤：`ATR >= 5%`、`20 日动量 >= 150%`、`5 日动量 >= 60%`、`成交量比 >= 2x`、`跳空 <= 80%`、`价格 <= 100`
- 最多推送：Top2，按单仓全仓复利搜索结果选择更高收益组合，不再为了凑 Top10 强行补低质量信号
- 主要验证目标：TP2，当前为 `7ATR`
- 最大持有/跟踪期：`3` 个交易日，目标是更快释放资金，提高全仓复利滚动频次
- 风险特征：信号更多、更激进、回撤可能很大；适合 shadow tracking 后再决定是否实盘采用

## 功能

- 同步 Nasdaq Trader 股票池到 DuckDB
- 同步 Yahoo Chart / yfinance 免费日线数据到 DuckDB
- 从本地数据库全市场扫描，不依赖每次实时逐票拉取
- 生成入场区间、止损价、TP1、TP2、失效价和风险提示
- DeepSeek 可参与新闻/事件评分；没有 key 或请求失败时自动降级为中性 AI 分
- 钉钉 Markdown 中文推送，`scan --notify` 扫描完成后会自动发送
- 跟踪推荐生命周期：入场、止盈、止损、失效、超期
- 历史评分验证：只使用信号日前历史数据打分，再用后续最多 10 个交易日验证结果

## 快速开始

```powershell
cd D:\Trading\us_stock_signal
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
copy .env.example .env
```

`.env` 需要配置：

```text
DINGTALK_WEBHOOK=你的钉钉机器人 webhook
DINGTALK_SECRET=可选，机器人加签 secret
DEEPSEEK_API_KEY=你的 DeepSeek API key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

## 常用命令

```powershell
python -m us_stock_signal sync-universe
python -m us_stock_signal sync-daily --period 1y
python -m us_stock_signal sync-all --period 1y
python -m us_stock_signal market-status
python -m us_stock_signal scan --session premarket --notify
python -m us_stock_signal scan --session regular --notify
python -m us_stock_signal scan --session afterhours --notify
python -m us_stock_signal notify --latest
python -m us_stock_signal track
python -m us_stock_signal validate-scoring --lookback-days 365 --sample-days 40
python -m us_stock_signal strategy-search --lookback-days 365 --sample-days 40 --min-signals 30 --objective compound
python -m pytest
```

说明：

- `scan --notify` 会在扫描完成后自动发送钉钉，不需要再手动跑 `notify --latest`。
- `notify --latest` 只会把最近一次扫描结果重新推送一次。
- `--max-symbols 30` 只适合本地连通性测试；正式扫描不要传，让系统从数据库全市场筛选。
- `sync-universe` 会同步全市场股票池。
- `sync-daily` 会把股票池中的历史日线增量写入 DuckDB，重复 `symbol/date` 会更新，不会重复插入。
- `sync-all` 会先同步股票池，再同步日线；第一次全量同步会比较慢。
- `sync-daily`、`sync-all`、`prepare-market` 默认启用美东时间保护：只允许在 `20:30 ET` 后或 `08:00-09:20 ET` 盘前重试窗口同步日线，避免美股未收盘或免费源未稳定时写入当天不完整日线。
- `--force` 只用于手动修复或补历史数据；VPS 定时任务不要常态使用。
- 日线同步按 `--batch-size` 分批执行；默认配置还会在批次之间暂停 `1` 秒。单批 provider 失败会尝试 fallback，fallback 也失败时跳过该批并继续后续批次。
- `market-status` 用于检查本地数据库覆盖率和最新日线日期。
- `strategy-search` 会批量搜索高收益参数组合，默认按“单仓全仓复利收益”排序，搜索范围包含分数门槛、动量/成交量过滤、TP2、止损 ATR 倍数和最大止损比例，结果写入 `data/strategy_search_report.json`。

## 正式工作流

首次或需要刷新全量数据时：

```powershell
python -m us_stock_signal sync-all --period 1y --force
python -m us_stock_signal market-status
```

日常运行：

```powershell
python -m us_stock_signal scan --session premarket --notify
python -m us_stock_signal scan --session regular --notify
python -m us_stock_signal track
```

VPS 上建议：

- 美股盘前跑一次 `prepare-market --session premarket --notify`
- 盘中每 15 分钟跑一次 `scan --notify`
- 每天至少同步一次股票池和日线，保持数据库更新
- 日线同步按美东时间卡点，不按北京时间“今天”判断：收盘后 `20:30 ET` 全量同步 1 年数据，次日 `08:15 ET` 只重试最近 `5d`，同步完成后扫描推送，目标是在 `09:30 ET` 正式开盘前约 1 小时收到钉钉。`08:15 ET` 是正式开盘前，不是 04:00 ET 盘前交易开始前。

## 数据源限制

免费数据源可能有延迟、缺失、限速和接口变化。真实资金使用前建议至少跑一段 shadow tracking，并考虑后续替换为 Polygon、Tiingo、Finnhub、Alpha Vantage 或券商级行情源。

## 免责声明

本项目输出研究提醒，不构成投资建议，不保证收益或准确率。系统不会自动交易，也不会替你执行止损或止盈。
