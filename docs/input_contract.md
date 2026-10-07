# 规范化输入包 v1

输入目录至少包含以下文件。可以先运行离线演示查看机器生成的完整样例。

| 文件 | 内容 |
|---|---|
| bundle.json | 格式版本、as_of_date、synthetic 和所有输入文件的 SHA-256 |
| universe.csv | 140 个示例池成员的类型、币种、状态和流动性筛选字段 |
| universe.json | 已排序成员、成员哈希、源 CSV 哈希和筛选阈值 |
| bars.csv | 股票日线，symbol/date/open/high/low/close/amount/volume |
| benchmark.csv | 单一 HK.800000 基准日线，同上字段 |
| calendar.json | 已排序且唯一的交易日、最新完成日、下一交易日与证据 |
| sources.json | 股票与基准的来源记录、复权声明 |

CSV 日期采用 `YYYY-MM-DD`，价格和成交额为 HKD，成交量为股数。股票 OHLC 必须明确为前复权。合成数据中的 qfq 标记只模拟接口口径，不表示经过真实公司行动复权。

```json
{
  "format": "hksc-public-bundle/1",
  "as_of_date": "2025-07-02",
  "synthetic": false,
  "files": {
    "bars.csv": "<sha256>",
    "benchmark.csv": "<sha256>",
    "universe.csv": "<sha256>",
    "universe.json": "<sha256>",
    "calendar.json": "<sha256>",
    "sources.json": "<sha256>",
    "raw/bars.json": "<sha256>",
    "raw/benchmark.json": "<sha256>",
    "raw/calendar.json": "<sha256>"
  }
}
```

`sources.json` 的 `bars` 和 `benchmark` 各自包含 `provider`、`access_tool`、`data_as_of`、带时区的 `source_timestamp` / `retrieved_at`、`currency`、`amount_unit`、`volume_unit`、`adjustment` 和 `evidence_reference`。真实来源还必须包含 `raw_evidence_file`，指向清单内已哈希的原始响应文件。允许的 provider 为 `westock`、`futu`、`gildata`；`synthetic` 只用于演示。

为了兼容抽取的扫描核心，还需要：

```json
{
  "stock_provenance_assessment": {"adjustment": "qfq"}
}
```

真实 `calendar.json` 使用 `synthetic=false`，包含 `calendar_evidence_file`，指向清单内的交易日依据。不得用合成工作日表代替真实港交所日历。

可选 `gildata_facts.json` 是事实数组，每项包含 `provider=gildata`、`published_at`、`retrieved_at` 和 `evidence_reference`，并可包含 `symbol`、`category`、`statement` 等说明。该文件必须纳入输入哈希。事实不参与扫描规则，模型解读不能补造缺失数字。

公开版固定 140 个池成员、至少 126 个覆盖、每个至少 120 根有效日线。该规模来自抽取的 HK-M1 示例，不是全市场覆盖承诺。使用者自行提供池成员，不附原项目真实池。池内筛选列见演示 `universe.csv`；成员选择需要独立评估幸存者偏差。

校验只证明文件与声明一致，不能证明提供者身份、原始响应真实性或数据授权。真实输入运行始终标为 `RESEARCH_ONLY` 并要求人工复核。

## 续接

`--prior` 只接受公开版输出，要求旧产物哈希一致、日期递增、池成员一致、已完成日历保持前缀不变、已有行情历史逐值一致。旧事件只能追加；已终止候选仍保留。遇到复权重述、日期错误或哈希错误直接阻断。

输出目录必须全新。发生写盘中断时保留目录作为失败证据，使用新目录重做，不能用部分目录继续冒充完成。
