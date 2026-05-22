# lottery-analysis Makefile
# 用法: make <target>
# Windows 用户: Git Bash 自带 make，或在 PowerShell 中使用对应 python 命令

LOTTERY ?= pls
TOP_K  ?= 30
STRATEGY ?= default

.PHONY: daily daily-review backtest compare review tune chart clean \
        kl8-fetch kl8-predict kl8-review kl8-metrics kl8-check \
        review-normal review-final \
        push-predict push-review push-kl8-predict push-kl8-review \
        help

## ── 排列三 / 福彩3D ──

## 每日预测（Hermes 14:40 自闭环推送也会执行）
daily:
	python run_daily.py --top-k $(TOP_K) --strategy $(STRATEGY)

## 每日复盘（Hermes 21:35/22:05/23:10 调用）
daily-review:
	python scripts/daily_review.py

## 晚间复盘 Job（--stage normal：两彩种齐全才推送）
review-normal:
	python scripts/jobs/lottery_review_job.py --stage normal

## 晚间复盘 Job（--stage final：不齐也推送兜底通知）
review-final:
	python scripts/jobs/lottery_review_job.py --stage final

## Walk-forward 回测
backtest:
	python scripts/backtest.py --lottery $(LOTTERY) --periods 100 --top-k $(TOP_K)

## 预测 vs 开奖对比
compare:
	python scripts/compare_result.py --lottery $(LOTTERY)

## 复盘表现摘要
review:
	python scripts/review_summary.py

## 权重自动调优（需 review_history >= 15 期）
tune:
	python scripts/tune_weights.py --lottery $(LOTTERY) --trials 30 --periods 50

## 可视化（HTML 交互图）
chart:
	python scripts/visualize.py --lottery $(LOTTERY) --chart all --output-format html

## ── 快乐8（KL8）──

## 拉取 KL8 历史数据
kl8-fetch:
	python scripts/kl8/fetcher.py --pages 3

## 生成 KL8 预测（20码池 + 选四主推）
kl8-predict:
	python scripts/kl8/predictor.py

## KL8 复盘（选四命中 + 盈亏）
kl8-review:
	python scripts/kl8/reviewer.py

## KL8 累计表现
kl8-metrics:
	python scripts/kl8/metrics.py

## KL8 全链路健康检查
kl8-check:
	python scripts/kl8/check.py

## ── 推送（Hermes cron no_agent 模式）──

## 预测推送（自闭环：run_daily → health → push）
push-predict:
	bash scripts/push/lottery_predict_push.sh

## 复盘推送（自闭环：daily_review → push）
push-review:
	bash scripts/push/lottery_review_push.sh

## KL8 预测推送（自闭环：fetcher → predictor → stats → push）
push-kl8-predict:
	bash scripts/push/kl8_predict_push.sh

## KL8 复盘推送（自闭环：fetcher → reviewer → metrics → push）
push-kl8-review:
	bash scripts/push/kl8_review_push.sh

## ── 工具 ──

## 清理输出文件
clean:
	@echo "清理 output/ 下的预测和图表..."
	rm -rf output/predictions/*.json
	rm -rf output/charts/*
	rm -rf output/backtests/*
	rm -rf output/tuning/*
	@echo "完成"

help:
	@echo "用法: make <target> [LOTTERY=pls|d3] [TOP_K=30] [STRATEGY=default|conservative|diversity|all]"
	@echo ""
	@echo "── 排列三/福彩3D ──"
	@echo "  make daily           每日预测"
	@echo "  make daily-review    每日复盘"
	@echo "  make review-normal   晚间复盘（normal阶段）"
	@echo "  make review-final    晚间复盘（final阶段）"
	@echo "  make backtest        Walk-forward 回测"
	@echo "  make compare         预测 vs 开奖对比"
	@echo "  make review          复盘表现摘要"
	@echo "  make tune            权重自动调优"
	@echo "  make chart           可视化图表"
	@echo ""
	@echo "── 快乐8 ──"
	@echo "  make kl8-fetch       拉取历史数据"
	@echo "  make kl8-predict     生成预测"
	@echo "  make kl8-review      复盘"
	@echo "  make kl8-metrics     累计表现"
	@echo "  make kl8-check       健康检查"
	@echo ""
	@echo "── 推送 ──"
	@echo "  make push-predict        预测推送"
	@echo "  make push-review         复盘推送"
	@echo "  make push-kl8-predict    KL8预测推送"
	@echo "  make push-kl8-review     KL8复盘推送"
	@echo ""
	@echo "  make clean           清理输出文件"
	@echo ""
	@echo "示例:"
	@echo "  make daily LOTTERY=pls TOP_K=10 STRATEGY=conservative"
	@echo "  make backtest LOTTERY=d3 TOP_K=30"
