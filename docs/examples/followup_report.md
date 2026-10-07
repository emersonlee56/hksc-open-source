# HKSC 每日行动计划 | 2025-07-08

模式：合成数据回放；仅用于研究，全部进入与退出均为模拟。

规则版本：`hkm1_public_research_v0.1`；下一交易日：2025-07-09。

续接 2025-07-07；前序绑定 9c0d6ba571d6cc75db4e27e586b84a781032898260c087405316a46b02f77cff。
研究池版本：core_tradable_universe_v0.1-provisional；成员绑定：257a10987b0267a80a5d8983477215b0d5d1ce7bcbd6fc4ed4f7319356b39e88。

扫描覆盖 140/140；扫描数据缺口 0。

合格扫描结果 0；新增候选 0；开放候选 2；已有候选数据缺口 0。

## 今日关注

| 标的 | 变化 | 研究动作 | 下一观察日 | 追价上限 | 止损 | 目标 |
| --- | --- | --- | --- | ---: | ---: | ---: |
| DEMO.00005 | UPDATED | 复核新增终止事件 | -- | 37.2221 | 36.0691 | 39.1436 |
| DEMO.00004 | UNCHANGED | 继续跟踪 | -- | 35.0535 | 33.9679 | 36.8629 |
| DEMO.00003 | UNCHANGED | 继续跟踪 | -- | 32.9387 | 31.9187 | 34.6387 |

## 候选变化与依据

- DEMO.00005：HOLDING_RESEARCH_STATE → TARGET_HIT；TARGET
- 入选依据：{'absolute_momentum': 'PASS', 'breakout': 'PASS', 'liquidity': 'PASS', 'relative_momentum': 'PASS', 'trend': 'PASS', 'volume_confirmation': 'PASS'}；信号分数 0.2817959401。
- 初始止损条件：max(lowest_low_t_minus_9_to_t, open_next - 2*ATR14_t)；目标条件：open_next + 3*(open_next-initial_stop)。
- 新记录事件：2025-07-08 / SIMULATED_EXIT / TARGET。
- DEMO.00004：HOLDING_RESEARCH_STATE → HOLDING_RESEARCH_STATE；继续跟踪已记录的止损、目标及趋势退出条件。
- 入选依据：{'absolute_momentum': 'PASS', 'breakout': 'PASS', 'liquidity': 'PASS', 'relative_momentum': 'PASS', 'trend': 'PASS', 'volume_confirmation': 'PASS'}；信号分数 0.2718596667。
- 初始止损条件：max(lowest_low_t_minus_9_to_t, open_next - 2*ATR14_t)；目标条件：open_next + 3*(open_next-initial_stop)。
- DEMO.00003：HOLDING_RESEARCH_STATE → HOLDING_RESEARCH_STATE；继续跟踪已记录的止损、目标及趋势退出条件。
- 入选依据：{'absolute_momentum': 'PASS', 'breakout': 'PASS', 'liquidity': 'PASS', 'relative_momentum': 'PASS', 'trend': 'PASS', 'volume_confirmation': 'PASS'}；信号分数 0.2616814802。
- 初始止损条件：max(lowest_low_t_minus_9_to_t, open_next - 2*ATR14_t)；目标条件：open_next + 3*(open_next-initial_stop)。

## 数据缺口与降级

本次没有扫描覆盖缺口或可选模块降级；候选缺口见今日关注。

## 公司与事件背景

- DEMO.00005：合成背景示例：此记录不对应真实公告或公司，且不参与 HK-M1 扫描。；发布时间 2025-07-08T15:30:00+08:00；引用 fictional fact generated independently of all suppliers。

## 数据来源

- bars: synthetic / hksc.demo.generate；来源时间 2025-07-08T16:10:00+08:00；获取时间 2025-07-08T16:11:00+08:00。
- benchmark: synthetic / hksc.demo.generate；来源时间 2025-07-08T16:10:00+08:00；获取时间 2025-07-08T16:11:00+08:00。

## 人工复核

- 背景资料不参与 HK-M1 准入规则。
- 模拟事件来自完成日线回放，不代表当时已经取得前向证据。
- 研究动作不是账户指令，交易与投资判断由使用者自行承担。
