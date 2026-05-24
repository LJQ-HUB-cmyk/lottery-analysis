# CLAUDE.md — 彩票分析项目指令

## 项目概述

排列三 + 福彩3D + 快乐8 彩票数据分析与评分预测系统。核心思路：基于多窗口统计 + 理论分布 + 动态评分引擎，对候选号码打分排序，输出 Top-K 候选。

> 彩票开奖完全随机，本项目仅供学习研究。所有分析仅基于历史统计，不代表未来结果。

## Hermes cron 定时任务

项目通过 Hermes 定时执行，不依赖 GitHub Actions。所有推送类任务均为 **no_agent 模式**，绕过 Tirith 安全审批链，不消耗 API token。

> 详细配置见 [docs/HERMES_CONFIG.md](docs/HERMES_CONFIG.md)

### 下午预测链路（14:40 / 14:50）

| 时间 | 命令 | 说明 | 模式 |
|------|------|------|:----:|
| 14:40 | `bash scripts/push/lottery_predict_push.sh` | **PLS/D3 预测**：Job → run_daily → source_health → hermes_push | no_agent |
| 14:50 | `bash scripts/push/kl8_predict_push.sh` | **KL8 预测**：Job → fetcher → predictor → stats → hermes_push | no_agent |

> 预测推送为自闭环，内部 Job 自动执行全部步骤。业务键（dedup_key）去重，不加 --force。

### 晚间复盘链路（22:05 → 22:10 → 22:15 → 22:20 单彩种独立推送）

| 时间 | 命令 | 说明 | 模式 |
|------|------|------|:----:|
| 22:05 | `bash scripts/push/lottery_review_push.sh --prepare-only` | **拉取开奖 + 应用人工修正**（不推送） | no_agent |
| 22:05 | `python scripts/kl8/check.py` | **KL8 健康检查** | agent |
| 22:10 | `bash scripts/push/lottery_review_push.sh --lottery pls --final` | **排列三复盘**：带 Top30，未齐推兜底通知 | no_agent |
| 22:15 | `bash scripts/push/lottery_review_push.sh --lottery d3 --final` | **福彩3D复盘**：带 Top30，未齐推兜底通知 | no_agent |
| 22:20 | `bash scripts/push/kl8_review_push.sh` | **KL8 复盘**：带完整候选池 | no_agent |

> 单彩种独立推送：哪个彩种数据齐了就推哪个，不再互相等待。
> 每条推送自带 `--final` 兜底（数据不齐时推送"无法复盘"通知），不再需要 23:10 独立任务。
> Hermes cron 包装脚本（`~/.hermes/scripts/lottery_review_*.sh`）通过 shell 薄入口调用 Python job，保留锁文件、日志、23点自动 final 等机制。
> 去重靠 dedup_key（业务键），按彩种拆分：`review:{date}:pls-{issue}` / `review:{date}:d3-{issue}`。
> 锁和日志文件均按彩种隔离。

> 快乐8每期开20个号码(1-80)。策略：热号12+冷号8混合生成20码池 + 选四主推。复盘计算命中数/奖金/盈亏。累计表现自动追踪近N期。
>
> **推送脚本维护说明：** Hermes no_agent cron 使用的包装脚本在 `~/.hermes/scripts/` 下（如 `lottery_review_pls.sh`），它们通过 `scripts/push/` 下的 shell 薄入口调用 Python job。修改 `scripts/push/*.sh` 后需手动复制到 `~/.hermes/scripts/` 才能生效：
> ```bash
> cp scripts/push/*.sh ~/.hermes/scripts/
> ```
> Hermes no_agent 模式要求脚本文件必须在 `~/.hermes/scripts/` 目录内（不支持软链接指向外部）。

## 项目结构

