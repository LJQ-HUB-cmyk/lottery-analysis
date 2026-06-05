#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
彩票数据获取器 —— 排列三 & 福彩3D
===================================
多源优先级 + 熔断 + 校验 + 隔离

数据源:
  排列三: js-lottery.com (primary) → sporttery.cn API (backup, 带熔断)
  福彩3D: eastmoney.com (primary) → zhcw.com (verify, 带熔断)

用法:
    python data_fetcher.py --all              # 获取所有彩种
    python data_fetcher.py --lottery pls      # 仅排列三
    python data_fetcher.py --lottery d3       # 仅福彩3D
    python data_fetcher.py --all --days 30    # 获取最近30期
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

try:
    from issue_utils import validate_issue
except ImportError:
    from scripts.issue_utils import validate_issue

# ==========================================
#  日志
# ==========================================

LOG_DIR = Path(__file__).resolve().parent.parent / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_DIR / 'data_fetcher.log'), encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ==========================================
#  路径
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / 'data' / 'raw'
RAW_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = BASE_DIR / 'data' / 'cache'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR = BASE_DIR / 'data' / 'quarantine'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/134.0.0.0 Safari/537.36',
}


# ==========================================
#  熔断器
# ==========================================

class CircuitBreaker:
    """管理数据源健康状态，连续失败后自动冷却"""

    STATUS_FILE = CACHE_DIR / 'source_status.json'

    def __init__(self):
        self._status = self._load()

    def _load(self):
        if self.STATUS_FILE.exists():
            try:
                with open(self.STATUS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, ValueError):
                logger.warning("source_status.json 损坏，重建")
        return {}

    def _save(self):
        with open(self.STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self._status, f, ensure_ascii=False, indent=2)

    def should_skip(self, source_name, max_failures=3, cooldown_minutes=120):
        """返回 True 表示应跳过该源（冷却中）"""
        item = self._status.get(source_name, {})
        fails = item.get('consecutive_failures', 0)
        cooldown_str = item.get('cooldown_until')

        # 未达失败阈值 → 不跳过
        if fails < max_failures:
            return False

        # 达到阈值但无冷却时间 → 自动设置冷却
        if not cooldown_str:
            cooldown_until = datetime.now() + timedelta(minutes=cooldown_minutes)
            item['cooldown_until'] = cooldown_until.strftime("%Y-%m-%d %H:%M:%S")
            self._status[source_name] = item
            self._save()
            logger.info("🔒 {} 连续失败{}次，冷却 {} 分钟至 {}".format(
                source_name, fails, cooldown_minutes,
                cooldown_until.strftime("%H:%M")))
            return True

        # 检查冷却是否到期
        try:
            cooldown_until = datetime.strptime(cooldown_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() >= cooldown_until:
                # 冷却到期，自动重置
                item['consecutive_failures'] = 0
                item['cooldown_until'] = None
                self._status[source_name] = item
                self._save()
                logger.info("🔓 {} 冷却到期，恢复使用".format(source_name))
                return False
            remaining = (cooldown_until - datetime.now()).total_seconds()
            logger.info("🔒 {} 冷却中，剩余 {} 分钟".format(source_name, int(remaining / 60)))
            return True
        except (ValueError, TypeError):
            return False

    def record_success(self, source_name):
        """记录成功，清零所有计数（包括冷却轮次）"""
        self._status[source_name] = {
            'consecutive_failures': 0,
            'cooldown_round': 0,
            'last_success': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'last_failure': self._status.get(source_name, {}).get('last_failure'),
            'cooldown_until': None,
            'last_status': 200,
        }
        self._save()

    def _calc_cooldown(self, base_minutes, cooldown_round):
        """指数冷却：2h→6h→12h→24h(max)"""
        return min(24 * 60, base_minutes * (2 ** cooldown_round))

    def record_failure(self, source_name, status_code=None, max_failures=3,
                       cooldown_minutes=120):
        """记录失败，达阈值时设置冷却（指数递增）"""
        item = self._status.get(source_name, {})
        fails = item.get('consecutive_failures', 0) + 1
        cooldown_round = item.get('cooldown_round', 0)
        now = datetime.now()

        entry = {
            'consecutive_failures': fails,
            'last_failure': now.strftime("%Y-%m-%d %H:%M:%S"),
            'last_success': item.get('last_success'),
            'last_status': status_code,
            'cooldown_until': item.get('cooldown_until'),
            'cooldown_round': cooldown_round,
        }

        if fails >= max_failures:
            entry['cooldown_round'] = cooldown_round + 1
            actual_cooldown = self._calc_cooldown(cooldown_minutes, cooldown_round)
            cooldown_until = now + timedelta(minutes=actual_cooldown)
            entry['cooldown_until'] = cooldown_until.strftime("%Y-%m-%d %H:%M:%S")
            if cooldown_round > 0:
                logger.warning("🔒 {} 第{}轮冷却，{} 分钟（指数递增）至 {}".format(
                    source_name, cooldown_round + 1, actual_cooldown,
                    cooldown_until.strftime("%H:%M")))
            else:
                logger.warning("🔒 {} 连续失败{}次，冷却 {} 分钟至 {}".format(
                    source_name, fails, actual_cooldown,
                    cooldown_until.strftime("%H:%M")))

        self._status[source_name] = entry
        self._save()

    def print_status(self):
        """打印所有源的状态摘要"""
        if not self._status:
            logger.info("📊 无熔断记录")
            return
        logger.info("📊 数据源状态:")
        for name, item in self._status.items():
            fails = item.get('consecutive_failures', 0)
            cd = item.get('cooldown_until', '无')
            rnd = item.get('cooldown_round', 0)
            last = item.get('last_success') or item.get('last_failure') or '无'
            if cd and cd != '无':
                state = '🔒'
                extra = ' 第{}轮'.format(rnd) if rnd > 1 else ''
            else:
                state = '✅'
                extra = ''
            logger.info("  {} {} 失败{}次{} 最后:{}".format(state, name, fails, extra, last))


# ==========================================
#  排列三 —— sporttery.cn API (backup)
# ==========================================

def fetch_pls(limit=30, max_retries=2):
    """从体彩官方API获取排列三最新数据，567限频退避 + jitter"""
    # 随机UA轮换降低指纹
    ua_list = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
    ]
    headers = dict(HEADERS)
    headers['User-Agent'] = random.choice(ua_list)

    url = (
        "https://webapi.sporttery.cn/gateway/lottery/"
        f"getHistoryPageListV1.qry?gameNo=350133&provinceId=0"
        f"&pageSize={min(limit, 5)}&is498=1"
    )
    delays = [30, 90]  # 重试间隔

    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 567:
                if attempt < max_retries - 1:
                    wait = delays[attempt] + random.randint(3, 20)
                    logger.warning("排列三API返回567(限频)，{}秒后重试({}/{})".format(
                        wait, attempt + 1, max_retries))
                    time.sleep(wait)
                    continue
                logger.error("排列三API: {}次重试后仍567".format(max_retries))
                return []
            r.raise_for_status()
            data = r.json()
            break
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(delays[attempt])
                continue
            logger.error("排列三API请求失败: {}".format(e))
            return []
        except (ValueError, KeyError) as e:
            logger.error("排列三数据解析失败: {}".format(e))
            return []
    else:
        logger.error("排列三API: {}次重试后仍失败".format(max_retries))
        return []

    results = []
    for item in data.get('value', {}).get('list', []):
        nums = item['lotteryDrawResult'].split()
        if len(nums) < 3:
            logger.warning("排列三: 期号{} 号码格式异常: {}".format(
                item['lotteryDrawNum'], item['lotteryDrawResult']))
            continue
        results.append({
            '期号': item['lotteryDrawNum'],
            '日期': item['lotteryDrawTime'],
            '号码': ''.join(nums[:3]),
        })
    if results:
        logger.info("排列三(sporttery): 获取到 {} 条 (最新: {})".format(
            len(results), results[0]['期号']))
    else:
        logger.warning("排列三(sporttery): 无数据")
    return results


