"""持久化层：配置、历史、日志。

所有数据落在 NEWS_DIR（容器内 /data/news-service），该目录为宿主 bind 挂载，
容器重建不丢失。
"""

import copy
import json
import os
import threading
import time
from collections import deque
from datetime import datetime

from .defaults import default_config

DATA_DIR = os.environ.get("NEWS_DIR", "/data/news-service")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
LOG_DIR = os.path.join(DATA_DIR, "logs")

_lock = threading.RLock()
_mem_logs = deque(maxlen=500)


# ---------------------------------------------------------------- 工具
def _deep_merge(base: dict, override: dict) -> dict:
    """用 override 覆盖 base，dict 递归合并，list 整体替换。"""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _atomic_write(path: str, data: str) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


# ---------------------------------------------------------------- 配置
def load_config() -> dict:
    """加载配置；文件不存在或损坏时回落到默认配置。"""
    ensure_dirs()
    with _lock:
        if not os.path.exists(CONFIG_FILE):
            cfg = default_config()
            save_config(cfg)
            log("INFO", "首次启动，已生成默认配置 config.json")
            return cfg
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
            # 与默认值合并，保证新增字段自动补齐
            return _deep_merge(default_config(), stored)
        except (OSError, json.JSONDecodeError) as e:
            log("ERROR", f"配置读取失败，使用默认配置：{e}")
            return default_config()


def save_config(cfg: dict) -> dict:
    ensure_dirs()
    with _lock:
        _atomic_write(CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=2))
    return cfg


def reset_config() -> dict:
    cfg = default_config()
    save_config(cfg)
    log("INFO", "配置已恢复默认")
    return cfg


# ---------------------------------------------------------------- 历史与去重
def load_history() -> dict:
    ensure_dirs()
    with _lock:
        if not os.path.exists(HISTORY_FILE):
            return {"seen": {}, "records": []}
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("seen", {})
            data.setdefault("records", [])
            return data
        except (OSError, json.JSONDecodeError):
            return {"seen": {}, "records": []}


def save_history(data: dict, keep_days: int = 7) -> None:
    """保存历史，同时清理过期记录与去重索引。"""
    ensure_dirs()
    now = time.time()
    cutoff = now - keep_days * 86400

    with _lock:
        data["records"] = [r for r in data.get("records", []) if r.get("ts", 0) >= cutoff]
        # 去重索引最多保留 7 天，避免无限增长
        dedup_cutoff = now - max(keep_days, 2) * 86400
        data["seen"] = {k: v for k, v in data.get("seen", {}).items() if v >= dedup_cutoff}
        _atomic_write(HISTORY_FILE, json.dumps(data, ensure_ascii=False, indent=2))


def append_record(record: dict, items: list, keep_days: int, dedup_hours: int) -> None:
    """写入一条播报记录，并登记去重索引。"""
    data = load_history()
    data["records"].append(record)
    data["records"] = data["records"][-200:]
    if dedup_hours > 0:
        ts = record["ts"]
        for it in items:
            if it.get("id"):
                data["seen"][it["id"]] = ts
    save_history(data, keep_days)


def seen_ids(dedup_hours: int) -> set:
    """返回在去重窗口内已播报过的新闻 id。"""
    if dedup_hours <= 0:
        return set()
    cutoff = time.time() - dedup_hours * 3600
    data = load_history()
    return {k for k, v in data.get("seen", {}).items() if v >= cutoff}


# ---------------------------------------------------------------- 日志
def log(level: str, msg: str) -> None:
    ts = datetime.now()
    line = f"[{ts.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}"
    _mem_logs.append(line)
    try:
        ensure_dirs()
        path = os.path.join(LOG_DIR, f"{ts.strftime('%Y-%m-%d')}.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def recent_logs(limit: int = 100) -> list:
    return list(_mem_logs)[-limit:]


def cleanup_logs(keep_days: int = 30) -> None:
    """删除过期日志文件。"""
    cutoff = time.time() - keep_days * 86400
    try:
        for name in os.listdir(LOG_DIR):
            if not name.endswith(".log"):
                continue
            p = os.path.join(LOG_DIR, name)
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
    except OSError:
        pass


# ---------------------------------------------------------------- 运行时状态
def load_state() -> dict:
    """音量/静音等运行时状态，重启后仍能恢复。"""
    ensure_dirs()
    with _lock:
        if not os.path.exists(STATE_FILE):
            return {"muted": False, "last_volume": 50}
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("muted", False)
            data.setdefault("last_volume", 50)
            return data
        except (OSError, json.JSONDecodeError):
            return {"muted": False, "last_volume": 50}


def save_state(data: dict) -> None:
    ensure_dirs()
    with _lock:
        _atomic_write(STATE_FILE, json.dumps(data, ensure_ascii=False, indent=2))
