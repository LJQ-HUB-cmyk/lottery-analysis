# 彩票数据分析与预测系统（排列三 / 福彩3D / 快乐8）

基于**多窗口统计 + 理论分布 + 动态评分引擎**的彩票评分预测系统。排列三/福彩3D 对 1000 注号码多维度打分排序；快乐8 生成 20 码候选池（1-80 选 20）。

> ⚠️ **重要声明**：彩票开奖完全随机，本项目仅供学习、研究和娱乐参考。所有分析仅基于历史数据统计和理论分布，不代表未来开奖结果。请理性对待，量力而行。不保证任何命中率。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 一键运行（复盘 + 预测，开奖后执行）
python run_daily.py --mode all --strategy all

# 3. 查看可视化仪表板
python run_web.py
# 浏览器自动打开 http://127.0.0.1:8000
```

## 核心命令

```bash
# 复盘 + 预测（开奖后一条命令搞定）
python run_daily.py --mode all --strategy all --top-k 10

# 仅预测
python run_daily.py --mode predict --strategy all

# 仅复盘
python run_daily.py --mode review

# 单彩种
python run_daily.py pls --mode all
python run_daily.py d3 --mode all

# Web 仪表板
python run_web.py                    # 启动 → http://127.0.0.1:8000
python run_web.py --port 9000        # 指定端口
python run_web.py --no-open          # 不自动打开浏览器