# ==========================================
#  排列三 —— js-lottery.com (primary)
# ==========================================

def fetch_pls_from_js_lottery(limit=30):
    """从江苏体彩网抓取排列三历史数据"""
    url = "https://www.js-lottery.com/wfzq/p3p5/p3data"
    logger.info("排列三(js-lottery): 开始抓取...")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = 'utf-8'
        if resp.status_code != 200:
            logger.error("排列三(js-lottery): HTTP {}".format(resp.status_code))
            return []
    except requests.exceptions.RequestException as e:
        logger.error("排列三(js-lottery): 请求失败 {}".format(e))
        return []

    # 用 pd.read_html 解析
    try:
        dfs = pd.read_html(StringIO(resp.text))
    except (ValueError, ImportError) as e:
        logger.error("排列三(js-lottery): HTML解析失败 {}".format(e))
        # fallback: 简单正则
        return _parse_pls_js_lottery_fallback(resp.text, limit)

    for df in dfs:
        cols = [str(c).strip() for c in df.columns]
        # 弹性匹配列名
        issue_col = next((c for c in cols if '期号' in c), None)
        num_col = next((c for c in cols if '开奖号码' in c or '号码' in c or '奖号' in c), None)
        date_col = next((c for c in cols if '日期' in c or '发布' in c), None)

        if issue_col and num_col:
            results = []
            for _, row in df.iterrows():
                issue = str(row[issue_col]).strip()
                number = str(row[num_col]).strip().replace(' ', '')
                # 期号校验：5位纯数字
                if not issue.isdigit() or len(issue) != 5:
                    continue
                # 号码校验：3位数字
                if not number.isdigit() or len(number) < 3:
                    number = ''.join(c for c in number if c.isdigit())[:3]
                if len(number) != 3:
                    continue
                date_val = str(row[date_col]).strip() if date_col else ''
                results.append({
                    '期号': issue,
                    '日期': date_val,
                    '号码': number,
                })
                if len(results) >= limit:
                    break

            if results:
                logger.info("排列三(js-lottery): 获取到 {} 条 (最新: {})".format(
                    len(results), results[0]['期号']))
                return results

    # pd.read_html 没找到 → fallback
    return _parse_pls_js_lottery_fallback(resp.text, limit)


