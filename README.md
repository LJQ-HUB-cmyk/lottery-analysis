
# 彩票数据分析与预测系统（排列三 / 福彩3D / 快乐8）

基于**多窗口统计 + 理论分布 + 动态评分引擎**的彩票评分预测系统。排列三/福彩3D 对 1000 注号码多维度打分排序；快乐8 生成 20 码候选池（1-80 选 20）。

> ⚠️ **重要声明**：彩票开奖完全随机，本项目仅供学习、研究和娱乐参考。所有分析仅基于历史数据统计和理论分布，不代表未来开奖结果。请理性对待，量力而行。不保证任何命中率。

## 快速开始

> 项目目录已预置 `.gitkeep` 占位文件。若从零克隆，可用 `mkdir -p data/raw data/processed data/cache output/predictions output/backtests output/charts output/reports logs` 创建完整目录结构。

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 更新数据
python scripts/data_fetcher.py --all
#     ✅ 福彩3D通过 eastmoney.com 自动抓取（主源），数据正常获取
#     旧 cwl.gov.cn WAF 403 问题已由 eastmoney 主源解决

# 3. 完整预测流程（排列三）
python scripts/data_fetcher.py --lottery pls
python scripts/feature_engine.py \
  --input data/raw/pls_raw.csv \
  --output data/processed/pls_feat.csv \
  --lottery pls \
  --force
# feature_engine 自动识别格式：标准三列(期号,日期,号码) 或 旧KittenCN格式
# 旧格式需要 --skiprows 参数，新格式自动处理

python scripts/stats_engine.py --lottery pls
python scripts/scoring_engine.py --lottery pls --top-k 30

# 4. 完整预测流程（福彩3D）
# 数据已内置 seed（data/archived/d3_history.csv），首次运行自动复制
python scripts/feature_engine.py --input data/raw/d3_raw.csv --output data/processed/d3_feat.csv --lottery d3
python scripts/stats_engine.py --lottery d3
python scripts/scoring_engine.py --lottery d3 --top-k 30

