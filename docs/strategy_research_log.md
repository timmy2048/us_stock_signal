# Strategy Research Log

本文档记录每轮高收益策略搜索结果。后续如果要做多策略评分、信号触发机制或按市场环境动态切换策略，优先从这里抽取候选策略。

## 记录规则

- 每轮搜索都记录：日期、策略参数、验证窗口、样本天数、信号数、单仓最终权益倍数、单仓复利收益、最大回撤、Profit Factor、是否进入默认配置。
- 默认用 `single_position_final_equity` 和 `single_position_total_return_pct` 评估“全仓复利滚动”效果。
- 40 样本结果只看爆发力；80/120 样本结果用于判断是否过拟合。
- 策略进入默认配置前，至少要和当前默认在 40/80 样本比较；如果 120 样本可承受耗时，也要补充 120 样本。
- 市场环境、AI、新闻等未来模块可以把本日志里的策略作为候选 profile，而不是只维护一套固定参数。

## 当前默认策略

状态：Accepted, active default = `aggressive_150_60`

参数：

```yaml
trigger_mode: high_yield_breakout
top_n: 2
profile_name: aggressive_150_60
candidate_pool_limit: 100
min_score: 80
min_atr_pct: 5
max_atr_pct: 999
min_momentum_20_pct: 150
min_momentum_5_pct: 60
min_volume_ratio: 2
max_gap_pct: 80
max_price: 100
take_profit_2_atr_multiple: 7.0
min_stop_pct: 0.02
max_stop_pct: 0.02
entry_buffer_pct: 0.0
pending_signal_expiry_trading_days: 1
max_tracking_trading_days: 3
```

验证摘要：

| Sample days | Signals | Final equity | Compound return | Single-position max DD | Profit Factor | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 40 | 31 | 101.2428x | 10024.28% | 7.06% | 19.8572 | 当前执行 profile，40 样本爆发力最强 |
| 80 | 64 | 15.9276x | 1492.76% | 30.59% | 5.428 | 收益仍高，但回撤明显高于 balanced_120_80 |
| 120 | 96 | 10.0230x | 902.30% | 36.95% | 4.1002 | 保留高收益取向，接受更大波动 |

采用原因：

- 用户当前明确优先追求高收益，接受更大波动和回撤。
- `150/60` 在 40 样本上单仓复利最高，且最大回撤最低。
- `balanced_120_80` 继续保留为后续市场环境切换或 profile 评分候选。

风险：

- 胜率仍低，主要靠少数 TP2 大盈利覆盖大量 2% 止损。
- Rank 2 在 80 样本中单独表现较差，但 120 样本中 Top2 对单仓滚动收益更好；后续可继续研究 rank-aware allocation 或只在 Rank2 额外通过确认条件时触发。

## 研究轮次

### R-001: 固定 2% 止损

状态：Accepted, later combined into current default

参数变化：

- `min_stop_pct: 0.03 -> 0.02`
- `max_stop_pct: 0.04 -> 0.02`

验证窗口：365 days, sample-days 40

| Strategy | Signals | Final equity | Compound return | Single-position max DD | Profit Factor |
| --- | ---: | ---: | ---: | ---: | ---: |
| Previous 4% max stop | 38 | 75.3436x | 7434.36% | 19.84% | 8.9917 |
| Fixed 2% stop | 38 | 94.6160x | 9361.60% | 11.18% | 16.537 |

结论：

- 固定 2% 止损显著提高 40 样本复利，并降低回撤。
- 继续保留为默认策略的一部分。

### R-002: 价格行为过滤

状态：Accepted, later combined into current default

新增过滤：

- `max_gap_pct: 80`
- `max_price: 100`

验证窗口：365 days

| Sample days | Strategy | Signals | Final equity | Compound return | Single-position max DD | Profit Factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 40 | No price-action filter | 38 | 94.6160x | 9361.60% | 11.18% | 16.537 |
| 40 | `gap<=80`, `price<=100` | 31 | 101.2428x | 10024.28% | 7.06% | 19.8572 |
| 80 | `gap<=80`, `price<=100`, old momentum `150/60` | 64 | 15.9276x | 1492.76% | 30.59% | 5.428 |
| 120 | `gap<=80`, `price<=100`, old momentum `150/60` | 96 | 10.0230x | 902.30% | 36.95% | 4.1002 |