```
lottery-analysis/
├── run_daily.py              # 一键每日运行入口
├── scripts/
│   ├── data_fetcher.py       # 多源数据抓取（js-lottery/eastmoney主源 + sporttery/zhcw备用 + 熔断 + 校验）
│   ├── feature_engine.py     # 特征工程（113维）+ 数据质量检查
│   ├── stats_engine.py       # 多窗口统计 + 理论分布
│   ├── scoring_engine.py     # 评分引擎v2（YAML权重 + 回归惩罚 + 多样性）
│   ├── backtest.py           # Walk-forward 回测（三策略对比 + ROI拆分）
│   ├── compare_result.py     # 预测 vs 开奖对比 + review_history累加
│   ├── review_summary.py     # 最近N期复盘表现摘要
│   ├── daily_review.py       # 每日复盘一键脚本（Hermes cron调用）
│   ├── tune_weights.py       # 权重自动调优（随机搜索 + Optuna贝叶斯优化 + 稳定性分析）
│   ├── filter_engine.py      # 轻量预过滤（已降级）
│   ├── visualize.py          # 走势图/热力图（matplotlib + plotly）
│   ├── issue_utils.py         # 期号标准化（PLS/D3格式互转）
│   ├── source_health.py       # 数据源健康报告
│   ├── hermes_push.py         # 两段式推送（支持 --lottery pls/d3/kl8）
│   ├── kl8/                    # 快乐8独立模块
│   │   ├── fetcher.py          # 官方API抓取 + 校验 + --check
│   │   ├── predictor.py        # 20码池 + 选四主推
│   │   ├── reviewer.py         # 选四命中/盈亏/期号精确匹配
│   │   ├── check.py            # 全链路5项健康检查
│   │   ├── metrics.py          # 近N期累计成本/奖金/盈亏
│   │   ├── stats.py            # 奇偶/大小/连号/和值/冷热统计
│   │   └── strategy.py         # 4策略统一接口（暂不启用）
│   ├── jobs/                    # Python job 业务编排（Shell 薄入口调用）
│   │   ├── lottery_predict_job.py   # PLS/D3 预测编排
│   │   ├── lottery_review_job.py    # PLS/D3 复盘编排（--stage normal/final）
│   │   ├── kl8_predict_job.py       # KL8 预测编排
│   │   └── kl8_review_job.py        # KL8 复盘编排（删旧文件+时间戳+期号校验）
│   ├── lib/                     # 共享库
│   │   └── job_status.py            # 统一状态文件读写（5种状态枚举）
│   └── push/                   # Hermes cron no_agent 推送脚本（薄入口）
│       ├── lottery_predict_push.sh  # 预测推送（→ lottery_predict_job.py）
│       ├── lottery_review_push.sh   # 复盘推送（→ lottery_review_job.py）
│       ├── kl8_predict_push.sh      # KL8预测推送（→ kl8_predict_job.py）
│       ├── kl8_review_push.sh       # KL8复盘推送（→ kl8_review_job.py）
├── rules/
│   ├── scoring_weights.yaml              # 默认权重
│   ├── scoring_weights_conservative.yaml # 稳健策略
│   ├── scoring_weights_diversity.yaml    # 多样性策略
│   └── data_sources.yaml                 # 数据源配置
├── data/
│   ├── raw/         # 原始CSV（git忽略）
│   ├── processed/   # 特征工程输出（git忽略）
│   ├── archived/    # 种子数据（git追踪）
│   ├── cache/       # 统计缓存 + 熔断状态（git忽略）
│   ├── kl8/         # 快乐8历史数据 + latest JSON
│   └── quarantine/  # 坏数据隔离区（git忽略）
└── output/
    ├── predictions/ # 预测JSON
    ├── reviews/     # 复盘CSV
    ├── backtests/   # 回测报告
    ├── reports/     # 数据检查报告 + 健康报告
    ├── charts/      # 可视化图表
    ├── kl8/         # 快乐8预测+复盘输出
    ├── push/        # 推送日报 + 发送日志 + pending补发
    ├── status/      # 任务状态JSON（git忽略，运行时产物）
    └── tuning/      # 调参记录
```

## 核心脚本与常用命令

### 每日一键运行

```bash
python run_daily.py                              # 跑两个彩种，默认策略Top-30
python run_daily.py pls --top-k 10               # 只跑排列三，10注
python run_daily.py --strategy conservative       # 稳健策略
python run_daily.py --strategy all                # 三套策略全跑
```

### 每日复盘

```bash
python scripts/daily_review.py                    # 一键复盘（拉取→对比→摘要）
python scripts/daily_review.py --lottery pls      # 仅排列三
```

### 特征工程

```bash
python scripts/feature_engine.py --input data/raw/pls_raw.csv --output data/processed/pls_feat.csv --lottery pls --force
```

### 评分预测

```bash
python scripts/scoring_engine.py --lottery pls --top-k 30
python scripts/scoring_engine.py --lottery pls --weights rules/scoring_weights_conservative.yaml --output-name conservative
```

### 回测

```bash
python scripts/backtest.py --lottery pls --periods 100 --top-k 30
```

