# Hermes 定时任务配置

> 此文件供 Hermes 读取并自动配置定时任务。修改此文件后，同步至 Hermes 平台生效。
> 最后更新：2026-05-22（v2.15.0：Job 架构改造 — shell 薄入口 + Python job 业务逻辑 + dedup_key 去重 + status.json）

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

### 三、定时任务（7 个任务）

> 所有推送类任务均为 no_agent=true 模式，绕过安全审批链。
> Shell 脚本为薄入口，调用 Python job 负责业务逻辑。
> 晚间复盘脚本在 23 点后自动启用 --final-check 兜底（无需传参）。
> KL8 复盘错开到 22:15 避免与 PLS/D3 同时跑。
> 修改项目 `scripts/push/` 后须手动 `cp` 到 `~/.hermes/scripts/`（软链接被 Hermes 拦截）。

```
# ── 下午预测链路（14:40 单一入口）──

[task-predict-push]
cron = 40 14 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/lottery_predict_push.sh
on_failure = continue
deliver = origin
no_agent = true
description = 排列三/福彩3D：下午预测生成并推送（自闭环：Job → run_daily → source_health → hermes_push）

# ── 晚间复盘链路（21:35 / 22:05 / 23:10 三波补偿）──

[task-review-2135]
cron = 35 21 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/lottery_review_push.sh
on_failure = continue
deliver = origin
no_agent = true
description = 复盘尝试1：两彩种齐全才推送，未齐静默（send_log+文件锁防重）

[task-review-2205]
cron = 05 22 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/lottery_review_push.sh
on_failure = continue
deliver = origin
no_agent = true
description = 复盘尝试2：两彩种齐全才推送，未齐静默（send_log+文件锁防重）

[task-review-2310]
cron = 10 23 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/lottery_review_push.sh --final
on_failure = continue
deliver = origin
no_agent = true
description = 复盘兜底：齐全推完整复盘，未齐推无法复盘通知

# ── 快乐8 KL8（14:50 预测 + 22:00 检查 + 22:15 复盘）──
# KL8 独立 push shell 脚本，不混入 PLS/D3 主流程

[task-kl8-predict-push]
cron = 50 14 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/kl8_predict_push.sh
on_failure = continue
deliver = origin
no_agent = true
description = 快乐8预测推送：自闭环 fetcher→predictor→stats→推送

[task-kl8-check]
cron = 0 22 * * *
command = cd /home/admin/bendi/lottery-analysis && .venv/bin/python scripts/kl8/check.py
on_failure = continue
deliver = local
description = 快乐8：全链路健康检查（非0 exit=异常）

[task-kl8-review-push]
cron = 15 22 * * *
command = cd /home/admin/bendi/lottery-analysis && bash scripts/push/kl8_review_push.sh
on_failure = continue
deliver = origin
no_agent = true
description = 快乐8复盘推送：自闭环 fetcher→reviewer→metrics→推送（错开22:05避免冲突）
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
下午（14:40）：预测推送
  └── lottery_predict_push.sh → lottery_predict_job.py（自闭环）
      ├── run_daily --strategy all --top-k 30
      ├── source_health
      └── hermes_push --mode predict --dedup-key predict:{date}:pls-{issue}:d3-{issue}

晚上（21:35 / 22:05 / 23:10）：复盘推送
  └── lottery_review_push.sh --stage normal|final
      └── lottery_review_job.py → daily_review + 开奖齐全判断 + hermes_push
          ├── normal: 两彩种未齐 → skipped_waiting，不推送
          ├── final: 未齐 → 推送兜底通知（dedup_key=review_missing:{date}）
          └── 齐全 → dedup_key = review:{date}:pls-{issue}:d3-{issue}

快乐8（独立模块）：
  14:50 → kl8_predict_push.sh → kl8_predict_job.py
          └── dedup_key = kl8_predict:{issue}
  22:00 → check.py → 全链路健康检查
  22:15 → kl8_review_push.sh → kl8_review_job.py
          └── 删旧文件 + 时间戳校验 + dedup_key = kl8_review:{issue}
```

**架构层次：**

```
Hermes / cron            → 定时触发
scripts/push/*.sh        → 薄入口：切目录、加锁、日志、启动 Python
scripts/jobs/*.py        → 业务编排：拉取、预测/复盘、状态判断、去重
scripts/hermes_push.py   → 推送内容生成 + 去重 + 发送
output/status/*.json     → 每次任务的状态记录
```

**核心改进：**

- 下午 14:40 单一 Job 入口，自闭环生成预测+推送
- 预测和复盘分开推送，不再混在同一条消息里
- 期号不再出现 "预测 26128 复盘 26127" 的混淆
- 晚间三波复盘自带防重复（send_log.jsonl + 文件锁），不会重复轰炸

---

## 定时任务清单

### 下午预测链路（14:40 单一入口）

#### 任务 1 — 14:40 预测生成并推送

```
时间: 14:40
命令: cd /home/admin/bendi/lottery-analysis && bash scripts/push/lottery_predict_push.sh
失败处理: 允许失败
deliver: origin
no_agent: true
说明: 自闭环 → lottery_predict_job.py 内部执行：
  1. run_daily.py --strategy all --top-k 30（数据抓取+特征+统计+三策略评分）
  2. source_health.py（健康报告）
  3. hermes_push.py --mode predict --dedup-key ...（推送）
  4. 写 output/status/lottery_predict_status.json
  dedup_key = predict:{date}:pls-{issue}:d3-{issue}
```

---

### 晚间复盘链路（21:35 / 22:05 / 23:10）

> 三段式补偿：数据源通常在 21:00 开奖后 20-30 分钟更新，三波覆盖延迟场景。
> 每波都跑 `daily_review.py && hermes_push.py --mode review`。
> **防重复**：`send_log.jsonl` + 文件锁 记录每期推送状态，同一期只推送一次。

#### 任务 4 — 21:35 复盘尝试

```
时间: 21:35
命令: bash scripts/push/lottery_review_push.sh（内部 --complete-only）
失败处理: 允许失败
deliver: origin
说明: 开奖后 35 分钟，两彩种齐全才推送复盘，未齐静默等待下一波
```

#### 任务 5 — 22:05 复盘尝试

```
时间: 22:05
命令: bash scripts/push/lottery_review_push.sh（内部 --complete-only）
失败处理: 允许失败
deliver: origin
说明: 距开奖 65 分钟，两彩种齐全才推送。若 21:35 已推送则 skip
```

#### 任务 6 — 23:10 复盘兜底

```
时间: 23:10
命令: bash scripts/push/lottery_review_push.sh --final（内部 --final-check）
失败处理: 允许失败
deliver: origin
说明: 最终兜底。齐全推完整复盘，未齐推"无法完成复盘"通知
```

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
