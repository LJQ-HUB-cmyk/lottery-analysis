#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推送发送模块
============
从 hermes_push.py 拆分而来，负责多通道发送、去重、锁机制。

用法（被 hermes_push.py 调用，不直接运行）：
    from push_sender import send_or_save, acquire_push_lock, release_push_lock
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
PUSH_DIR = BASE / "output" / "push"
PUSH_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))


def now() -> datetime:
    return datetime.now(CN_TZ)


def today_str() -> str:
    return now().strftime("%Y-%m-%d")


# ═══════════════════════════════════════════
#  去重 & 锁
# ═══════════════════════════════════════════

def msg_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def already_sent(kind: str, h: str) -> bool:
    log_path = PUSH_DIR / "send_log.jsonl"
    if not log_path.exists():
        return False
    today = today_str()
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("date") == today and item.get("kind") == kind and item.get("hash") == h and item.get("ok"):
                return True
    except Exception:
        pass
    return False


def already_sent_by_key(kind: str, dedup_key: str) -> bool:
    """业务键去重：同一 date+kind+dedup_key 只推一次，文本变化不绕过"""
    log_path = PUSH_DIR / "send_log.jsonl"
    if not log_path.exists():
        return False
    today = today_str()
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if (item.get("date") == today
                    and item.get("kind") == kind
                    and item.get("dedup_key") == dedup_key
                    and item.get("ok")):
                return True
    except Exception:
        pass
    return False


_LOCK_DIR = BASE / "output" / ".push_locks"
_LOCK_DIR.mkdir(parents=True, exist_ok=True)


def _push_lock(kind: str, h: str) -> str:
    """简易文件锁路径。"""
    os.makedirs(str(_LOCK_DIR), exist_ok=True)
    lock_path = _LOCK_DIR / f"{kind}_{h}.lock"
    return str(lock_path)


def acquire_push_lock(kind: str, h: str, timeout: float = 5.0,
                      stale_after: float = 600.0) -> bool:
    """获取推送锁。timeout=最大等待秒数，stale_after=锁文件超过多久视为残留。"""
    lock_file = _push_lock(kind, h)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(f"{kind}/{h} locked by pid {os.getpid()}\n")
            return True
        except FileExistsError:
            try:
                mtime = os.path.getmtime(lock_file)
                if time.time() - mtime > stale_after:
                    os.unlink(lock_file)
                    continue
            except OSError:
                pass
            time.sleep(0.2)
    return False


def release_push_lock(kind: str, h: str):
    """释放推送锁。"""
    lock_file = _push_lock(kind, h)
    try:
        os.unlink(lock_file)
    except OSError:
        pass


def append_log(kind: str, h: str, ok: bool, detail: str = "", dedup_key: str = ""):
    log_path = PUSH_DIR / "send_log.jsonl"
    item = {
        "time": now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": today_str(),
        "kind": kind,
        "hash": h,
        "dedup_key": dedup_key,
        "ok": ok,
        "detail": detail,
    }
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"[WARN] 写入发送日志失败: {e}", file=sys.stderr)