### 预测 vs 开奖对比

```bash
python scripts/compare_result.py --lottery pls
python scripts/compare_result.py --lottery pls --strategy conservative
```

### 复盘摘要

```bash
python scripts/review_summary.py
python scripts/review_summary.py --window 60 --lottery pls
```

### 数据源健康 & 推送

```bash
python scripts/source_health.py                          # 终端健康报告
python scripts/source_health.py --json                   # JSON 格式
python scripts/source_health.py --json --output output/reports/source_health.json  # 写文件
python scripts/data_fetcher.py --cb-status               # 熔断器状态
python scripts/hermes_push.py --mode predict             # 推送预测
python scripts/hermes_push.py --mode review              # 推送复盘
python scripts/hermes_push.py --mode predict --force     # 强制补发预测
python scripts/hermes_push.py --mode review --force      # 强制补发复盘
python scripts/hermes_push.py --mode predict --write-only  # 只生成不推送
python scripts/hermes_push.py --mode daily               # 旧版混合日报（兼容）
```

### Job 架构（Shell 薄入口 → Python 业务编排）

```bash
# 晚间复盘（单彩种独立推送）
python scripts/jobs/lottery_review_job.py --prepare-only                    # 只拉数据不推送
python scripts/jobs/lottery_review_job.py --lottery pls --final             # 排列三复盘（带Top30）
python scripts/jobs/lottery_review_job.py --lottery d3 --final              # 福彩3D复盘（带Top30）

# KL8 复盘（含删旧文件+时间戳+期号三重校验）
python scripts/jobs/kl8_review_job.py

# 预测
python scripts/jobs/lottery_predict_job.py    # PLS/D3 预测
python scripts/jobs/kl8_predict_job.py        # KL8 预测
```

> Job 负责全部业务判断（开奖齐全/期号校验/去重/状态写入），Shell 只做 cd/加锁/启动/日志。
> 每个 Job 写入 `output/status/*.json`，状态枚举：ready/pushed/skipped_waiting/skipped_already_sent/error。
> 退出码：0=正常（含等待开奖），2=业务异常，3=环境异常。

### 快乐8

```bash
# 数据 + 预测
python scripts/kl8/fetcher.py --pages 3            # 拉取历史开奖
python scripts/kl8/predictor.py                    # 生成20码池+选四主推
python scripts/kl8/stats.py                        # 统计指标（奇偶/大小/连号）

# 复盘
python scripts/kl8/reviewer.py                     # 选四命中+盈亏复盘
python scripts/kl8/metrics.py                      # 更新累计表现

# 健康检查
python scripts/kl8/check.py                        # 全链路5项检查

# 推送
python scripts/hermes_push.py --mode predict --lottery kl8   # 推送预测
python scripts/hermes_push.py --mode review --lottery kl8    # 推送复盘（含累计表现）

# 多策略（暂不启用，供回测用）
python -c "from scripts.kl8.strategy import list_strategies; print(list_strategies())"
```

### 期号工具

```bash
python scripts/issue_utils.py                            # 自测
```

### 权重调优（需 review_history ≥ 15 期）

```bash
python scripts/tune_weights.py --lottery pls --trials 30 --periods 50
python scripts/tune_weights.py --lottery pls --method optuna --trials 30
```

### 可视化

```bash
python scripts/visualize.py --lottery pls --chart all
python scripts/visualize.py --lottery pls --chart trend --output-format html
```

## 数据流

```
data_fetcher.py → data/raw/*.csv
    ↓
feature_engine.py → data/processed/*.csv（113维特征）
    ↓
stats_engine.py → data/cache/*_stats_latest.json
    ↓
scoring_engine.py → output/predictions/latest_*.json
    ↓
compare_result.py → output/reports/*_compare_latest.json + output/reviews/review_history.csv
    ↓
review_summary.py → 终端表现摘要
```

### Job 编排层

```
scripts/push/*.sh（薄入口：cd/加锁/日志）
    ↓
scripts/jobs/*.py（业务编排：拉取→判断→复盘→去重→推送）
    ↓
scripts/hermes_push.py（推送内容生成 + dedup_key去重 + 发送）
    ↓
output/status/*.json（任务状态记录）
```

## 关键设计决策