def _parse_pls_js_lottery_fallback(html, limit):
    """js-lottery 备用解析：正则提取"""
    import re
    # 匹配表格行：日期 | 期号 | 号码
    rows = re.findall(r'<tr[^>]*>.*?(\d{4}-\d{2}-\d{2}).*?(\d{5}).*?(\d\s*\d\s*\d).*?</tr>',
                      html, re.DOTALL)
    results = []
    for date_str, issue, number in rows:
        num = number.replace(' ', '')
        if len(num) == 3 and num.isdigit():
            results.append({'期号': issue, '日期': date_str, '号码': num})
            if len(results) >= limit:
                break
    if results:
        logger.info("排列三(js-lottery fallback): 解析到 {} 条".format(len(results)))
    else:
        logger.warning("排列三(js-lottery fallback): 未解析到数据")
    return results


# ==========================================
#  福彩3D —— zhcw.com (verify)
# ==========================================

def fetch_3d_from_zhcw(max_pages=10):
    """
    从中国福彩网(zhcw.com)抓取福彩3D历史数据

    使用 pd.read_html 解析静态表格。
    """
    all_dfs = []
    logger.info("福彩3D(zhcw): 最多 {} 页...".format(max_pages))

    for page in range(1, max_pages + 1):
        url = "http://kaijiang.zhcw.com/zhcw/html/3d/list_{}.html".format(page)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.encoding = 'utf-8'

            if resp.status_code != 200:
                continue

            dfs = pd.read_html(StringIO(resp.text))
            found = False
            for df in dfs:
                cols = df.columns
                col_strs = []
                if hasattr(cols, 'levels'):
                    for level in cols.levels:
                        col_strs.extend(str(c) for c in level)
                else:
                    col_strs = [str(c) for c in cols]

                if any('期号' in s for s in col_strs):
                    df = df.iloc[:, :3].copy()
                    df.columns = ['开奖日期', '期号', '中奖号码']
                    df['中奖号码'] = df['中奖号码'].astype(str).str.replace(' ', '').str.zfill(3)
                    df = df[df['期号'].astype(str).str.match(r'^\d{6,7}$')]
                    if len(df) > 0:
                        all_dfs.append(df)
                        logger.info("福彩3D(zhcw): 第 {} 页 -> {} 条".format(page, len(df)))
                    found = True
                    break

            if not found:
                logger.debug("福彩3D(zhcw): 第 {} 页未找到表格".format(page))

        except (requests.exceptions.RequestException, ValueError) as e:
            logger.debug("福彩3D(zhcw): 第 {} 页失败 {}".format(page, e))

        time.sleep(1.5)

    if not all_dfs:
        logger.error("福彩3D(zhcw): 所有页面抓取失败")
        return None

    final_df = pd.concat(all_dfs, ignore_index=True)
    final_df = final_df.drop_duplicates(subset=['期号']).sort_values(
        by='期号', ascending=False).reset_index(drop=True)

    logger.info("福彩3D(zhcw): 共 {} 条 ({} ~ {})".format(
        len(final_df), final_df['期号'].iloc[-1], final_df['期号'].iloc[0]))
    return final_df


