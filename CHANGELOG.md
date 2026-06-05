# 变更日志

> 集中式变更日志，按版本从新到旧排列。单日详细记录见 `docs/` 目录。

## v2.18.0 (2026-06-05)

- **实盘策略调优**：形态权重 12→16（修复 D3 组三全军覆没）；过热衰减 0.6/0.8→0.75/0.9（修复号码频繁掉出 Top30）；多样性 span_spread 8→5（修复跨差偏大）
- **性能优化**：`feature_engine.py` 遗漏值计算重写为 numpy 批量版本；`scoring_engine.py` `generate_all()` 加模块级缓存；`stats_engine.py` 理论分布加模块级缓存
- **Bug 修复**：`scoring_engine.py` `cold_count` 未定义风险；`compare_result.py` 期号类型统一为 str；`hermes_push.py` KL8 空 target 匹配漏洞；`compare_result.py` `__len__()` 改为 `len()`；`push_sender.py` 微信首次发送不再强制 sleep 5s
- **代码重构**：`scoring_engine.py` 抽取 `_score_frequency()` 通用函数；`hermes_push.py` 拆分为 `push_formatter.py` + `push_sender.py` + 薄 CLI 入口；`backtest.py` `_build_freq` 移至循环外；KL8 5 个模块消除 import 时 `mkdir` 副作用
- **KL8 完善**：新增 `backtest.py` 回测脚本；predictor `--zone-balance` 分区均衡约束；metrics 加权命中分（中四=93/中三=5/中二=3）；stats 全量 80 号码遗漏表；check `--stage predict|review|full` 参数；新增 `compare_strategies.py` 多策略对比
- **数据源**：新增 `patch_pls_dates.py` 历史日期补全工具；`data_fetcher.py --verify-backup` 备份源验证
- **推送增强**：`push_formatter.py` 增加奇偶/大小倾向展示
- **工程化**：新增 `rules/prizes.yaml` 奖金配置；新增 `.github/workflows/daily.yml`；新增 `tests/` 目录（35 个测试）；`.gitignore` 加 `.pytest_cache/`
- **清理**：删除 `_fetch_check.py`

## v2.17.0 (2026-05-25)

- **auto_tuned 自动调参闭环**：`tune_scoring_params.py`（Optuna walk-forward）+ `audit_lottery_data.py`（数据审计）+ `report_tuning_status.py`（灰度观察）
- **auto_tuned 接入全链路**：`run_daily.py --strategy all` 自动包含、`daily_review.py` 复盘对比、`hermes_push.py` 推送展示
- **KL8 健康检查推送**：`kl8_check_push.sh` 改为 no_agent/origin，异常时主动推送飞书
- **复盘推送 v3 重构**：命中指标按命中号码实时计算、命中展最佳策略Top30/未中展Top10、5列无编号、组选池"缺数字X"、单彩种复盘只显示对应彩种近期表现

## v2.16.0 (2026-05-24)

- **单彩种独立推送**：PLS/D3/KL8 分开推送（22:05准备→22:10PLS→22:15D3→22:20KL8），删除旧三波补偿
- **复盘日期口径修正**：标题 `开奖复盘｜推送日`，归档按期号另存
- **Top30 全量展示**：复盘消息每条策略展示完整30注（带排名编号→5列无编号）
- **五码/六码组选**：`top_digits()` + `check_group_hit()`，预测+复盘推送展示组选池和命中检测
- **人工开奖修正兜底**：`draw_overrides.csv` + `apply_draw_overrides.py` + 审计日志
- **代码审查大修复**：41项发现→25项修复→15项延后→1项跳过（详见审查报告）
- **文档大清理**：删除过期文档、精简冗余、更新所有过期引用

## v2.15.0 (2026-05-22)