1. **不硬过滤**：1000 注全部打分排序，不做硬规则排除（豹子除外）
2. **理论+近期混合**：每条规则 = 理论分布×60% + 近期走势×40%
3. **YAML 权重可配置**：改策略不改代码
4. **回归惩罚**：形态评分双向惩罚偏离理论值（过热降分、过冷加分）
5. **多样性惩罚**：同组选只保留最高分直选 + 跨度多样性促进
6. **遗漏评分上限截断**：`miss_score = max(0, min(miss_score, W['遗漏']))`，防止三热号场景遗漏分超过配置权重2倍（14/7）
7. **期号不匹配分类处理**：`pred>actual` 标记 `waiting_actual`(exit 0)，写 `*_waiting.json` 不覆盖 latest；`pred<actual` 视为真错误(exit 1)
8. **复盘命中按范围分层**：review_history 记录 `命中范围(Top5/Top10/Top30)` + `命中号码` + `命中排名` + `Top5直选/组选`，hermes_push 复盘推送口径与预测一致，命中时展示具体号码和排名，Top5 标注为"参考"
9. **不做 LSTM/ML 直接预测号码**：彩票无时间依赖，ML 不优于统计方法
10. **快乐8独立模块不接入主流程**：`scripts/kl8/` 7个文件（fetcher/predictor/reviewer/check/metrics/stats/strategy），热号+冷号策略 + 选四主推 + 盈亏复盘 + 累计表现，与 PLS/D3 互不干扰。多策略框架已就绪，待 ≥30 天数据后回测评估
11. **号码始终当字符串**：防止前导零丢失（040→40）
12. **Shell 薄入口 + Python Job 编排**：Shell 只做 cd/加锁/启动/日志，不做业务判断。所有业务逻辑（开奖齐全、期号校验、是否推送）在 Python job 层
13. **业务键去重（dedup_key）**：`review:date:pls-issue:d3-issue` / `kl8_review:issue` / `predict:date:pls-issue:d3-issue`，同一期号同日不重复推送，不受文本微小变化影响
14. **统一退出码**：0=正常（含等待开奖/已推送跳过），2=业务异常（阻断推送），3=环境异常（venv缺失）
15. **状态可追踪**：每个 Job 写 `output/status/*.json`，含 status/dedup_key/issues/reason，排查不再靠 grep 日志猜测
16. **KL8 复盘三重防旧数据**：删旧文件 → 时间戳校验 → 期号匹配预测期号，防止旧文件被误推

## 未解决问题

> 以下为已知但暂不致命的问题。解决后打 ✅。

- [ ] **js-lottery 排列三主源持续 fallback** — fallback 路径仅解析 10 条，影响历史数据完整性。建议采集失败响应样本到 `logs/source_samples/`
- [ ] **21:35/22:05 推送记录缺失无法回溯** — send_log.jsonl 不会回溯写入历史记录，仅从 2026-05-20 23:31 修复后开始记录 len+preview
- [ ] **push_state.json 不存在** — `--stdout + deliver=origin` 模式不创建 push_state.json（预期行为），该模式去重靠 send_log.jsonl + 文件锁

## 文件编码

所有 CSV/JSON/YAML 统一使用 UTF-8-sig（Windows 兼容）。Python open() 必须显式指定 encoding='utf-8' 或 'utf-8-sig'。

## KL8 后续计划

> 以下为 GPT 审查建议中确认有价值但暂不执行的项目。完成后打 ✅。

### P1：近期可做

- [ ] `scripts/kl8/backtest.py` 回测脚本 — 等 review_history ≥ 30 条后建，对比 4 策略表现
- [ ] `scripts/kl8/rules.py` 统一奖级表 — 选一~选十标准奖金，替代 reviewer 硬编码
- [ ] predictor 分区均衡约束 — `--zone-balance` 参数，避免候选池过度集中
- [ ] metrics 命中率加权 — 中四 > 中三 > 中二分值不同

### P2：数据积累后做

- [ ] 多策略对比报告 — v0随机/v1热冷/v2分区/v3遗漏，30天后跑一次完整对比
- [ ] stats.py 全量遗漏表 — 当前只有 top10
- [ ] check.py `--stage` 参数 — 区分 predict/review/full 检查场景
- [ ] 推送模板加奇偶/大小/连号展示 — stats 已有数据，模板可扩展

### 暂不做

- [ ] 深度学习/Transformer 模型（彩票无时间依赖，ML 不优于统计方法）
- [ ] run_daily.py 接入 KL8（独立模块设计不改）
- [ ] Streamlit 网页面板（飞书推送已够用）
- [ ] config/kl8.yaml（常量少，硬编码清晰）
