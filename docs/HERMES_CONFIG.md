# Hermes 定时任务配置

> 此文件供 Hermes 读取并自动配置定时任务。修改此文件后，同步至 Hermes 平台生效。
> 最后更新：2026-06-05（v2.18.0：性能优化 + hermes_push 拆分 + KL8 完善 + 测试）

---

## ══════════════════════════════════════
## 👇 Hermes 配置清单（直接复制到 Hermes）
## ══════════════════════════════════════

### 一、环境变量

```
FEISHU_WEBHOOK_URL = （你的飞书机器人 webhook 地址）
```

> 飞书是主推送通道，不限频。不配则走 `--stdout` → Hermes `deliver=origin` 路径。

### 二、cron_mode

```
cron_mode = allow
```

### 三、定时任务（8 个任务）

> 所有推送类任务均为 no_agent=true 模式，绕过安全审批链。
> Hermes cron 包装脚本（`~/.hermes/scripts/*.sh`）通过 `scripts/push/` 下的 shell 薄入口调用 Python job，保留锁文件、日志、23点自动 final 等机制。
> 修改 `scripts/push/` 下的脚本后须手动 `cp` 到 `~/.hermes/scripts/`（软链接被 Hermes 拦截）。
> 晚间复盘单彩种独立推送：22:05 准备数据 → 22:10 PLS → 22:15 D3 → 22:20 KL8。
> 每条推送自带 `--final` 兜底（数据不齐时推送"无法复盘"通知）。
> 去重按彩种拆分：PLS/D3 各自独立 dedup_key，互不干扰。

```
# ── 下午预测链路（14:40 单一入口）──

[task-predict-push]
cron = 40 14 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/lottery_predict_push.sh
on_failure = continue
deliver = origin
no_agent = true
description = 排列三/福彩3D：下午预测生成并推送（自闭环：Job → run_daily → source_health → hermes_push）

# ── 晚间复盘链路（22:05 准备 → 22:10/22:15/22:20 单彩种独立推送）──

[task-review-prepare-2205]
cron = 05 22 * * *
command = bash ~/.hermes/scripts/lottery_review_prepare.sh
on_failure = continue
deliver = local
no_agent = true
description = 排列三/福彩3D：拉取开奖并生成复盘数据（不推送）

[task-review-pls-2210]
cron = 10 22 * * *
command = bash ~/.hermes/scripts/lottery_review_pls.sh
on_failure = continue
deliver = origin
no_agent = true
description = 排列三单独复盘推送（带Top30）；数据已齐推完整复盘，未齐推兜底通知

[task-review-d3-2215]
cron = 15 22 * * *
command = bash ~/.hermes/scripts/lottery_review_d3.sh
on_failure = continue
deliver = origin
no_agent = true
description = 福彩3D单独复盘推送（带Top30）；数据已齐推完整复盘，未齐推兜底通知

# ── 快乐8 KL8（14:50 预测 + 22:05 检查 + 22:20 复盘）──

[task-kl8-predict-push]
cron = 50 14 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/kl8_predict_push.sh
on_failure = continue
deliver = origin
no_agent = true
description = 快乐8预测推送：自闭环 fetcher→predictor→stats→推送

[task-kl8-check]
cron = 05 22 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/kl8_check_push.sh
on_failure = continue
deliver = origin
no_agent = true
description = 快乐8：全链路健康检查（异常时主动推送通知）

[task-kl8-review-push]
cron = 20 22 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/kl8_review_push.sh
on_failure = continue
deliver = origin
no_agent = true
description = 快乐8单独复盘推送，带完整候选池（错开PLS/D3推送时间）
```

---

## ══════════════════════════════════════
## 👆 以上是需要配置的全部内容
## ══════════════════════════════════════

---

## 环境变量

Hermes 执行环境需配置以下变量：

| 变量名 | 必填 | 通道 | 说明 |
|------|:--:|------|------|
| `FEISHU_WEBHOOK_URL` | 推荐 | **飞书（主通道）** | 飞书机器人 Webhook，不限频，优先使用 |
| `WECOM_WEBHOOK_URL` | 可选 | 微信（辅助通道） | 企业微信群机器人，有限频保护（冷却5s + 退避30/60/120s） |
| `HERMES_WEBHOOK_URL` | 可选 | 通用（兜底通道） | 通用 Webhook 地址 |

