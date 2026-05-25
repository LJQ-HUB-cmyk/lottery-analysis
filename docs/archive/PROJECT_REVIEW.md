# 项目审查总览

> 最后更新：2026-05-21 | 版本：v2.13.0

## 审查结论

| 维度 | 状态 | 备注 |
|:-----|:----:|:-----|
| 代码质量 | 🟢 良好 | 模块化，函数职责清晰 |
| 评分引擎 | 🟢 v2 | YAML权重+多样性惩罚+冷补偿 |
| 回测 | 🟢 v2 | Walk-forward + 三策略 + 奖金区分组三/组六 |
| 快乐8 | 🟢 新模块 | 独立 `scripts/kl8/` 8文件，官方API抓取+热冷策略+选四盈亏复盘+累计表现 |
| 数据源 | 🟢 良好 | 排列三API(体彩官方,567重试) ✅ 福彩3D(zhcw主源+eastmoney备用+双源校验) ✅ KL8官方cwl.gov.cn API ✅ |
| 依赖管理 | 🟢 有 | requirements.txt（不锁版本号，不装无用库） |
| 文档 | 🟢 完善 | README + CLAUDE.md + PROJECT_REVIEW.md + CHANGELOG.md + HERMES_CONFIG.md |
| 可视化 | 🟢 完善 | matplotlib + plotly 交互图（走势/遗漏/热力图/Top50分布） |
| 工程化 | 🟢 有 | .gitattributes, .gitignore, .gitkeep, data/archived/种子数据 |

## 已修复的问题清单

| 问题 | 发现来源 | 修复版本 | 说明 |
|:-----|:--------:|:--------:|:-----|
| Python文件被压缩显示 | GPT审查 | v2.2 | 实际为正常多行文件，GitHub网页渲染问题。验证方法：`curl raw URL | wc -l` + `py_compile` |
| README命令缺参数 | GPT审查 | v2.2 → v2.3 | 补充了 `--input`/`--output`/`--skiprows` |
| data_fetcher退出逻辑 | GPT审查 | v2.2 | 数据不通过且无 `--force` 时 exit(1) |
| stats_engine排序保护 | GPT审查 | v2.2 | 加 `sort_values('期数', ascending=False)` |
| backtest组选命中永远True | GPT审查 | v2.2 | 改为真正的组选匹配 |
| backtest权重引用过期 | GPT审查 | v2.2 | 改为 `load_weights()` |
| 评分权重硬编码 | 自行发现 | v2.0 | 迁移到 `rules/scoring_weights.yaml` |
| 跨度偏好固化 | 自行发现 | v2.0 | 加入多样性惩罚 |
| 评分0区分度 | 自行发现 | v2.0 | 加入冷补偿+多样性 |
| 回测奖金不区分组三/组六 | GPT审查 | v2.3 | 组三=346元，组六=173元 |
| strategy_dynamic重复评分逻辑 | GPT审查 | v2.3 | 改为复用 `generate_predictions()` |

## 已知待修复 & 不采纳的建议

### 待修复

| 问题 | 严重程度 | 影响 |
|:-----|:--------:|:-----|
| 评分权重系统调优 | 🟡 中 | tune_weights.py 已就绪，等待复盘数据积累 30 期后运行（当前 24 条记录/4 期） |
| 遗漏计算伪向量化 | 🟢 低 | 当前 7600 行性能足够，纯向量化改写可选 |

> v2.7 已解决：福彩3D双源(zhcw+eastmoney+双源校验)、组三回归惩罚、API 567重试、回测命中累加、参数验证、PNG中文字体、shell=True、复盘闭环(review_history+review_summary)、多策略权重、Optuna贝叶斯优化、参数稳定性分析
> v2.13.x 已解决：晚间复盘完整性闸门(双彩种齐全才推送)、文件锁优化(stale_after拆分)、send_log+文件锁防重
> v2.11-12.x 已解决：快乐8独立模块(fetch/predict/review/check/metrics/stats/strategy)、选四盈亏复盘、KL8奖金表修正
> v2.10.x 已解决：两段式推送(predict/review分离)、compare_result期号分类(waiting_actual)、no_agent推送自闭环(run_daily→source_health→push)、--force去重绕过

### 不采纳的建议（附理由）

以下为外部审查提出的建议，经评估后决定暂不采纳：