# ==========================================
#  福彩3D —— 东方财富 (primary)
# ==========================================

def fetch_3d_from_eastmoney(max_pages=1):
    """从东方财富彩票页抓取福彩3D历史数据"""
    import re

    all_rows = []
    logger.info("福彩3D(eastmoney): 开始抓取...")

    for page in range(1, max_pages + 1):
        url = "https://caipiao.eastmoney.com/Result/History/fc3d?page={}".format(page)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.encoding = 'utf-8'
            if resp.status_code != 200:
                logger.warning("福彩3D(eastmoney): 第 {} 页 HTTP {}".format(page, resp.status_code))
                continue

            html = resp.text
            before_count = len(all_rows)

            rows = re.findall(r'<tr>\s*<td>.*?</tr>', html, re.DOTALL)
            if not rows:
                blocks = re.findall(
                    r'<a[^>]*id=(\d{7})[^>]*>.*?'
                    r'(20\d{2}-\d{2}-\d{2}).*?'
                    r'<span class="pellet[^"]*"[^>]*>(\d)</span>\s*'
                    r'<span class="pellet[^"]*"[^>]*>(\d)</span>\s*'
                    r'<span class="pellet[^"]*"[^>]*>(\d)</span>',
                    html, re.DOTALL
                )
                for block in blocks:
                    issue, date, d1, d2, d3 = block
                    all_rows.append({
                        '期号': issue,
                        '开奖日期': date,
                        '中奖号码': d1 + d2 + d3,
                    })
            else:
                for row in rows:
                    issue_m = re.search(r'id=(\d{7})', row)
                    date_m = re.search(r'(20\d{2}-\d{2}-\d{2})', row)
                    digits = re.findall(r'<span class="pellet[^"]*"[^>]*>(\d)</span>', row)
                    if issue_m and len(digits) >= 3:
                        all_rows.append({
                            '期号': issue_m.group(1),
                            '开奖日期': date_m.group(1) if date_m else '',
                            '中奖号码': ''.join(digits[:3]),
                        })

            logger.info("福彩3D(eastmoney): 第 {} 页 -> {} 条".format(
                page, len(all_rows) - before_count))

        except (requests.exceptions.RequestException, ValueError) as e:
            logger.debug("福彩3D(eastmoney): 第 {} 页失败 {}".format(page, e))

    if not all_rows:
        logger.error("福彩3D(eastmoney): 所有页面抓取失败")
        return None

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=['期号']).sort_values(
        by='期号', ascending=False).reset_index(drop=True)

    logger.info("福彩3D(eastmoney): 共 {} 条 ({} ~ {})".format(
        len(df), df['期号'].iloc[-1], df['期号'].iloc[0]))
    return df


