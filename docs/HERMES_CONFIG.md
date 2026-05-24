# Hermes 定时任务配置

> 此文件供 Hermes 读取并自动配置定时任务。修改此文件后，同步至 Hermes 平台生效。
> 最后更新：2026-05-24（v2.16.0：单彩种独立推送 + 包装脚本通过薄入口调用）

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
scripts/hermes_push.py   → 推送内容生成 + 去重 + 发送
output/status/*.json     → 每次任务的状态记录
```

**核心改进：**

- 单彩种独立推送：PLS/D3/KL8 分开推送，不再等两彩种齐全
- 每条推送自带 `--final` 兜底，不需要单独的 23:10 任务
- dedup_key 按彩种拆分（`review:{date}:pls-{issue}`），互不干扰
- 锁和日志文件按彩种隔离，不会互相阻塞

---

## 手动命令参考

### 推送相关

```bash
# 推送预测
python scripts/hermes_push.py --mode predict

# 推送复盘
python scripts/hermes_push.py --mode review

# 强制补发（忽略去重）
python scripts/hermes_push.py --mode predict --force
python scripts/hermes_push.py --mode review --force

# 只生成不推送（检查内容）
python scripts/hermes_push.py --mode predict --write-only
python scripts/hermes_push.py --mode review --write-only

# 旧版混合日报（兼容）
python scripts/hermes_push.py --mode daily
```

### 复盘相关

```bash
# 手动复盘
python scripts/daily_review.py
python scripts/daily_review.py --lottery pls
python scripts/daily_review.py --lottery d3

# 单测 compare_result（按实际开奖期号查找对应预测）
python scripts/compare_result.py --lottery pls --strategy default
python scripts/compare_result.py --lottery d3 --strategy conservative
```

### 预测相关

```bash
python run_daily.py --strategy all --top-k 30
python run_daily.py pls --strategy all --top-k 30
```

### 数据源诊断

```bash
python scripts/source_health.py
python scripts/source_health.py --json --output output/reports/source_health.json
python scripts/data_fetcher.py --cb-status
```

---

## 文件依赖关系

### predict 模式读取

| 文件 | 来源 | 内容 |
|------|------|------|
| `output/predictions/latest_pls.json` | `run_daily.py` | 排列三默认策略预测 |
| `output/predictions/latest_pls_conservative.json` | `run_daily.py` | 排列三稳健策略预测 |
| `output/predictions/latest_pls_diversity.json` | `run_daily.py` | 排列三多样性策略预测 |
| `output/predictions/latest_d3.json` | `run_daily.py` | 福彩3D默认策略预测 |
| `output/predictions/latest_d3_conservative.json` | `run_daily.py` | 福彩3D稳健策略预测 |
| `output/predictions/latest_d3_diversity.json` | `run_daily.py` | 福彩3D多样性策略预测 |
| `output/reports/source_health.json` | `source_health.py` | 数据源健康报告 |
| `data/cache/{lottery}_stats_latest.json` | `stats_engine.py` | 统计缓存（冷热/和值/跨度） |

### review 模式读取

| 文件 | 来源 | 内容 |
|------|------|------|
| `output/reviews/review_history.csv` | `daily_review.py` | 复盘记录（含命中范围/号码/排名 + Top5直选/组选） |
| `output/reports/{lottery}_compare_latest.json` | `compare_result.py` | 最新对比结果 |
| `output/reports/{lottery}_compare_waiting.json` | `compare_result.py` | 等待状态（pred > actual） |
| `output/reports/source_health.json` | `source_health.py` | 健康报告 |

### 快乐8 (KL8) 模式读取

| 文件 | 来源 | 内容 |
|------|------|------|
| `data/kl8/kl8_history.csv` | `kl8_fetcher.py` | 历史开奖数据 |
| `data/kl8/kl8_latest.json` | `kl8_fetcher.py` | 最新一期开奖 |
| `output/kl8/kl8_predict_latest.json` | `kl8_predictor.py` | 20码候选池预测 |
| `output/kl8/kl8_review_latest.json` | `kl8_reviewer.py` | 候选池vs开奖复盘 |
| `output/kl8/kl8_review_history.csv` | `kl8_reviewer.py` | 复盘历史累加 |

### 推送脚本写入

| 文件 | 用途 |
|------|------|
| `output/push/predict_report.md` | 预测日报落盘 |
| `output/push/review_report.md` | 复盘日报落盘 |
| `output/push/daily_report.md` | 旧版混合日报落盘（兼容） |
| `output/push/pending_*_report.md` | 推送失败时待补发的内容 |
| `output/push/send_log.jsonl` | 发送记录（逐行 JSON，含 dedup_key 业务键 + hash 去重） |
| `output/push/push_state.json` | 期号级防重状态（按 `日期_模式` 记录） |
| `output/status/kl8_review.json` | KL8 复盘状态 |
| `output/status/kl8_predict.json` | KL8 预测状态 |
| `output/status/lottery_review.json` | PLS/D3 复盘状态 |
| `output/status/lottery_predict.json` | PLS/D3 预测状态 |

---

## compare_result 期号不匹配分类

| 场景 | 返回状态 | exit code | 说明 |
|------|------|:--:|------|
| `pred > actual` | `waiting_actual` | 0 | 等待数据源更新，不算错误 |
| `pred < actual` | `错误` | 1 | 缺预测文件，真问题 |
| `pred == actual` | 正常复盘 | 0 | 写入 review_history |

> `waiting_actual` 时写入 `*_compare_waiting.json`，不覆盖 `*_compare_latest.json`。

---

## 关键设计原则

1. **两段式推送** — 预测单独推，复盘单独推，期号语义清晰无混淆
2. **预测按期号归档** — `*_predict_{issue}.json` 持久化，复盘按实开期号查找对应预测
3. **防重复推送** — `send_log.jsonl` 业务键（dedup_key）去重 + 文件锁，同一期号同日不重复推送。dedup_key 按期号计算，不受推送文本微小变化影响
4. **失败隔离** — 复盘失败不阻塞预测，健康报告失败不阻塞推送
5. **落盘优先** — 先写 `*_report.md` 再推送，推送失败内容不丢
6. **指数冷却** — sporttery API 连续失败后冷却 2h→6h→12h→24h
7. **stdout 隔离** — `--stdout` 模式只输出正文到 stdout，日志/警告全部走 stderr
8. **统一退出码** — 0=正常（含等待开奖/已推送跳过），2=业务异常（阻断推送），3=环境异常（venv缺失等）
9. **Shell 薄入口** — 脚本只负责 cd/加锁/启动 Python/写日志，不做业务判断
10. **状态可追踪** — 每个任务写 `output/status/*.json`，含 status/dedup_key/issues/reason

---

## 故障恢复

### 预测推送失败

预测日报已落盘到 `output/push/predict_report.md`。手动补发：

```bash
python scripts/hermes_push.py --mode predict --force
```

### 复盘推送失败

复盘日报已落盘到 `output/push/review_report.md`。手动补发：

```bash
python scripts/hermes_push.py --mode review --force
```

### 晚间复盘自动跳过（预期行为）

若 compare_result JSON 状态为 `waiting_actual`，hermes_push --mode review 会自动跳过推送并输出日志：

```
[跳过] 全部等待开奖（pls 预测期号 > 实际开奖期号...）
```

这是正常行为，不需要任何操作。等数据源更新后下一波 cron 会自动补推。

### Gateway 关闭后恢复

1. 重启 Hermes gateway
2. 确认 `cron_mode = allow`
3. 手动补跑当天缺失的关键任务：
   ```bash
   # 如果下午预测没生成
   python run_daily.py --strategy all --top-k 30
   python scripts/hermes_push.py --mode predict --force
   
   # 如果晚间复盘没跑
   python scripts/daily_review.py
   python scripts/hermes_push.py --mode review --force
   ```

---

## Python 环境约定

> 本项目正式运行环境统一使用 `.venv/bin/python`，**禁止**直接调用系统 `python` 或 `python3`。

### 执行路径

```
Hermes cron (no_agent)
  → scripts/push/*.sh（薄入口 shell 脚本）
    → .venv/bin/python scripts/jobs/*.py（业务逻辑）
```

Hermes 配置中的 command 只写 `bash scripts/push/*.sh`，不允许直接写 `python run_daily.py` 或 `python scripts/jobs/*.py`。

### 环境文件

| 目录 | 用途 | 状态 |
|:-----|:-----|:----:|
| `.venv/` | 正式 Hermes 运行环境（uv 创建） | ✅ 正式 |
| `venv/` | 临时测试环境（pip 创建） | ⚠️ 待清理 |

### 新增依赖

`.venv` 由 uv 管理（无普通 pip），服务器 PyPI 官方源可能不可用。新增依赖统一使用：

```bash
cd /home/admin/bendi/lottery-analysis
uv pip install --python .venv/bin/python 包名 \
  --index-url https://mirrors.aliyun.com/pypi/simple/
```

#### 示例

```bash
# 安装 packages
uv pip install --python .venv/bin/python beautifulsoup4 \
  --index-url https://mirrors.aliyun.com/pypi/simple/

# 检查已安装
uv pip list --python .venv/bin/python
```

### 故障恢复（手动执行）

如果 Hermes cron 未触发，需手动补跑时执行：

```bash
# 预测
cd /home/admin/bendi/lottery-analysis
.venv/bin/python scripts/jobs/lottery_predict_job.py

# 复盘
cd /home/admin/bendi/lottery-analysis
.venv/bin/python scripts/jobs/lottery_review_job.py

# 强制推送（绕过 dedup）
.venv/bin/python scripts/hermes_push.py --mode predict --force

# KL8
.venv/bin/python scripts/jobs/kl8_predict_job.py
.venv/bin/python scripts/jobs/kl8_review_job.py
```

**禁止**用系统 `python` 执行——系统环境无依赖，会报 `ModuleNotFoundError`。

`hermes_push.py` 已内置冷却和退避。如果仍然限频：
- 改用飞书作为主通道（配置 `FEISHU_WEBHOOK_URL`）
- 或只用 `--stdout` → `deliver=origin` 路径