def write_file(path: Path, text: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except Exception as e:
        print(f"[ERROR] 写入失败: {path} | {e}", file=sys.stderr)
        return False


# ═══════════════════════════════════════════
#  推送通道（独立隔离，微信失败不拖垮飞书）
# ═══════════════════════════════════════════

WECHAT_COOLDOWN = 5       # 微信发送前固定冷却秒数
WECHAT_MAX_RETRIES = 3    # 限频时最大退避次数
WECHAT_BACKOFF = [30, 60, 120]  # 限频退避秒数


def send_feishu(text: str) -> tuple[bool, str]:
    """飞书 webhook（主通道）"""
    url = os.getenv("FEISHU_WEBHOOK_URL", "")
    if not url:
        return False, "FEISHU_WEBHOOK_URL not set"
    try:
        resp = requests.post(
            url,
            json={"msg_type": "text", "content": {"text": text}},
            timeout=15,
        )
        if resp.status_code == 200:
            body = resp.json()
            if body.get("code", -1) != 0:
                return False, f"feishu code={body.get('code')} msg={body.get('msg','')}"
            return True, "feishu ok"
        return False, f"feishu HTTP {resp.status_code}"
    except Exception as e:
        return False, f"feishu exception: {e}"


def send_wechat(text: str) -> tuple[bool, str]:
    """企业微信机器人（辅助通道，带限频退避）"""
    url = os.getenv("WECOM_WEBHOOK_URL", "")
    if not url:
        return False, "WECOM_WEBHOOK_URL not set"

    for i in range(WECHAT_MAX_RETRIES):
        if i > 0:
            time.sleep(WECHAT_COOLDOWN)
        try:
            resp = requests.post(
                url,
                json={"msgtype": "markdown", "markdown": {"content": text}},
                timeout=15,
            )
            if resp.status_code == 200:
                body = resp.json()
                errcode = body.get("errcode", -1)
                errmsg = body.get("errmsg", "")
                if errcode == 0:
                    return True, "wechat ok"
                if "rate" in errmsg.lower() and "limit" in errmsg.lower():
                    wait = WECHAT_BACKOFF[i] if i < len(WECHAT_BACKOFF) else 60
                    print(f"[WARN] 微信限频，等待 {wait}s 后重试 ({i+1}/{WECHAT_MAX_RETRIES})",
                          file=sys.stderr)
                    time.sleep(wait)
                    continue
                if errcode == 45009:  # 接口调用频率限制
                    wait = WECHAT_BACKOFF[i] if i < len(WECHAT_BACKOFF) else 60
                    time.sleep(wait)
                    continue
                return False, f"wechat errcode={errcode} {errmsg}"
            return False, f"wechat HTTP {resp.status_code}"
        except Exception as e:
            err = str(e)
            if "rate" in err.lower() and "limit" in err.lower():
                wait = WECHAT_BACKOFF[i] if i < len(WECHAT_BACKOFF) else 60
                time.sleep(wait)
                continue
            if i < WECHAT_MAX_RETRIES - 1:
                time.sleep(WECHAT_BACKOFF[i] if i < len(WECHAT_BACKOFF) else 30)
                continue
            return False, f"wechat exception: {e}"

    return False, f"wechat rate limited after {WECHAT_MAX_RETRIES} retries"


def send_generic(text: str) -> tuple[bool, str]:
    """通用 webhook（兜底通道）"""
    url = os.getenv("HERMES_WEBHOOK_URL", "")
    if not url:
        return False, "HERMES_WEBHOOK_URL not set"
    try:
        resp = requests.post(url, json={"text": text}, timeout=15)
        if resp.status_code == 200:
            return True, "generic ok"
        return False, f"generic HTTP {resp.status_code}"
    except Exception as e:
        return False, f"generic exception: {e}"


# ═══════════════════════════════════════════
#  push_state 读写
# ═══════════════════════════════════════════

def load_push_state() -> dict:
    path = PUSH_DIR / "push_state.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_push_state(state: dict):
    path = PUSH_DIR / "push_state.json"
    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] 写入 push_state 失败: {e}", file=sys.stderr)


# ═══════════════════════════════════════════
#  多通道推送
# ═══════════════════════════════════════════

def push_to_all_channels(text: str, kind: str, force: bool = False) -> dict[str, str]:
    """推送到所有已配置通道，各通道独立隔离"""
    state = load_push_state()
    state_key = f"{today_str()}_{kind}"
    results = {}

    channels = [
        ("feishu", send_feishu, os.getenv("FEISHU_WEBHOOK_URL")),
        ("wechat", send_wechat, os.getenv("WECOM_WEBHOOK_URL")),
        ("generic", send_generic, os.getenv("HERMES_WEBHOOK_URL")),
    ]

    for ch_name, send_func, env_url in channels:
        if not env_url:
            continue

        ch_key = f"{state_key}_{ch_name}"
        if not force and state.get(ch_key) == "success":
            print(f"[跳过] {ch_name} 今日已推送成功", file=sys.stderr)
            results[ch_name] = "skipped (already sent)"
            continue
        if not force and state.get(ch_key, "").startswith("failed_rate"):
            print(f"[跳过] {ch_name} 今日限频失败，不再重试", file=sys.stderr)
            results[ch_name] = "skipped (rate limited earlier)"
            continue

        ok, detail = send_func(text)
        results[ch_name] = "success" if ok else f"failed: {detail}"
        state[ch_key] = results[ch_name]
        if ok:
            print(f"[完成] {ch_name} 推送成功", file=sys.stderr)
        else:
            print(f"[失败] {ch_name}: {detail}", file=sys.stderr)

    save_push_state(state)
    return results


def send_or_save(text: str, kind: str, force: bool = False, do_send: bool = True,
                 dedup_key: str = "") -> int:
    h = msg_hash(text)
    report_path = PUSH_DIR / f"{kind}_report.md"
    pending_path = PUSH_DIR / f"pending_{kind}_report.md"

    if not write_file(report_path, text):
        append_log(kind, h, False, "write failed", dedup_key)
        return 3

    if not force:
        if dedup_key and already_sent_by_key(kind, dedup_key):
            print(f"[跳过] 今日已发送相同 {kind} 消息（dedup_key={dedup_key}）")
            return 0
        if already_sent(kind, h):
            print(f"[跳过] 今日已发送相同 {kind} 消息")
            return 0

    if not do_send:
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
        append_log(kind, h, True, "write only", dedup_key)
        return 0

    results = push_to_all_channels(text, kind, force)
    success_count = sum(1 for v in results.values() if v == "success" or v.startswith("skipped"))
    fail_count = len(results) - success_count

    if success_count > 0:
        if pending_path.exists():
            pending_path.unlink()
        append_log(kind, h, True, f"channels: {results}", dedup_key)
        print(f"[完成] {kind} 推送: {results}")
        return 0

    write_file(pending_path, text)
    append_log(kind, h, False, f"all channels failed: {results}", dedup_key)
    print(f"[失败] {kind} 全部通道推送失败，已落盘: {pending_path}")
    return 2