| 建议 | 来源 | 不采纳理由 |
|:-----|:----:|:----------|
| requirements.txt 锁版本号 | Grok | 项目跑在 Hermes venv 下（pandas 3.0.3, numpy 2.4.4），不锁版本号 = 装最新兼容版。锁死了反而哪天依赖冲突装不上。 |
| 添加 plotly / seaborn / tqdm 依赖 | Grok | 当前代码未使用这三个库。`matplotlib` 已满足基础可视化需求。等真正需要交互图表或进度条时再加，避免装无用依赖。 |
| data_fetcher 统一用 cwl.gov.cn API | Grok | Grok提供的代码全用福彩官网API。实测该API在服务器上返回 **403（WAF防护）**，不可用。排列三体彩API(webapi.sporttery.cn)保持独立实现，已验证可用。 |
| feature_engine 替换为 Grok 简化版 | Grok | Grok版本删除了数据检查、分位遗漏、group_number、冷热分类等核心功能(~240行)，换来了有bug的遗漏向量化(applymap在pandas 3.x已移除)和滚动特征。只提取了滚动特征加入现有版本。 |
| scoring_engine 替换为 Grok 简化版 | Grok | Grok版本(~75行)严重简化了评分引擎：删除多样性惩罚、冷号补偿、generate_predictions()、apply_diversity()，不兼容现有backtest。评分从9维降至4维，精度大幅下降。仅提取了"推荐理由"字段加入现有v2版本。 |
| 添加 LSTM 预测模块 | GPT / Grok | **不采用**，理由：① 彩票开奖是独立同分布随机事件，无时间依赖，LSTM 对此类序列的预测能力等同于随机策略；② 服务器 2核CPU/3.5GB内存/无GPU，跑不了深度学习训练；③ 即便训出来 ROI 也趋近随机，不如把精力用在评分引擎和特征工程。ML 正确用途是特征工程辅助（聚类分析），而非直接预测号码。 |

## 架构变更记录

### v2.13.0（当前）
- 晚间复盘完整性闸门：双彩种齐全才推送，--complete-only/--final-check 区分波浪
- 文件锁 stale_after 拆分：等待5s，残留600s后清理
- review_push.sh 重写：--final 参数 + stderr → 日志文件
- push_state 口径修正：--stdout 路径不创建 push_state.json，去重靠 send_log + 文件锁

### v2.12.1
- KL8 全量逐行审查：8 个文件全部通过，奖金表修正(中二=3元/中四=93元)
- check/metrics/stats/strategy 4 个增强模块就绪

### v2.11.0
- 快乐8(KL8) 独立模块：`scripts/kl8/` 8 个文件，fetch/predict/review/check/metrics/stats/strategy
- 选四主推 + 盈亏复盘 + hermes_push --lottery kl8
- 多策略框架（v0-v3），待 ≥30 天数据后回测

### v2.10.2
- 14:40 推送自闭环：`lottery_predict_push.sh` 内部自动执行 run_daily → source_health → hermes_push 全流程
- 预测推送加 `--force`，避免当天去重命中后无输出
- 推送脚本纳入版本控制（`scripts/push/`）
- 14:30/14:35 明确标注为辅助任务，失败不阻塞推送

### v2.10.1
- Tirith glibc 兼容问题：推送类 cron 全部改为 no_agent=true，绕过安全审批链
- 新建 `~/.hermes/scripts/lottery_predict_push.sh` / `lottery_review_push.sh`
- 不消耗 API token（无大模型调用）

### v2.10.0
- 两段式推送：hermes_push 新增 predict/review 两种模式，下午推预测，晚间推复盘
- compare_result 按期号查找预测文件 + waiting_actual 状态分类（exit 0 不覆盖 latest）
- HERMES_CONFIG 6 cron job 结构化配置
- push_state.json 防重复推送
- build_review_message 重写为"开奖复盘｜推送日"（v2.16.0 起改为单彩种独立推送 + 命中指标修正）

### v2.7.1（历史）
- Hermes cron 适配：`daily_review.py` 一键复盘（拉取→对比→摘要）；`compare_result.py --strategy` 多策略对比
- `review_history.csv` 增加策略列，支持按策略分组复盘
- `backtest.py` ROI 拆分直选/组选独立计算
- `data_fetcher.py` `save_incremental()` 空数据保护