> 三个通道独立隔离，任一失败不影响其他。飞书为主通道（不限频），微信为辅助（带限频保护）。
> 都不配置时走 `--stdout` 模式，由 Hermes `deliver=origin` 负责推送。

---

## 两段式推送设计

```
下午（14:40 / 14:50）：预测推送
  ├── lottery_predict_push.sh → lottery_predict_job.py（自闭环）
  │     ├── run_daily --strategy all --top-k 30
  │     ├── source_health
  │     └── hermes_push --mode predict --dedup-key predict:{date}:pls-{issue}:d3-{issue}
  └── kl8_predict_push.sh → kl8_predict_job.py
        └── dedup_key = kl8_predict:{issue}

晚上（22:05 → 22:10 → 22:15 → 22:20）：单彩种独立复盘推送
  ├── 22:05 lottery_review_push.sh --prepare-only（拉取开奖+人工修正）
  ├── 22:10 lottery_review_push.sh --lottery pls --final（排列三复盘+Top30）
  ├── 22:15 lottery_review_push.sh --lottery d3 --final（福彩3D复盘+Top30）
  └── 22:20 kl8_review_push.sh（KL8复盘+候选池）
```

**架构层次：**

```
Hermes / cron            → 定时触发
~/.hermes/scripts/*.sh   → 包装脚本（no_agent 要求脚本在此目录）
scripts/push/*.sh        → 薄入口：切目录、加锁、日志、启动 Python
scripts/jobs/*.py        → 业务编排：拉取、预测/复盘、状态判断、去重
scripts/hermes_push.py   → CLI 入口（接口不变）
  scripts/push_formatter.py → 推送内容生成（新增）
  scripts/push_sender.py    → 去重 + 多通道发送（新增）
output/status/*.json     → 每次任务的状态记录
```

**核心改进：**

- 单彩种独立推送：PLS/D3/KL8 分开推送，不再等两彩种齐全
- 每条推送自带 `--final` 兜底，不需要单独的 23:10 任务
- dedup_key 按彩种拆分（`review:{date}:pls-{issue}`），互不干扰
- 锁和日志文件按彩种隔离，不会互相阻塞

---

## 文件依赖 → 详见 [../CLAUDE.md](../CLAUDE.md) 项目结构章节

---

## compare_result 期号不匹配分类

| 场景 | 返回状态 | exit code | 说明 |
|------|------|:--:|------|
| `pred > actual` | `waiting_actual` | 0 | 等待数据源更新，不算错误 |
| `pred < actual` | `错误` | 2 | 缺预测文件，真问题 |
| `pred == actual` | 正常复盘 | 0 | 写入 review_history |

> `waiting_actual` 时写入 `*_compare_waiting.json`，不覆盖 `*_compare_latest.json`。

---

## 本次更新（v2.18.0）服务器部署步骤

### 必做步骤（2 步）

```bash
# 1. 拉取最新代码
cd /home/admin/bendi/lottery-analysis
git pull

# 2. 同步 shell 脚本到 Hermes 目录
cp scripts/push/*.sh ~/.hermes/scripts/
```

**完成。** 以上两步即可运行。cron 任务配置不变，无需修改 Hermes 平台。

### 可选验证（推荐）

```bash
# 3. 安装 pytest（仅用于本地测试，不影响 cron 运行）
.venv/bin/pip install pytest

# 4. 验证新模块可导入
.venv/bin/python -c "from scripts.push_formatter import build_predict_message; print('OK')"
.venv/bin/python -c "from scripts.push_sender import send_or_save; print('OK')"

# 5. 跑测试
.venv/bin/python -m pytest tests/ -q

# 6. 跑一次主流程（不推送，仅验证）
.venv/bin/python run_daily.py pls --top-k 5

# 7. KL8 健康检查
PYTHONUTF8=1 .venv/bin/python scripts/kl8/check.py
```