- **Job 架构改造**：Shell 脚本瘦身为薄入口（cd/加锁/启动Python/日志），业务逻辑迁移到 Python job
- **新增 4 个 Python job**：`scripts/jobs/kl8_review_job.py`（删旧文件+时间戳+期号三重校验）、`lottery_review_job.py`（--stage normal/final 开奖齐全判断）、`kl8_predict_job.py`、`lottery_predict_job.py`
- **新增统一状态库**：`scripts/lib/job_status.py`，5 种状态枚举（ready/pushed/skipped_waiting/skipped_already_sent/error）
- **去重升级**：hermes_push.py 新增 `already_sent_by_key` + `--dedup-key` CLI 参数，从文本 hash 去重升级为业务键（按期号）去重
- **daily_review.py 失败控制**：`run()` 返回值聚合，真正异常 exit 2 阻断推送
- **全流程锁**：kl8_review_push.sh + lottery_review_push.sh 添加 flock，防止三波任务重叠执行
- **cron 推送去 --force**：kl8_predict_push.sh + lottery_predict_push.sh 去掉 --force，靠 dedup_key 去重
- **统一退出码**：0=正常（含等待开奖），2=业务异常，3=环境异常
- **状态可追踪**：新增 `output/status/` 目录，每次任务写 status JSON

## v2.14.0 (2026-05-21)

- **推送脚本部署修复**：`~/.hermes/scripts/` 软链接被 Hermes 安全策略拦截，改为实体文件复制
- **KL8 推送链路修复**：kl8_predict_push.sh / kl8_review_push.sh 文件缺失导致 cron 任务失败，新建实体文件
- **lottery_review_push.sh 旧版同步**：旧版缺少日志/--complete-only/--final-check/--final 参数，同步到新版
- **HERMES_CONFIG 更新**：6→9 任务，时间修正，KL8 健康检查新增
- **维护方式确立**：改项目 `scripts/push/` 后需手动 `cp` 到 `~/.hermes/scripts/`

## v2.13.0 (2026-05-21)

- **晚间复盘完整性闸门**：双彩种齐全才推送，--complete-only(21:35/22:05)/--final-check(23:10) 区分波浪
- **文件锁优化**：acquire_push_lock stale_after 拆分(5s等待/600s过期)，防止并发重复推送
- **review_push.sh 重写**：支持 --final 参数 + stderr → 日志文件（不再丢弃错误信息）
- **HERMES_CONFIG push_state 口径修正**：全程改为 send_log.jsonl + 文件锁防重
- **CLAUDE.md 未解决问题登记**：js-lottery fallback / 推送记录缺失 / push_state 预期行为

## v2.12.1 (2026-05-20)

- **KL8 全量逐行审查**：8 个文件全部 py_compile 通过 + 逻辑审查
- **奖金表修正**：选四中二=3元（官方规则），中四=93元（官方标准）
- **增强模块就绪**：check 健康检查、metrics 累计表现、stats 统计指标、strategy 多策略框架
- **KL8 后续计划清单**：P1 回测/rules/zone-balance，P2 多策略对比/全量遗漏/stage参数

## v2.11.0 (2026-05-20)

- **快乐8(KL8) 独立模块**：`scripts/kl8/` 8 个文件（fetcher/predictor/reviewer/check/metrics/stats/strategy）
- **数据抓取**：官方 cwl.gov.cn API，20 号码 1-80 严格校验
- **选四主推**：热号12+冷号8 → 20码候选池 → 近5期稳定度提取4码
- **盈亏复盘**：选四奖级表(93/5/3元)、奖金/成本/盈亏、pool 命中统计
- **推送集成**：hermes_push --lottery kl8 复用飞书推送通道
- **多策略框架**：v0随机/v1热冷/v2分区/v3遗漏回补，待 ≥30 天数据后回测评估

## v2.10.2 (2026-05-20)

- **推送自闭环**：`lottery_predict_push.sh` 内部自动执行 run_daily → source_health → hermes_push 全流程
- **预测推送加 `--force`**：避免当天去重命中后无输出，每次 14:40 到点强制推送
- **推送脚本纳入版本控制**：`scripts/push/lottery_predict_push.sh`、`scripts/push/lottery_review_push.sh`
- **14:30/14:35 降级为辅助任务**：即使失败也不影响 14:40 推送
- **文档同步**：README / CLAUDE.md / HERMES_CONFIG.md / PROJECT_REVIEW.md 全部同步 no_agent 审批说明

## v2.10.1 (2026-05-19)

- **推送链路加固**：Tirith glibc 兼容问题导致 cron 审批中断，4 个推送任务全部改为 no_agent=true
- **脚本化推送**：新建 `~/.hermes/scripts/lottery_predict_push.sh` / `lottery_review_push.sh`
- **不消耗 API token**：no_agent 模式无大模型调用，脚本直接运行并 stdout 交付飞书
- **crontab 方案讨论并否决**：详见 `docs/` 目录下相关记录