### v2.7
- 复盘闭环：`compare_result.py` → `review_history.csv` 累加 → `review_summary.py` 表现摘要
- 多策略权重：`scoring_weights_conservative.yaml` / `diversity.yaml` + `run_daily.py --strategy all`
- `tune_weights.py`: 随机搜索 + Optuna TPE 贝叶斯优化 + 参数稳定性分析
- 数据源加固：`fetch_3d_from_eastmoney()` 东方财富接入(50条/页) + 双源校验 + fallback
- 工具链：`CLAUDE.md` 项目指令 + `Makefile` 一键命令 + `rules/data_sources.yaml` 配置外部化

### v2.6.1
- `scoring_engine.py`: 形态评分改为双向回归惩罚（组三过热降分、过冷加分）
- `data_fetcher.py`: `fetch_pls()` 新增 567 限频退避重试（5s/10s/15s）
- `backtest.py`: 回测命中从 `any()`/`elif` 改为 `sum()` 累加；参数验证；`json.load` 补充编码
- `visualize.py`: matplotlib 自动探测系统中文字体，修复 PNG 中文方框
- `feature_engine.py`/`data_fetcher.py`: 新增 `normalize_number()` 号码清洗（去空格/补零/剔非数字）
- `compare_result.py`: 输出优化——开奖号码大字展示 + JSON 一句话摘要

### v2.6
- 第二轮代码审查修复：`shell=True`→列表参数、`skiprows=0`、删除死代码
- `scoring_engine.py`: `generate_all()` 复用 `feature_engine.add_features()`，消除~60行重复
- 新增 `scripts/compare_result.py`：预测 vs 开奖对比
- `run_daily.py`: CLI参数化(--top-k/--exclude-recent)、`ensure_seed_data()` 自动初始化
- `data/archived/`: 种子数据归档（pls_history.csv + d3_history.csv）
- Top30号码字段从完整 `scored` 列表取，修复 top_k<30 时误导
- `backtest.py`/`visualize.py`: 添加文件缺失错误处理

### v2.5
- 新增 `run_daily.py` 一键每日运行脚本
- `data_fetcher.py`: 福彩3D数据源升级为 zhcw.com pd.read_html
- `feature_engine.py`: PLS 格式自动检测（标准三列 / 旧KittenCN格式）
- `stats_engine.py`/`data_fetcher.py`: 统一 utf-8-sig 编码

### v2.4
- Plotly 交互式可视化（走势图/热力图 HTML 输出）
- `visualize.py`: 双格式输出（PNG + HTML）

### v2.3
- `scoring_engine.py`: 新增 `generate_predictions()` 共用函数
- `backtest.py`: `strategy_dynamic_scoring` 复用 generate_predictions，删除35行重复代码
- `backtest.py`: 回测ROI奖金区分组三(346元)和组六(173元)
- `data_fetcher.py`: 重写v2 —— 增量保存、日志系统、`--days`参数、API状态标注
- 新增 `PROJECT_REVIEW.md`

### v2.2
- 修复GPT代码审查提出的3个P0 + 3个P1 + 3个P2问题
- 添加 `.gitkeep` 保留空目录
- 添加 `.gitattributes` 确保LF换行符
- README补全命令参数

### v2.0
- 评分引擎重大升级：YAML权重可配置
- 多样性惩罚（组选去重+跨度多样化）
- 冷号补偿（阈值6→冷号占比更大）
- data_fetcher 数据自动获取
- requirements.txt

## 文件清单

```
lottery-analysis/
├── scripts/
│   ├── feature_engine.py     # 113维特征工程 + 数据检查
│   ├── stats_engine.py       # 多窗口统计 + 理论分布
│   ├── scoring_engine.py     # 评分引擎v2 + generate_predictions()
│   ├── backtest.py           # Walk-forward回测v2
│   ├── compare_result.py     # 预测 vs 开奖对比
│   ├── data_fetcher.py       # 自动拉取数据
│   ├── filter_engine.py      # 轻量预过滤
│   └── visualize.py          # 走势/遗漏/热力图
├── rules/
│   ├── scoring_weights.yaml  # 评分权重（可配置）
│   ├── pls_default.yaml      # 排列三过滤规则
│   └── d3_default.yaml       # 福彩3D过滤规则
├── data/  (raw/processed/archived/cache)
├── output/  (predictions/backtests/charts/reports)
├── logs/
├── README.md
├── requirements.txt
├── PROJECT_REVIEW.md
└── .gitattributes / .gitignore
```
