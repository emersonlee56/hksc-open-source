# HKSC 每日行动计划 | 2025-07-02

模式：合成数据回放；仅用于研究，全部进入与退出均为模拟。

规则版本：`hkm1_public_research_v0.1`；下一交易日：2025-07-03。

起始研究。
研究池版本：core_tradable_universe_v0.1-provisional；成员绑定：257a10987b0267a80a5d8983477215b0d5d1ce7bcbd6fc4ed4f7319356b39e88。

扫描覆盖 140/140；扫描数据缺口 0。

合格扫描结果 5；新增候选 3；开放候选 3；已有候选数据缺口 0。

## 今日关注

| 标的 | 变化 | 研究动作 | 下一观察日 | 追价上限 | 止损 | 目标 |
| --- | --- | --- | --- | ---: | ---: | ---: |
| DEMO.00005 | NEW | 等待进入条件 | 2025-07-03 | 37.2221 | -- | -- |
| DEMO.00004 | NEW | 等待进入条件 | 2025-07-03 | 35.0535 | -- | -- |
| DEMO.00003 | NEW | 等待进入条件 | 2025-07-03 | 32.9387 | -- | -- |

## 候选变化与依据

- DEMO.00005：首次记录 → ACTIONABLE_SETUP_TRIGGERED；等待指定交易日开盘，核对追价与止损条件。
- 入选依据：{'liquidity': 'PASS', 'absolute_momentum': 'PASS', 'relative_momentum': 'PASS', 'trend': 'PASS', 'breakout': 'PASS', 'volume_confirmation': 'PASS'}；信号分数 0.2817959401。
- 初始止损条件：max(lowest_low_t_minus_9_to_t, open_next - 2*ATR14_t)；目标条件：open_next + 3*(open_next-initial_stop)。
- DEMO.00004：首次记录 → ACTIONABLE_SETUP_TRIGGERED；等待指定交易日开盘，核对追价与止损条件。
- 入选依据：{'liquidity': 'PASS', 'absolute_momentum': 'PASS', 'relative_momentum': 'PASS', 'trend': 'PASS', 'breakout': 'PASS', 'volume_confirmation': 'PASS'}；信号分数 0.2718596667。
- 初始止损条件：max(lowest_low_t_minus_9_to_t, open_next - 2*ATR14_t)；目标条件：open_next + 3*(open_next-initial_stop)。
- DEMO.00003：首次记录 → ACTIONABLE_SETUP_TRIGGERED；等待指定交易日开盘，核对追价与止损条件。
- 入选依据：{'liquidity': 'PASS', 'absolute_momentum': 'PASS', 'relative_momentum': 'PASS', 'trend': 'PASS', 'breakout': 'PASS', 'volume_confirmation': 'PASS'}；信号分数 0.2616814802。
- 初始止损条件：max(lowest_low_t_minus_9_to_t, open_next - 2*ATR14_t)；目标条件：open_next + 3*(open_next-initial_stop)。

## 数据缺口与降级

本次没有扫描覆盖缺口或可选模块降级；候选缺口见今日关注。

## 公司与事件背景

- DEMO.00005：合成背景示例：此记录不对应真实公告或公司，且不参与 HK-M1 扫描。；发布时间 2025-07-02T15:30:00+08:00；引用 fictional fact generated independently of all suppliers。

## 数据来源

- bars: synthetic / hksc.demo.generate；来源时间 2025-07-02T16:10:00+08:00；获取时间 2025-07-02T16:11:00+08:00。
- benchmark: synthetic / hksc.demo.generate；来源时间 2025-07-02T16:10:00+08:00；获取时间 2025-07-02T16:11:00+08:00。

## 人工复核

- 背景资料不参与 HK-M1 准入规则。
- 模拟事件来自完成日线回放，不代表当时已经取得前向证据。
- 研究动作不是账户指令，交易与投资判断由使用者自行承担。