结论：

- 极端跳空和高价/疑似反向拆股异常标的会贡献较多止损和噪声。
- 价格行为过滤提升 40 样本复利和回撤表现，但扩大样本后仍需要重新调动量阈值。

### R-003: 80/120 样本动量重调

状态：Accepted, retained as `balanced_120_80` profile

参数变化：

- `min_momentum_20_pct: 150 -> 120`
- `min_momentum_5_pct: 60 -> 80`
- 保持 `top_n=2`, `TP2=7ATR`, fixed 2% stop, `gap<=80`, `price<=100`

| Sample days | Strategy | Signals | Final equity | Compound return | Single-position max DD | Profit Factor |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 40 | Old `150/60` | 31 | 101.2428x | 10024.28% | 7.06% | 19.8572 |
| 40 | New `120/80` | 35 | 60.4518x | 5945.18% | 7.06% | 16.919 |
| 80 | Old `150/60` | 64 | 15.9276x | 1492.76% | 30.59% | 5.428 |
| 80 | New `120/80` | 74 | 22.7405x | 2174.05% | 21.08% | 5.0948 |
| 120 | Old `150/60` | 96 | 10.0230x | 902.30% | 36.95% | 4.1002 |
| 120 | New `120/80` | 113 | 12.9283x | 1192.83% | 25.41% | 4.3021 |

结论：

- 旧 `150/60` 在 40 样本上更爆，但扩大样本后回撤和稳定性变差。
- 新 `120/80` 在 80/120 样本上更强，信号也更多，保留为更均衡的候选 profile。
- 2026-06-01 根据用户偏好切回 `aggressive_150_60` 作为当前执行触发条件。

### R-004: 市场宽度/市场动量过滤

状态：Rejected for default, keep as watchlist candidate

离线特征：

- `breadth_above_ma20_pct`: 高流动性前 500 只股票中，收盘价在 20 日均线上的比例。
- `median_ret5_pct`: 高流动性前 500 只股票 5 日收益中位数。
- `median_ret20_pct`: 高流动性前 500 只股票 20 日收益中位数。
- `positive_ret5_pct`, `positive_ret20_pct`: 5/20 日收益为正的比例。

验证窗口：365 days, sample-days 120, base strategy = `balanced_120_80` at time of search

| Filter | Signals | Final equity | Compound return | Single-position max DD | Profit Factor | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| None | 113 | 12.9283x | 1192.83% | 25.41% | 4.3021 | Current default |
| `median_ret20_pct >= -5` | 110 | 13.2288x | 1222.88% | 25.41% | 4.4348 | Watchlist only |
| `breadth >= 30` | 108 | 7.5460x | 654.60% | 25.41% | 3.9203 | Reject |
| `median_ret20_pct >= 0` | 95 | 6.8026x | 580.26% | 33.46% | 3.4415 | Reject |

结论：

- 大部分市场宽度过滤会减少大赢家，复利下降。
- `median_ret20_pct >= -5` 有小幅改善，但提升太小，不值得增加默认配置复杂度。
- 后续如果做多策略评分，可以把 `median_ret20_pct >= -5` 作为轻量加分项，而不是硬过滤。

## 后续候选方向

1. Rank-aware 触发：Rank 2 当前频次有价值，但独立表现弱，后续可要求 Rank 2 满足更高分数、更低跳空、更低上影线或更高 5 日动量。
2. 多 profile 评分：保留 `aggressive_150_60`、`balanced_120_80`、`Top1-only`、`median_ret20>=-5` 作为候选 profile，由验证分数决定当日使用哪个 profile。
3. 分市场阶段调参：不要用简单宽度硬过滤；可以用市场阶段作为评分权重，比如弱市场减少 Rank2 权重，强市场提高候选池。
4. 新闻/AI 事件层：当前 AI 多数未参与，有新闻后可把重大正面催化作为突破候选的额外确认，不覆盖硬过滤。