## v2.10.0 (2026-05-19)

- **两段式推送**：hermes_push 新增 predict(预测)/review(复盘)两种模式，下午推预测、晚间推复盘
- **compare_result 期号分类**：pred>actual → waiting_actual(exit 0，写 `*_waiting.json` 不覆盖 latest)；pred<actual 视为真错误(exit 2→v2.17 统一为 exit 2)
- **build_review_message 重写**：从"昨日复盘"改为"今日预测 vs 开奖直接对比"（v2.16 已改为"开奖复盘｜推送日"）
- **HERMES_CONFIG 6 cron job**：结构化配置清单，含故障恢复章节
- **push_state.json**：每期推送状态记录，多轮 cron 不重复轰炸

## v2.7.1 (2026-05-16)

- **Hermes cron 适配**：新增 `daily_review.py` 一键复盘脚本
- **compare_result 多策略对比**：支持 `--strategy` 参数
- **review_history.csv 增加策略列**：支持按策略分组复盘
- **backtest ROI 拆分**：直选/组选独立计算
- **data_fetcher 空数据保护**：`save_incremental()` 处理空数据场景

## v2.7 (2026-05-16)

- **复盘闭环**：compare_result → review_history.csv 累加 → review_summary 表现摘要
- **多策略权重**：scoring_weights_conservative.yaml / diversity.yaml + `run_daily --strategy all`
- **权重自动调优**：tune_weights.py（随机搜索 + Optuna TPE 贝叶斯优化 + 参数稳定性分析）
- **数据源加固**：东方财富福彩3D 接入(50条/页) + 双源校验 + fallback
- **工具链**：CLAUDE.md 项目指令 + Makefile + data_sources.yaml 配置外部化

## v2.6.1 (2026-05-15)

- **组三回归惩罚**：形态评分改为双向惩罚（过热降分、过冷加分）
- **API 567 退避重试**：fetch_pls() 限频 5s/10s/15s 递增等待
- **回测命中累加**：从 any()/elif 改为 sum() 累加 + 参数验证
- **PNG 中文字体**：matplotlib 自动探测系统中文字体
- **号码清洗**：normalize_number() 去空格/补零/剔除非数字
- **compare_result 输出优化**：开奖号码大字展示 + JSON 一句话摘要

## v2.6 (2026-05-15)

- **第二轮代码审查修复**：shell=True→列表参数、skiprows=0、删除 dead code
- **scoring_engine**：`generate_all()` 复用 feature_engine.add_features()，消除~60行重复
- **compare_result.py 新增**：预测 vs 开奖对比脚本
- **run_daily.py CLI 参数化**：--top-k / --exclude-recent，`ensure_seed_data()` 自动初始化
- **种子数据归档**：data/archived/pls_history.csv + d3_history.csv

## v2.5.1 (2026-05-15)

- **run_daily.py 新增**：一键每日运行脚本
- **福彩3D 数据源升级**：zhcw.com pd.read_html
- **feature_engine 兼容简洁 3 列 CSV**

## v2.5 (2026-05-15)

- **scoring_engine JSON 结构升级**：过滤说明改 object、代码版本字段
- **README 模式 A/B 说明**：--skiprows 3/2
- **.gitignore 放行 predictions/*.json**

## v2.4.1 (2026-05-15)

- **numpy 2.x 兼容**：np.char.add 修复
- **遗漏特征向量化**：20x 加速

## v2.4 (2026-05-15)

- **Plotly 交互可视化**：走势图/热力图 HTML 双格式

## v2.3 (2026-05-15)

- **generate_predictions() 抽取共用**：backtest 复用，删除 35 行重复
- **回测奖金区分组三(346元)/组六(173元)**
- **data_fetcher 重写 v2**：增量保存、日志系统、--days 参数

## v2.2 (2026-05-15)

- **P0/P1/P2 代码审查修复**：README 参数补全、回测组选判断修复、数据检查退出保护等
- **工程化**：.gitkeep、.gitattributes(LF换行符)

## v2.0 (2026-05-15)

- **评分引擎重大升级**：YAML 权重可配置、多样性惩罚（组选去重+跨度多样化）
- **冷号补偿**：阈值 6→冷号占比更大
- **data_fetcher 数据自动获取**

## v1.0 (2026-05-14)

- **初始版本**：基础评分引擎、特征工程、回测
