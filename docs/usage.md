# HKSC 使用指南

## 环境

需要 Python 3.10 或更新版本，研究代码没有第三方运行依赖。在项目根目录执行 `python -m hksc`，或通过 `python -m pip install -e .` 安装本地命令。

下文 `local/day-001` 等目录需按 [输入合同](input_contract.md)准备，不是仓库内置真实数据。MCP / Skills 由使用者配置，程序本身不发起网络请求或访问账户。

## 完整演示

```bash
python -m hksc demo --output outputs/demo
python -m hksc check-output --input outputs/demo
```

打开 `outputs/demo/index.html`，查看 11 个连续合成研究日、三次期间复盘和后续研究问题。第一期与最后一期不是完整自然周；覆盖只对应报告明确的起止日期。

所有股票、价格、日历、背景与评价假设都是虚构的，没有查询真实供应商。模拟事件来自完成日线回放，不代表当时已取得前向证据。

输出目录不能覆盖。再次运行使用新目录，如 `--output outputs/demo-002`。只体验两次扫描可使用 `demo --quick --output outputs/quick-demo`。

## 每日研究

```bash
python -m hksc validate-input --input local/day-001
python -m hksc daily --input local/day-001 --output outputs/day-001
python -m hksc daily --input local/day-002 --output outputs/day-002 --prior outputs/day-001
```

`daily` 先运行主线，再独立执行效果与环境观察。`--prior` 支持上一份 daily 目录或独立 run 目录。

| 产物 | 用途 |
| --- | --- |
| `index.html` | 日常入口与前序复盘问题 |
| `research/report.html` | 每日行动计划 |
| `research/daily_plan.json` | 关注清单、前后状态、扫描缺口与背景 |
| `evaluation/report.html` | 候选效果和可选组合模型 |
| `context/report.html` | 基准和研究池环境 |
| `daily_receipt.json` | 主线、旁路状态和原因 |
| `result_hashes.json` | 整个交付的递归绑定 |

研究动作包括等待进入条件、继续跟踪、等待退出开盘证据和人工复核，不是交易指令。前序之后新增的事件即使不发生在当天，也会披露。

主线失败输出 `BLOCKED`，退出码为 2，不跑旁路。旁路失败输出 `COMPLETE_WITH_DEGRADATION`，退出码为 0，有效主线保留。降级不代表该旁路已验收。

## 显式评价假设

默认只输出候选毛结果，不隐含零成本或组合资金配置。需要组合模型时提供政策：

```bash
python -m hksc daily --input local/day-001 --output outputs/day-001-model --policy local/evaluation-policy.json
```

结构参考 `config/evaluation.demo.json`。样例不是建议仓位或实际费率，详见 [评价口径](evaluation.md)。

## 期间复盘

```bash
python -m hksc weekly \
  --runs outputs/day-001 outputs/day-002 \
  --start 2025-07-02 --end 2025-07-03 \
  --evaluations outputs/day-001/evaluation outputs/day-002/evaluation \
  --contexts outputs/day-001/context outputs/day-002/context \
  --output outputs/review-001
```

日期须替换为实际研究日期。没有有效旁路时不传对应目录，报告会说明不足，不补造结果。

复盘披露缺失研究日、前序断点与日历左右端未知范围。“完整覆盖”只指请求期间和已知日历，不证明完整自然周或全市场。

下一期增加 `--prior-review outputs/review-001`，新期间必须在旧期间之后。问题保留首次提出日期，每期追加观察；缺口消失也不自动宣布问题解决。

下一轮日常研究可以读取这些问题：

```bash
python -m hksc daily --input local/day-003 --output outputs/day-003 \
  --prior outputs/day-002 --prior-review outputs/review-001
```

问题保存于独立的 `research_agenda.json`，显示在总入口，不改写策略或候选。

## 独立模块

```bash
python -m hksc run --input local/day-001 --output outputs/run-001
python -m hksc evaluate --run outputs/run-001 --input local/day-001 --output outputs/eval-001
python -m hksc context --run outputs/run-001 --input local/day-001 --output outputs/context-001
python -m hksc check-output --input outputs/run-001
```

评价和环境必须使用该 run 绑定的输入，不能换一个日期相同的数据包。

## 失败与恢复

保留失败目录，不把部分产物当作有效前序。日期、哈希、历史或安全错误不自动重试或自修复。复权历史被重述时独立复核，不能改写旧记录让流程继续。

原型 `hksc-public-run/1` 不直接续接到当前 `/2`；保留旧结果，以新目录建立公开版起点。

## 旁路写盘中断

效果或环境旁路失败时，不修补清单、不重跑主线。当前新运行中的半成品移动到 `failed_artifacts/<stage>/`，所有文件内容原样保留；不完整的 `result_hashes.json` 仅改名为 `result_hashes.json.incomplete`，避免把失败证据当作已完成子交付。`failure_evidence.json` 记录原路径、保存路径和内容哈希，Daily 回执指向证据目录。

父交付仍绑定完整文件集合和所有证据哈希，篡改失败证据仍被拒绝。已完成子交付继续严格递归校验。隔离或封装本身失败时返回 `BLOCKED`，不宣称交付完成，也不修改前序目录。

完整演示中的期间复盘同样是旁路。某期失败只记录降级、保存当前半成品证据，不重跑该期，也不停止后续研究日；下一期使用自己的新期间与最后一份有效复盘。没有有效复盘时 `last_review` 为 `null`，后续入口不虚构研究问题，索引不链接失败报告。周报证据位于 `weekly/failed_artifacts/<期间结束日期>/`。演示总状态明确为 `COMPLETE_WITH_DEGRADATION`；真实封装安全边界仍可形成 `BLOCKED`。