# ==========================================
#  数据校验 & 隔离
# ==========================================

def _validate_draw_data(df, lottery):
    """
    逐行校验数据

    Returns:
        (valid_df, bad_rows_df)
        bad_rows_df 含额外列 '验证失败原因'
    """
    valid_rows = []
    bad_rows = []

    for _, row in df.iterrows():
        errors = []
        issue = str(row.get('期号', '')).strip()
        number = str(row.get('号码', row.get('中奖号码', ''))).strip()
        date_val = str(row.get('日期', row.get('开奖日期', ''))).strip()

        # 1. 期号非空 + 格式校验（复用 issue_utils）
        if not issue:
            errors.append("期号为空")
        else:
            result = validate_issue(issue, lottery)
            if not result['valid']:
                errors.append(result['reason'])

        # 2. 号码3位数字
        number = number.replace(' ', '')
        number = ''.join(c for c in number if c.isdigit())
        if len(number) != 3:
            errors.append("号码不是3位数字: '{}'".format(number))
        else:
            row['号码'] = number.zfill(3)

        # 3. 日期格式（非空时校验）
        if date_val and date_val != 'nan':
            try:
                datetime.strptime(date_val, "%Y-%m-%d")
            except ValueError:
                errors.append("日期格式无效: '{}'".format(date_val))

        if errors:
            bad_row = row.to_dict()
            bad_row['验证失败原因'] = '; '.join(errors)
            bad_rows.append(bad_row)
        else:
            valid_rows.append(row.to_dict())

    valid_df = pd.DataFrame(valid_rows) if valid_rows else pd.DataFrame()
    bad_df = pd.DataFrame(bad_rows) if bad_rows else pd.DataFrame()
    return valid_df, bad_df


def _quarantine_bad_data(bad_df, lottery, reason='数据验证失败'):
    """校验失败的记录写入隔离区（CSV格式）"""
    if bad_df is None or len(bad_df) == 0:
        return
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = QUARANTINE_DIR / '{}_{}_{}.csv'.format(lottery, reason.replace(' ', '_'), ts)
    bad_df.to_csv(path, index=False, encoding='utf-8-sig')
    logger.warning("⚠️ {} 条坏数据已隔离 -> {}".format(len(bad_df), path))