# 静态 HTML 仪表板（备用）
python scripts/build_dashboard.py
```

## 项目结构

```
lottery-analysis/
├── run_daily.py                  # 一键每日运行入口（复盘+预测+命中率统计）
├── run_web.py                    # Web 仪表板启动器（FastAPI + ECharts）
├── scripts/
│   ├── data_fetcher.py           # 多源数据抓取（熔断 + 校验 + 隔离）
│   ├── feature_engine.py         # 特征工程（113维）+ 数据质量检查
│   ├── stats_engine.py           # 多窗口统计 + 理论分布
│   ├── scoring_engine.py         # 评分引擎（YAML权重 + 回归惩罚 + 多样性）
│   ├── enhanced_predictor.py     # 增强预测器（分位分析+和值区间+对子连号+热号池+动态权重）
│   ├── compare_result.py         # 预测 vs 开奖对比 + review_history累加
│   ├── review_summary.py         # 最近N期复盘表现摘要
│   ├── metrics.py                # 命中率统计（多维度+多窗口+趋势数据）
│   ├── backtest.py               # Walk-forward 回测（6策略对比 + ROI拆分）
│   ├── tune_scoring_params.py    # 权重自动调优（Optuna 贝叶斯优化）
│   ├── build_ensemble_predictions.py # 策略融合（共识投票加权预测）
│   ├── hermes_push.py            # 推送 CLI 入口（调用 push_formatter + push_sender）
│   ├── push_formatter.py         # 推送内容格式化（预测/复盘/KL8/健康报告）
│   ├── push_sender.py            # 多通道发送（飞书/微信/webhook）+ 去重 + 锁
│   ├── build_dashboard.py        # 静态 HTML 仪表板生成器（备用）
│   ├── kl8/                      # 快乐8独立模块
│   │   ├── fetcher.py            # 官方API抓取 + 校验
│   │   ├── predictor.py          # 20码池 + 选四主推
│   │   ├── reviewer.py           # 选四命中/盈亏复盘
│   │   ├── check.py              # 全链路健康检查（--stage predict/review/full）
│   │   ├── metrics.py            # 近N期累计成本/奖金/盈亏
│   │   ├── stats.py              # 奇偶/大小/连号/和值/冷热/全量遗漏
│   │   ├── backtest.py           # Walk-Forward 回测
│   │   └── compare_strategies.py # 多策略对比报告
│   ├── lib/
│   │   └── job_status.py         # 统一任务状态管理（TaskStatus 生命周期）
│   └── push/                     # Shell 薄入口脚本
│       ├── lottery_predict_push.sh
│       ├── lottery_review_push.sh
│       ├── kl8_predict_push.sh
│       ├── kl8_review_push.sh
│       └── kl8_check_push.sh
├── web/                          # Web 仪表板（FastAPI + Jinja2 + ECharts）
│   ├── main.py                   # FastAPI 入口 + 页面路由
│   ├── routes/                   # API 路由（pls/d3/kl8/backtest/metrics）
│   ├── templates/                # Jinja2 HTML 模板（深色主题）
│   └── static/                   # 静态资源
├── rules/
│   ├── scoring_weights.yaml              # 默认权重
│   ├── scoring_weights_conservative.yaml # 稳健策略
│   ├── scoring_weights_diversity.yaml    # 多样性策略
│   ├── scoring_weights_auto_pls.yaml     # 排列三自动调参权重
│   ├── scoring_weights_auto_d3.yaml      # 福彩3D自动调参权重
│   ├── prizes.yaml                       # 各彩种各玩法奖金配置
│   ├── strategy_registry.yaml            # 策略融合注册表
│   └── data_sources.yaml                 # 数据源配置
├── tests/                        # 单元测试（35个）
├── data/
│   ├── raw/                      # 原始CSV
│   ├── processed/                # 特征工程输出
│   ├── archived/                 # 种子数据
│   ├── cache/                    # 统计缓存 + 熔断状态
│   ├── kl8/                      # 快乐8历史数据
│   └── quarantine/               # 坏数据隔离区
├── output/
│   ├── predictions/              # 预测JSON（按期号+latest）
│   ├── reviews/                  # 复盘总表（review_history.csv）
│   ├── metrics/                  # 命中率统计JSON
│   ├── backtests/                # 回测报告
│   ├── charts/                   # 可视化图表
│   ├── reports/                  # 数据检查 + 对比报告
│   ├── push/                     # 推送日报 + 发送日志
│   ├── status/                   # 任务状态JSON
│   └── tuning/                   # 调参记录
├── CLAUDE.md                     # Agent 项目指令
├── CHANGELOG.md                  # 变更日志
└── requirements.txt              # 依赖清单
```

## Web 仪表板

```bash
python run_web.py    # → http://127.0.0.1:8000
```

| 页面 | 路径 | 内容 |
|------|------|------|
| 首页 | `/` | 命中率仪表盘 + 最新复盘 + Top10 预测 + 推送预览 |
| 排列三 | `/lottery/pls` | Top10 预测 + 复盘详情 + 误差趋势图 + 推送预览 |
| 福彩3D | `/lottery/d3` | 同上 |
| 快乐8 | `/kl8` | 选四主推 + 热号/冷号排行 + 累计盈亏 |
| 回测中心 | `/backtest` | 6 策略 walk-forward 结果 + ROI 对比图 |

API 端点：
```
GET /api/pls/predict, /api/d3/predict, /api/kl8/predict
GET /api/pls/review,  /api/d3/review,  /api/kl8/review
GET /api/metrics/pls, /api/metrics/d3
GET /api/metrics/pls/trend, /api/metrics/d3/trend
GET /api/backtest/pls, /api/backtest/d3, /api/backtest/kl8
```

## 命中率统计

```bash
python scripts/metrics.py                    # 生成命中率 JSON
python scripts/metrics.py --lottery pls      # 仅排列三
python scripts/metrics.py --windows 7,30,90  # 自定义时间窗口
```

输出 `output/metrics/{lottery}_metrics.json` 和 `{lottery}_trend.json`，Web 仪表板自动读取。

统计维度：
- 直选命中率 / 组选命中率
- 形态命中率 / 和值命中率 / 跨度命中率
- 胆码单中率 / 胆码双中率
- 平均和值差 / 平均跨度差

时间窗口：近 7 / 30 / 90 / 180 期

## 评分引擎

| 维度 | 默认权重 | 评分方式 |
|------|:--------:|----------|
| 和值 | 18 | 理论×60% + 近30期×40% × 过热衰减 |
| 跨度 | 15 | 同上 |
| 形态 | 16 | 理论回归惩罚（过热降分、过冷加分） |
| 奇偶 | 8 | 1-2个奇数=满分 |
| 大小 | 8 | 同上 |
| 012路 | 7 | 均衡=高分 |
| 冷热 | 10 | 0冷号+有热号=满分 |
| 遗漏 | 7 | 平均遗漏半值内=满分 |
| 多样性 | 10 | 组选重复扣分 + 跨度多样性加分 |

增强预测器额外维度：分位数字分析 + 和值区间过滤 + 对子/连号模式 + 热号池 + 动态权重。

## 回测

```bash
python scripts/backtest.py --lottery pls --periods 30 --top-k 10
```

自动发现并对比所有策略权重：随机 + 固定规则 + default + conservative + diversity + auto_tuned。

## 数据来源

| 彩种 | 源 | 方法 |
|------|-----|------|
| 排列三 | 体彩官方API | `data_fetcher.py` 自动拉取 |
| 福彩3D | 东方财富 | `data_fetcher.py` 自动拉取（主源） |
| 快乐8 | cwl.gov.cn | `kl8/fetcher.py` 自动拉取 |

## 开奖时间

| 彩种 | 官方开奖 | 建议拉取 |
|------|---------|---------|
| 排列三 | 每日 21:25 | 22:00 以后 |
| 福彩3D | 每日 21:15 | 22:00 以后 |
| 快乐8 | 每日 21:30 | 22:00 以后 |

## 风险提示

彩票开奖结果具有高度随机性。所有分析仅基于历史数据统计和理论分布，不代表未来开奖结果。请理性看待，不建议将分析结果作为实际投注依据。

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。