### 不需要做的事

| 项目 | 原因 |
|------|------|
| 不需要改 cron 任务 | 8 个任务配置不变，shell 脚本路径不变 |
| 不需要装新依赖 | 无新增 pip 包，`requirements.txt` 不变 |
| 不需要重新调参 | `scoring_weights_auto_*.yaml` 已存在，权重微调在 YAML 中手动改 |
| 不需要改环境变量 | `FEISHU_WEBHOOK_URL` 等不变 |
| 不需要重跑数据 | 现有 raw/processed/cache 数据继续用 |
| 不需要改 venv | Python 3.11+ 已满足所有语法要求 |

### v2.18.0 新增/变更文件

| 文件 | 状态 | 说明 |
|------|:----:|------|
| `scripts/push_formatter.py` | **新增** | 推送内容格式化（从 hermes_push 拆出） |
| `scripts/push_sender.py` | **新增** | 多通道发送+去重+锁（从 hermes_push 拆出） |
| `scripts/hermes_push.py` | **重写** | 薄 CLI 入口，调用上述两个模块（CLI 接口不变） |
| `scripts/kl8/backtest.py` | **新增** | KL8 walk-forward 回测 |
| `scripts/kl8/compare_strategies.py` | **新增** | KL8 多策略对比 |
| `scripts/patch_pls_dates.py` | **新增** | PLS 历史日期补全工具 |
| `rules/prizes.yaml` | **新增** | 各彩种奖金配置（backtest/reviewer 从此读取） |
| `tests/` | **新增** | 35 个单元测试 |
| `rules/scoring_weights*.yaml` | **修改** | 形态权重/过热衰减/跨度分散参数微调 |
| `scripts/kl8/check.py` | **修改** | 新增 `--stage` 参数 + 期号比较逻辑修复 |
| `scripts/kl8/predictor.py` | **修改** | 新增 `--zone-balance` + `duration_ms` |
| `scripts/kl8/metrics.py` | **修改** | 新增加权命中分 |
| `scripts/kl8/stats.py` | **修改** | 新增全量 80 号码遗漏表 |
| `scripts/data_fetcher.py` | **修改** | 新增 `--verify-backup` 参数 |
| `scripts/compare_result.py` | **修改** | 期号类型统一 + `__len__` 修复 |

### 兼容性说明

> `hermes_push.py` 已重写为薄入口——实际逻辑拆到了 `push_formatter.py` 和 `push_sender.py`。
> 但 **CLI 接口完全不变**（`--mode predict/review`、`--lottery`、`--stdout`、`--force`、`--dedup-key` 等参数全保留），
> 所以所有 shell 脚本和 Python job 的调用方式不需要改。

---

## 历史部署记录

### v2.17.0（2026-05-25）

```bash
cd /home/admin/bendi/lottery-analysis && git pull
cp scripts/push/*.sh ~/.hermes/scripts/
# 生成 auto_tuned 权重（只需跑一次）
.venv/bin/python scripts/tune_scoring_params.py --lottery pls --trials 80 --periods 120 --train-window 150
.venv/bin/python scripts/tune_scoring_params.py --lottery d3 --trials 80 --periods 120 --train-window 150
ls -l rules/scoring_weights_auto_*.yaml
.venv/bin/python scripts/audit_lottery_data.py --lottery all
```

### v2.16.0（2026-05-24）

| 旧任务 | 新任务 | 变化 |
|------|------|------|
| task-review-2135 (21:35) | **删除** | 三波补偿废弃 |
| task-review-2205 (22:05) | task-review-prepare-2205 | 改为 prepare-only（只拉数据不推送） |
| — | task-review-pls-2210 (22:10) | **新增**：排列三独立复盘 |
| — | task-review-d3-2215 (22:15) | **新增**：福彩3D独立复盘 |
| task-review-2310 (23:10) | **删除** | 每条推送自带 --final 兜底 |
| task-kl8-review-push (22:15) | task-kl8-review-push (22:20) | 时间错开 5 分钟 |
| task-kl8-check (22:00) | task-kl8-check (22:05) | 改为 no_agent/origin |