def _quarantine_source_conflict(lottery, issue, expected_date,
                                 primary_source, primary_number, primary_date,
                                 verify_source, verify_number, verify_date,
                                 reason='source_mismatch'):
    """双源号码不一致时写入隔离区（JSON格式，含完整上下文）"""
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = QUARANTINE_DIR / '{}_{}_{}.json'.format(lottery, reason, ts)

    record = {
        'lottery': lottery,
        'issue': issue,
        'expected_date': expected_date,
        'primary': {
            'source': primary_source,
            'number': primary_number,
            'date': primary_date,
        },
        'verify': {
            'source': verify_source,
            'number': verify_number,
            'date': verify_date,
        },
        'reason': reason,
        'action': 'not_written_to_raw',
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    logger.warning("⚠️ 双源冲突已隔离 -> {}".format(path))


def _migrate_old_format(df):
    """检测旧格式(期数,红球_1,红球_2,红球_3)并转换为标准格式(期号,日期,号码)"""
    if '期数' in df.columns and '红球_1' in df.columns:
        logger.warning("检测到旧PLS格式(期数+红球)，自动迁移...")
        df = df.copy()
        df['期号'] = df['期数'].astype(str)
        df['号码'] = (
            df['红球_1'].astype(str).str.zfill(1) +
            df['红球_2'].astype(str).str.zfill(1) +
            df['红球_3'].astype(str).str.zfill(1)
        )
        df['日期'] = ''
        # 过滤无效行（期号必须为5位数字）
        df = df[df['期号'].str.match(r'^\d{5}$')]
        df = df[['期号', '日期', '号码']]
        logger.info("迁移完成: {} 条有效".format(len(df)))
    return df


# ==========================================
#  增量保存（带校验）
# ==========================================

def save_incremental(df, lottery_type):
    """
    通用增量保存：校验 → 隔离坏数据 → 合并去重

    Args:
        df: pd.DataFrame
        lottery_type: 'pls' 或 'd3'
    """
    file_path = RAW_DIR / '{}_raw.csv'.format(lottery_type)

    if df is None or len(df) == 0:
        logger.warning("⚠️ {} 新数据为空，保留旧数据".format(lottery_type))
        return file_path if file_path.exists() else None

    # 统一列名
    rename_map = {
        '开奖日期': '日期',
        '中奖号码': '号码',
        '号码': '号码',
    }
    df_out = df.rename(columns=rename_map)
    # 确保有 期号,日期,号码 三列
    for col in ['期号', '日期', '号码']:
        if col not in df_out.columns:
            df_out[col] = ''
    df_out = df_out[['期号', '日期', '号码']].copy()
    df_out['期号'] = df_out['期号'].astype(str)
    # 清洗号码
    df_out['号码'] = (
        df_out['号码'].astype(str)
        .str.replace(r'\s+', '', regex=True)
        .str.replace(r'\D', '', regex=True)
        .str.zfill(3)
        .str[:3]
    )

    # 数据校验
    valid_df, bad_df = _validate_draw_data(df_out, lottery_type)
    _quarantine_bad_data(bad_df, lottery_type)

    if len(valid_df) == 0:
        logger.error("❌ {} 全部{}条新数据校验失败，不覆盖原文件".format(lottery_type, len(df_out)))
        return file_path if file_path.exists() else None

    # 合并旧数据
    if file_path.exists():
        old_df = pd.read_csv(file_path, dtype=str, encoding='utf-8-sig')
        # 旧格式迁移
        old_df = _migrate_old_format(old_df)
        combined = pd.concat([old_df, valid_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=['期号'], keep='last')
    else:
        combined = valid_df

    combined = combined.sort_values(by='期号', ascending=False).reset_index(drop=True)
    combined.to_csv(file_path, index=False, encoding='utf-8-sig')
    logger.info("数据已更新 -> {} (总计 {} 条)".format(file_path, len(combined)))
    return file_path


# ==========================================
#  主流程
# ==========================================

def main():
    parser = argparse.ArgumentParser(description='彩票开奖数据获取器')
    parser.add_argument('--lottery', choices=['pls', 'd3'], help='彩种')
    parser.add_argument('--all', action='store_true', help='获取所有彩种')
    parser.add_argument('--days', type=int, default=30,
                        help='获取最近多少期（默认30）')
    parser.add_argument('--max-pages', type=int, default=10,
                        help='福彩3D抓取页数')
    parser.add_argument('--source', choices=['zhcw', 'eastmoney', 'auto'],
                        default='auto',
                        help='福彩3D数据源：zhcw/eastmoney/auto')
    parser.add_argument('--verify-backup', action='store_true',
                        help='强制使用备份源（验证备用源可用性）')
    parser.add_argument('--cb-status', action='store_true',
                        help='打印熔断器状态后退出')
    args = parser.parse_args()

    cb = CircuitBreaker()

    if args.cb_status:
        cb.print_status()
        return

    if not args.all and not args.lottery:
        parser.print_help()
        sys.exit(1)

    start = datetime.now()
    logger.info("=== 开始数据更新 ===")

    # --verify-backup: 强制使用备份源（验证备用源可用性）
    if args.verify_backup:
        logger.info("🔧 验证备份源模式：排列三用 sporttery，福彩3D 用 zhcw")

    # ─── 排列三 ───
    if args.all or args.lottery == 'pls':
        pls_data = None
        js_cfg = {'max_failures': 3, 'cooldown_minutes': 60}
        sporttery_cfg = {'max_failures': 2, 'cooldown_minutes': 120}

        # Source 1: js-lottery (primary, --verify-backup 时跳过)
        if args.verify_backup:
            logger.info("排列三: 跳过主源(js-lottery)，直接用备份源(sporttery)")
        elif cb.should_skip('pls_js_lottery', **js_cfg):
            logger.info("排列三: js-lottery 冷却中，跳过")
        else:
            try:
                pls_data = fetch_pls_from_js_lottery(args.days)
            except Exception as e:
                logger.error("排列三(js-lottery): 异常 {}".format(e))
                pls_data = None

            if pls_data and len(pls_data) > 0:
                cb.record_success('pls_js_lottery')
            else:
                cb.record_failure('pls_js_lottery', **js_cfg)

        # Source 2: sporttery API (backup)
        if not pls_data or len(pls_data) == 0:
            if cb.should_skip('pls_sporttery', **sporttery_cfg):
                logger.info("排列三: sporttery 冷却中，跳过")
            else:
                try:
                    pls_data = fetch_pls(args.days)
                except Exception as e:
                    logger.error("排列三(sporttery): 异常 {}".format(e))
                    pls_data = None

                if pls_data and len(pls_data) > 0:
                    cb.record_success('pls_sporttery')
                else:
                    cb.record_failure('pls_sporttery', status_code=567, **sporttery_cfg)

        if pls_data and len(pls_data) > 0:
            save_incremental(pd.DataFrame(pls_data), 'pls')
        else:
            logger.warning("⚠️ 排列三: 所有数据源均失败，保留现有数据")

    # ─── 福彩3D ───
    if args.all or args.lottery == 'd3':
        df_d3 = None
        em_cfg = {'max_failures': 3, 'cooldown_minutes': 60}
        zhcw_cfg = {'max_failures': 2, 'cooldown_minutes': 60}

        if args.source == 'zhcw':
            if cb.should_skip('d3_zhcw', **zhcw_cfg):
                logger.info("福彩3D: zhcw 冷却中，跳过")
            else:
                try:
                    df_d3 = fetch_3d_from_zhcw(max_pages=args.max_pages)
                except Exception as e:
                    logger.error("福彩3D(zhcw): 异常 {}".format(e))
                if df_d3 is not None and len(df_d3) > 0:
                    cb.record_success('d3_zhcw')
                else:
                    cb.record_failure('d3_zhcw', **zhcw_cfg)

        elif args.source == 'eastmoney':
            if cb.should_skip('d3_eastmoney', **em_cfg):
                logger.info("福彩3D: eastmoney 冷却中，跳过")
            else:
                try:
                    df_d3 = fetch_3d_from_eastmoney()
                except Exception as e:
                    logger.error("福彩3D(eastmoney): 异常 {}".format(e))
                if df_d3 is not None and len(df_d3) > 0:
                    cb.record_success('d3_eastmoney')
                else:
                    cb.record_failure('d3_eastmoney', **em_cfg)

        else:  # auto: eastmoney primary → zhcw fallback → verify
            d3_primary_source = None  # 追踪主源，用于双源互验

            # Primary: eastmoney（--verify-backup 时跳过，直接用 zhcw）
            if args.verify_backup:
                logger.info("福彩3D: 跳过主源(eastmoney)，直接用备份源(zhcw)")
            elif cb.should_skip('d3_eastmoney', **em_cfg):
                logger.info("福彩3D: eastmoney 冷却中")
            else:
                try:
                    df_d3 = fetch_3d_from_eastmoney(max_pages=2)
                except Exception as e:
                    logger.error("福彩3D(eastmoney): 异常 {}".format(e))
                if df_d3 is not None and len(df_d3) > 0:
                    cb.record_success('d3_eastmoney')
                    d3_primary_source = 'eastmoney'
                else:
                    cb.record_failure('d3_eastmoney', **em_cfg)

            # Fallback: zhcw
            if df_d3 is None or len(df_d3) == 0:
                if cb.should_skip('d3_zhcw', **zhcw_cfg):
                    logger.info("福彩3D: zhcw 冷却中")
                else:
                    try:
                        df_d3 = fetch_3d_from_zhcw(max_pages=args.max_pages)
                    except Exception as e:
                        logger.error("福彩3D(zhcw): 异常 {}".format(e))
                    if df_d3 is not None and len(df_d3) > 0:
                        cb.record_success('d3_zhcw')
                        d3_primary_source = 'zhcw'
                        logger.warning("福彩3D: 主源(eastmoney)失败，回退到zhcw")
                    else:
                        cb.record_failure('d3_zhcw', **zhcw_cfg)

            # 双源校验：用不同于主源的源做交叉验证
            if args.source == 'auto' and df_d3 is not None and len(df_d3) > 0:
                df_verify = None
                verify_source = None

                if d3_primary_source == 'eastmoney':
                    # 主源 eastmoney → 用 zhcw 验证
                    if not cb.should_skip('d3_zhcw', **zhcw_cfg):
                        try:
                            df_verify = fetch_3d_from_zhcw(max_pages=1)
                            verify_source = 'zhcw'
                        except Exception:
                            logger.warning("验证源 zhcw 不可用，跳过双源校验")
                elif d3_primary_source == 'zhcw':
                    # 主源 zhcw → 用 eastmoney 验证
                    if not cb.should_skip('d3_eastmoney', **em_cfg):
                        try:
                            df_verify = fetch_3d_from_eastmoney(max_pages=1)
                            verify_source = 'eastmoney'
                        except Exception:
                            logger.warning("验证源 eastmoney 不可用，跳过双源校验")
                # 如果 d3_primary_source 未确定（理论上不应发生），跳过校验

                if df_verify is not None and len(df_verify) > 0:
                    latest_main = str(df_d3['期号'].iloc[0])
                    verify_row = df_verify[df_verify['期号'].astype(str) == latest_main]
                    if len(verify_row) > 0:
                        # 安全提取号码字段
                        if '中奖号码' in df_d3.columns:
                            main_col = '中奖号码'
                        elif '号码' in df_d3.columns:
                            main_col = '号码'
                        else:
                            main_col = df_d3.columns[-1]
                        num_main = str(df_d3[df_d3['期号'].astype(str) == latest_main][main_col].iloc[0])

                        if '中奖号码' in verify_row.columns:
                            vfy_col = '中奖号码'
                        elif '号码' in verify_row.columns:
                            vfy_col = '号码'
                        else:
                            vfy_col = verify_row.columns[-1]
                        num_v = str(verify_row[vfy_col].iloc[0])

                        if num_main == num_v:
                            logger.info("双源校验通过: 主源{} vs 验证源{} 期号{} 号码{}一致".format(
                                d3_primary_source, verify_source, latest_main, num_main))
                        else:
                            logger.warning("双源校验不一致: 期号{} 主源({})={} 验证源({})={}".format(
                                latest_main, d3_primary_source, num_main, verify_source, num_v))
                            # 冲突写入结构化 JSON 隔离区
                            main_date = str(df_d3[df_d3['期号'].astype(str) == latest_main]['开奖日期'].iloc[0]) \
                                if '开奖日期' in df_d3.columns else \
                                str(df_d3[df_d3['期号'].astype(str) == latest_main]['日期'].iloc[0]) \
                                if '日期' in df_d3.columns else ''
                            vfy_date = str(verify_row['开奖日期'].iloc[0]) \
                                if '开奖日期' in verify_row.columns else \
                                str(verify_row['日期'].iloc[0]) \
                                if '日期' in verify_row.columns else ''
                            _quarantine_source_conflict(
                                lottery='d3', issue=latest_main, expected_date='',
                                primary_source=d3_primary_source, primary_number=num_main, primary_date=main_date,
                                verify_source=verify_source, verify_number=num_v, verify_date=vfy_date)
                    else:
                        logger.info("校验源({})尚无期号{}的数据".format(verify_source, latest_main))

        if df_d3 is not None and len(df_d3) > 0:
            save_incremental(df_d3, 'd3')
        else:
            logger.warning("⚠️ 福彩3D: 所有数据源均失败，保留现有数据")

    elapsed = datetime.now() - start
    logger.info("=== 更新完成 (耗时: {}) ===".format(elapsed))
    cb.print_status()


if __name__ == '__main__':
    main()