# 5. 回测
python scripts/backtest.py --lottery pls --periods 100 --top-k 30
python scripts/backtest.py --lottery d3 --periods 100 --top-k 30
```

## 正式运行入口

> 以下为 Hermes cron 使用的正式入口。cron 只跑 shell，shell 只跑 Job，Job 负责全部业务逻辑。

| 入口 | 用途 | 调用链 |
|------|------|--------|
| `bash scripts/push/lottery_predict_push.sh` | PLS/D3 预测 | → `lottery_predict_job.py` → run_daily + source_health + hermes_push |
| `bash scripts/push/lottery_review_push.sh [--final]` | PLS/D3 复盘 | → `lottery_review_job.py --stage normal\|final` → daily_review + hermes_push |
| `bash scripts/push/kl8_predict_push.sh` | KL8 预测 | → `kl8_predict_job.py` → fetcher + predictor + stats + hermes_push |
| `bash scripts/push/kl8_review_push.sh` | KL8 复盘 | → `kl8_review_job.py` → fetcher + reviewer + metrics + hermes_push |

> `run_daily.py` / `daily_review.py` / `scripts/hermes_push.py` 不直接配入 cron。
> 它们只被 Job 调用，或手动调试使用。

## 项目结构

```
lottery-analysis/
├── run_daily.py                  # 一键每日运行入口
├── scripts/
│   ├── data_fetcher.py           # 多源数据抓取（js-lottery/eastmoney主源 + sporttery/zhcw备用 + 熔断 + 校验）
│   ├── feature_engine.py         # 113维特征工程 + 数据质量检查
│   ├── stats_engine.py           # 多窗口统计 + 理论分布
│   ├── scoring_engine.py         # 评分引擎v2（YAML权重 + 回归惩罚 + 多样性）
│   ├── backtest.py               # Walk-forward 回测（多策略对比 + ROI拆分）
│   ├── compare_result.py         # 预测 vs 开奖对比 + review_history累加
│   ├── review_summary.py         # 最近N期复盘表现摘要
│   ├── daily_review.py           # 每日复盘一键脚本（Hermes cron调用）
│   ├── tune_scoring_params.py     # 权重自动调优（Optuna 贝叶斯优化）
│   ├── build_ensemble_predictions.py # 策略融合（共识投票加权预测）
│   ├── apply_draw_overrides.py    # 人工开奖修正
│   ├── audit_lottery_data.py      # 数据审计
│   ├── report_tuning_status.py    # 查看调参状态
│   ├── patch_pls_dates.py         # 排列三历史日期补全工具
│   ├── visualize.py              # 走势图/热力图（matplotlib + plotly）
│   ├── issue_utils.py            # 期号标准化（PLS/D3格式互转）
│   ├── source_health.py          # 数据源健康报告
│   ├── hermes_push.py            # 两段式推送 CLI 入口（调用 push_formatter + push_sender）
│   ├── push_formatter.py         # 推送内容格式化（预测/复盘/KL8/健康报告）
│   ├── push_sender.py            # 多通道发送（飞书/微信/webhook）+ 去重 + 锁
│   ├── kl8/                    # 快乐8独立模块
│   │   ├── common.py           # 共享常量与工具
│   │   ├── fetcher.py          # 官方API抓取 + 校验 + --check
│   │   ├── predictor.py        # 20码池 + 选四主推
│   │   ├── reviewer.py         # 选四命中/盈亏/期号精确匹配
│   │   ├── check.py            # 全链路健康检查（支持 --stage predict/review/full）
│   │   ├── metrics.py          # 近N期累计成本/奖金/盈亏（含加权命中分）
│   │   ├── stats.py            # 奇偶/大小/连号/和值/冷热/全量遗漏统计
│   │   ├── backtest.py         # Walk-Forward 回测（热冷策略 vs 随机基准）
│   │   ├── compare_strategies.py # 多策略对比报告
│   │   └── strategy.py         # 4策略统一接口（暂不启用）
│   ├── jobs/                    # Python job 业务编排（Shell 薄入口调用）
│   │   ├── lottery_predict_job.py   # PLS/D3 预测编排
│   │   ├── lottery_review_job.py    # PLS/D3 复盘编排（--stage normal/final）
│   │   ├── kl8_predict_job.py       # KL8 预测编排
│   │   └── kl8_review_job.py        # KL8 复盘编排（删旧文件+时间戳+期号校验）
│   ├── lib/                     # 共享库
│   │   └── job_status.py            # 统一状态文件读写
│   └── push/                   # Hermes cron no_agent 推送脚本（薄入口）
│       ├── lottery_predict_push.sh  # 预测推送（→ lottery_predict_job.py）
│       ├── lottery_review_push.sh   # 复盘推送（→ lottery_review_job.py）
│       ├── kl8_predict_push.sh      # KL8预测推送（→ kl8_predict_job.py）
│       ├── kl8_review_push.sh       # KL8复盘推送（→ kl8_review_job.py）
│       └── kl8_check_push.sh        # KL8健康检查（异常时主动推送）
├── rules/
│   ├── scoring_weights.yaml              # 默认权重
│   ├── scoring_weights_conservative.yaml # 稳健策略
│   ├── scoring_weights_diversity.yaml    # 多样性策略
│   ├── prizes.yaml                       # 各彩种各玩法奖金配置
│   └── data_sources.yaml                 # 数据源配置（URL外部化）
├── data/
│   ├── raw/                  # 原始CSV（data_fetcher.py储存位置）
│   ├── processed/            # 特征工程输出（113维）
│   ├── archived/             # 种子数据（首次clone自动复制到raw/）
│   ├── cache/                # 统计缓存 + 熔断状态
│   └── quarantine/           # 坏数据隔离区
├── output/
│   ├── predictions/          # 预测结果JSON（多策略独立输出）
│   ├── reviews/              # 复盘总表（review_history.csv）
│   ├── backtests/            # 回测报告
│   ├── charts/               # 可视化图表
│   ├── reports/              # 数据检查报告 + 健康报告 + 对比报告
│   ├── push/                 # 推送日报 + 发送日志 + pending补发
│   ├── status/               # 任务状态JSON（运行时产物，git忽略）
│   └── tuning/               # 调参记录
├── tests/                    # 单元测试（pytest）
├── CLAUDE.md                 # Agent 项目指令
├── Makefile                  # 一键命令入口
├── CHANGELOG.md              # 集中式变更日志
├── docs/                     # 项目文档（配置/记录/计划）
└── requirements.txt          # 依赖清单
```

## 评分引擎（核心）—— v2

### 权重配置（`rules/scoring_weights.yaml`）

| 维度 | 默认权重 | 评分方式 |
|------|:--------:|----------|
| 和值 | 18 | 理论组合比例×60% + 近30期频率比例×40% × 过热衰减 |
| 跨度 | 15 | 同上 |
| 形态 | 12 | 理论回归惩罚——实际频率偏离理论双向扣分（组三过热降分、过冷加分） |
| 奇偶 | 8 | 1-2个奇数=满分，全奇全偶=低分 |
| 大小 | 8 | 同上 |
| 012路 | 7 | 均衡=高分，一路集中=低分 |
| **冷热** | **10 ↑** | 0冷号+有热号=满分（冷号阈值由8→**6**） |
| **遗漏** | **7 ↑** | 三个号码在平均遗漏半值内=满分 |
| 组三六偏向 | 8 | 保留权重位，实际回归惩罚已由形态维度统一处理 |
| **多样性** | **10 新增** | 组选重复扣分 + 跨度多样性加分 |

**v2 关键改进：**
- ✅ 所有权重从 YAML 加载，改策略不需改代码
- ✅ **组选多样性惩罚**：同组选号码只保留最高分直选
- ✅ **跨度多样性促进**：Top-K 尽量覆盖多个跨度
- ✅ **冷号阈值下调**：遗漏>6视为冷号（原8），给冷号更多机会
- ✅ **过热衰减更敏感**：近5期出现≥3次打6折
- ✅ **走势分计算修复**：从 `*30` 改为理论频率比

### 评分原则
- **不硬过滤**：1000注全部打分，按总分排序
- **理论+近期混合**：每条规则 = 理论分布分×60% + 近期走势分×40%
- **过热衰减**：近5期高频特征折扣
- **理论回归惩罚**：形态/跨度偏离理论分布越大扣分越多

## 后续计划

- [x] 评分权重系统调优 — 已升级为 `tune_scoring_params.py`（Optuna walk-forward），auto_tuned 灰度运行中
- [x] 遗漏计算向量化 — 已用 numpy 批量计算替代 `df.iloc` 逐元素赋值
- [x] GitHub Actions 每日自动运行 — 已创建 `.github/workflows/daily.yml`

> ❌ **不考虑 LSTM/ML 预测模块**，原因：
>
> 1. **理论不成立**：彩票开奖是独立同分布随机事件，每期之间无时间依赖关系，LSTM 对此类序列的预测能力等同于随机策略
> 2. **硬件不支持**：当前服务器为 2 核 CPU、3.5GB 内存、**无 NVIDIA GPU**（`nvidia-smi: 未安装`），无法运行深度学习训练
> 3. **投入产出比低**：即便训练出模型，其 ROI 在统计上也趋近于随机策略，不如把精力用在优化评分引擎和特征工程上
>
> ML 的正确用途：特征工程辅助（如聚类分析辅助生成规则），而非直接预测号码。

## 数据来源

| 彩种 | 源 | 方法 |
|------|-----|------|
| 排列三（体彩） | 体彩官方API | `data_fetcher.py` 自动拉取 JSON | ✅ 已验证可用 |
| 福彩3D | 东方财富(eastmoney) | `data_fetcher.py` 自动拉取 JSON（主源） | ✅ 已验证可用 |

### 福彩3D手动数据准备（备用）

> ✅ **`data_fetcher.py --lottery d3` 默认通过 eastmoney.com 自动拉取**，数据正常获取。
> 以下仅作为 eastmoney 异常时的备用方案。

如果自动抓取失败，请手动准备 `data/raw/d3_raw.csv`：

```csv
期号,日期,号码
2025123,2025-05-01,583
2025122,2025-04-30,147
2025121,2025-04-29,902
```

- 字段：`期号`（数字）、`日期`（YYYY-MM-DD）、`号码`（3位数字连写）
- 可参考 [konglr/Lottery](https://github.com/konglr/Lottery) 获取历史数据
- 准备好后继续执行第4步的预测流程即可

### 开奖时间

| 彩种 | 官方开奖 | 建议拉取 |
|------|---------|---------|
| 排列三 | 每日 21:25 | 22:00 以后 |
| 福彩3D | 每日 21:15 | 22:00 以后 |

> 数据源（API/网页）通常在开奖后 15-30 分钟更新，过早拉取可能获取不到最新期。

### 排列三数据说明

当前推荐使用 `scripts/data_fetcher.py --lottery pls` 生成标准 CSV：
`期号,日期,号码`

这种格式不需要 `--skiprows`，`feature_engine.py` 会自动识别。

只有使用旧版 KittenCN / 500.com 双表头或多说明行 CSV 时，才需要手动指定：
- 2 行说明：`--skiprows 2`
- 3 行说明：`--skiprows 3`

不确定时先执行：
`head -10 data/raw/pls_raw.csv`

## 回测

```bash
python scripts/backtest.py --lottery pls --periods 100 --top-k 30
```

采用 **Walk-forward** 方式（避免未来函数），比较三种策略：
1. **随机基准**：纯随机选30注
2. **固定规则**：固定权重评分
3. **动态调整**：根据近期表现调权重

## 可视化

生成走势图、热力图（matplotlib PNG + plotly 交互 HTML）：

```bash
# 排列三全部图表（PNG + HTML 两种格式）
python scripts/visualize.py --lottery pls --chart all
# 福彩3D全部图表
python scripts/visualize.py --lottery d3 --chart all
# 仅生成走势图
python scripts/visualize.py --lottery pls --chart trend
# 仅生成交互HTML（不含PNG）
python scripts/visualize.py --lottery pls --chart all --output-format html
```

- **PNG 静态图**：走势图、遗漏图、热力图 → `output/charts/`
- **HTML 交互图**：走势图、热力图、Top50推荐分布（支持悬停/缩放）→ `output/charts/`
- plotly 为可选依赖，未安装则自动跳过 HTML 输出

## 预测 vs 开奖对比

开奖后比对预测结果与实际开奖：

```bash
python scripts/compare_result.py --lottery pls
python scripts/compare_result.py --lottery d3
```

输出：直选/组选命中、和值差、跨度差、形态一致性。报告保存至 `output/reports/{lottery}_compare_latest.json`。

## 自动化读取最新预测结果

预测结果同步保存为固定路径，方便脚本/Hermes/GPT自动读取：

```
output/predictions/latest_pls.json      # 排列三最新预测（固定入口）
output/predictions/latest_d3.json       # 福彩3D最新预测（固定入口）
output/predictions/pls_predict_26125.json   # 按期号命名的历史记录
output/predictions/d3_predict_2026125.json  # 同上
```

### GPT/Grok 直接读取 URL

```
https://raw.githubusercontent.com/liu208987-git/lottery-analysis/main/output/predictions/pls_predict_{期号}.json
https://raw.githubusercontent.com/liu208987-git/lottery-analysis/main/output/predictions/d3_predict_{期号}.json
```

## 每日推荐流程

### 一键每日运行（推荐）

```bash
python run_daily.py                     # 跑排列三 + 福彩3D（默认Top-30）
python run_daily.py pls                 # 只跑排列三
python run_daily.py d3                  # 只跑福彩3D
python run_daily.py --top-k 10          # 推荐10注
python run_daily.py pls --top-k 20 --exclude-recent 3
```

脚本自动执行：seed数据初始化 → 数据更新 → 特征工程 → 统计引擎 → 评分预测 → 可视化。
预测结果保存至 `output/predictions/{lottery}_predict_{期号}.json`。

### 每日自动推送（Hermes cron）

| 时间 | 操作 | 模式 | 说明 |
|:---|:-----|:----:|:-----|
| 14:40 | `bash scripts/push/lottery_predict_push.sh` | no_agent | PLS/D3 预测（自闭环：Job→run_daily→hermes_push） |
| 14:50 | `bash scripts/push/kl8_predict_push.sh` | no_agent | KL8 预测 |
| 22:05 | `bash scripts/push/lottery_review_push.sh --prepare-only` | no_agent | 拉取开奖+应用人工修正（不推送） |
| 22:10 | `bash scripts/push/lottery_review_push.sh --lottery pls --final` | no_agent | 排列三复盘（带Top30，未齐推兜底） |
| 22:15 | `bash scripts/push/lottery_review_push.sh --lottery d3 --final` | no_agent | 福彩3D复盘（带Top30，未齐推兜底） |
| 22:20 | `bash scripts/push/kl8_review_push.sh` | no_agent | KL8 复盘（带完整候选池） |

> **单彩种独立推送**：PLS/D3/KL8 分开推送，哪个数据齐了推哪个，不再等两彩种齐全。
> **dedup_key 去重**：按期号拆分（`review:{date}:pls-{issue}`），同一期只推一次。
> 详见 [docs/HERMES_CONFIG.md](docs/HERMES_CONFIG.md)。

## Job 架构（v2.15.0+）

Shell 脚本降级为薄入口（cd/加锁/启动/日志），业务逻辑迁移到 Python job 层：

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

**架构层次：**
```
Hermes / cron            → 定时触发
scripts/push/*.sh        → 薄入口：切目录、加锁、日志、启动 Python
scripts/jobs/*.py        → 业务编排：拉取、预测/复盘、状态判断、去重
scripts/hermes_push.py   → CLI 入口
  scripts/push_formatter.py → 推送内容生成
  scripts/push_sender.py    → dedup_key 去重 + 多通道发送
output/status/*.json     → 每次任务的状态记录（ready/pushed/skipped_waiting/error）
```

**退出码规范：** 0=正常（含等待开奖/已推送跳过），2=业务异常（阻断推送），3=环境异常。

## 快乐8（KL8）—— 独立模块

快乐8 每期开 20 个号码（1-80）。当前使用**热号 12 + 冷号 8**混合策略生成 20 码候选池，复盘统计命中数（随机期望约 5/20）。

```bash
# 数据 + 预测 + 统计
python scripts/kl8/fetcher.py --pages 3
python scripts/kl8/predictor.py
python scripts/kl8/stats.py

# 开奖后复盘 + 累计表现
python scripts/kl8/reviewer.py
python scripts/kl8/metrics.py

# 全链路健康检查
python scripts/kl8/check.py

# 推送
python scripts/hermes_push.py --mode predict --lottery kl8
python scripts/hermes_push.py --mode review --lottery kl8
```

> 快乐8 为独立模块（`scripts/kl8_*.py`），不影响排列三/福彩3D 主流程。

## 已知问题与限制

- 🟢 **福彩3D自动拉取**：eastmoney.com 主源自动获取数据，已验证可用；zhcw.com 保留为备用校验源
- ✅ **评分权重已调优**：`tune_scoring_params.py`（Optuna walk-forward）已生成 auto_tuned 权重，灰度观察 10 天
- ⚠️ **彩票结果高度随机**：所有分析仅基于历史统计，不代表未来结果

## 风险提示

彩票开奖结果具有高度随机性。所有分析仅基于历史数据统计和理论分布，不代表未来开奖结果。请理性看待，不建议将分析结果作为实际投注依据。

## 更新日志

- **v2.15.0** (2026-05-22)：Job 架构改造——Shell 脚本瘦身为薄入口，业务逻辑迁移到 4 个 Python job；新增 job_status.py 统一状态库；hermes_push 去重从文本 hash 升级为业务键（dedup_key）；daily_review 失败控制（exit 2 阻断推送）；全流程 flock 锁；统一退出码 0/2/3；output/status/ 任务状态追踪
- **v2.14.0** (2026-05-21)：推送脚本部署修复——~/.hermes/scripts/ 软链接被 Hermes 拦截，改为实体文件复制；KL8 推送链路修复；lottery_review_push.sh 新版同步（日志/--complete-only/--final-check）
- **v2.13.0** (2026-05-21)：晚间复盘完整性闸门——双彩种齐全才推送；--complete-only/--final-check 参数区分波浪；文件锁 stale_after 优化(5s等待/600s过期)；review_push.sh stderr→日志文件；push_state口径修正
- **v2.12.1** (2026-05-20)：KL8全量逐行审查通过——奖金表修正(中二=3元)、check/metrics/stats/strategy 4个增强模块、全链路健康检查、累计表现追踪、多策略框架就绪
- **v2.11.0** (2026-05-20)：新增快乐8(KL8)独立模块——kl8_fetcher 官方API数据抓取、kl8_predictor 热12+冷8候选池、kl8_reviewer 选修命中+盈亏复盘、hermes_push --lottery kl8 推送；feature/kl8 分支隔离开发
- **v2.10.3** (2026-05-20)：复盘字段对齐——review_history 新增命中范围/命中号码/命中排名/Top5直选/Top5组选 5 个字段；hermes_push 复盘按实开期号读 `*_predict_{issue}.json` 而非 latest；命中时展示具体号码+排名+范围，Top5 标注为"参考"
- **v2.10.2** (2026-05-20)：14:40 推送自闭环——lottery_predict_push.sh 内部自动执行 run_daily → source_health → hermes_push 全流程，不再依赖 14:30 预生成；推送加 `--force` 避免去重误拦截；推送脚本纳入版本控制（`scripts/push/`）；文档同步 no_agent 审批说明
- **v2.10.1** (2026-05-19)：推送链路加固——推送类 cron 改为 no_agent 模式绕过 Tirith glibc 兼容问题；lottery_predict_push.sh / lottery_review_push.sh 脚本化；HERMES_CONFIG.md 同步 no_agent 配置；详细讨论见 `changelog/2026-05-19-fix-tirith-cron-push.md`
- **v2.10.0** (2026-05-19)：两段式推送 predict/review 分离——hermes_push 新增 predict(预测)/review(复盘)两种模式；compare_result 按期号查找预测文件 + waiting_actual 状态分类(exit 0 不覆盖latest)；HERMES_CONFIG 6 cron job 结构化配置；push_state.json 防重复推送
- **v2.7.1** (2026-05-16)：Hermes cron 适配——新增 `daily_review.py` 一键复盘脚本；`compare_result.py` 支持 `--strategy` 多策略对比；`review_history.csv` 增加策略列；回测 ROI 拆分直选/组选；`save_incremental` 空数据保护
- **v2.7** (2026-05-16)：复盘闭环 + 数据源加固 + 工具链完善——review_history.csv 长期复盘累加、review_summary.py 表现摘要、多策略权重(conservative/diversity)、tune_weights.py 随机搜索+Optuna贝叶斯优化+参数稳定性分析；东方财富福彩3D接入(50条/页)+双源校验+主源失败自动fallback；CLAUDE.md项目指令、Makefile一键命令、data_sources.yaml配置外部化
- **v2.6.1** (2026-05-15)：P1/P2集中修复——组三回归惩罚(形态评分双向扣分)、API 567退避重试、回测多注命中累加(sum替代any/elif)、回测参数验证、PNG中文字体自动探测；号码清洗加固(normalize_number去空格/补零/剔除非数字)；compare_result输出优化(开奖号码大字展示+一句话摘要)
- **v2.6** (2026-05-15)：第二轮代码审查修复——shell=True→列表参数、skiprows=0、删除openTime死代码、is_monotonic_increasing优化、generate_all()复用add_features()去重；新增 compare_result.py 预测vs开奖对比脚本；run_daily.py CLI参数化(--top-k/--exclude-recent)；seed数据归档(data/archived/)；Top30字段修复
- **v2.5.1** (2026-05-15)：新增 `run_daily.py` 一键每日运行脚本；福彩3D数据源升级为zhcw.com；feature_engine兼容简洁3列CSV格式
- **v2.5** (2026-05-15)：scoring_engine JSON结构升级——过滤说明改object、代码版本字段、展示理由字段；README模式A/B说明(--skiprows 3/2)；git兼容Python 3.6；.gitignore放行output/predictions/*.json
- **v2.4.1** (2026-05-15)：feature_engine.py numpy 2.x兼容修复(np.char.add)、遗漏特征向量化(20x加速)；scoring_engine新参数exclude-mode/include-baozi/target-issue；backtest同步
- **v2.4** (2026-05-15)：Plotly交互式可视化(HTML双格式)；README福彩3D入口优化；GPT/Grok建议评估
- **v2.3** (2026-05-15)：`generate_predictions()` 抽取共用、回测奖金区分组三(346元)/组六(173元)、新增 PROJECT_REVIEW.md
- **v2.2** (2026-05-15)：P0/P1/P2 代码审查修复（README参数补全、回测组选判断修复、数据检查退出保护等）
- **v2.0** (2026-05-15)：评分引擎重大升级——YAML权重配置、多样性惩罚、冷号补偿、data_fetcher 数据自动获取
- **v1.0** (2026-05-14)：初始版本——基础评分引擎、特征工程、回测
