"""音量与静音控制。

直接调用上游 xiaomusic 的 /getvolume、/setvolume；
静音状态与「静音前的音量」持久化到 state.json，重启后仍可正确恢复。
"""

import json
import os
import threading
import urllib.parse
import urllib.request

from . import store

UPSTREAM = os.environ.get("UPSTREAM", "http://host.docker.internal:58090").rstrip("/")
DEFAULT_DID = os.environ.get("DEFAULT_DID", "").strip()

_lock = threading.Lock()


def resolve_did(cfg: dict | None = None) -> str:
    """优先用配置里的设备，其次环境变量。"""
    if cfg is None:
        try:
            cfg = store.load_config()
        except Exception:  # noqa: BLE001
            cfg = {}
    return ((cfg.get("tts", {}) or {}).get("did") or "").strip() or DEFAULT_DID


def _get_json(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else {}


def _post_json(url: str, payload: dict, timeout: int = 15) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else {}


def get_volume(did: str) -> int:
    """读取音箱当前音量（0-100）。"""
    data = _get_json(f"{UPSTREAM}/getvolume?" + urllib.parse.urlencode({"did": did}))
    return int(data.get("volume", 0))


def set_volume(did: str, volume: int) -> int:
    """设置音量，返回实际生效值。"""
    volume = max(0, min(100, int(volume)))
    data = _post_json(f"{UPSTREAM}/setvolume", {"did": did, "volume": volume})
    if data.get("ret") != "OK":
        raise RuntimeError(f"上游拒绝：{data}")
    return int(data.get("volume", volume))


def status(did: str | None = None) -> dict:
    """当前音量 + 静音状态。"""
    did = did or resolve_did()
    state = store.load_state()
    try:
        current = get_volume(did)
    except Exception as e:  # noqa: BLE001 设备离线时仍返回已保存状态
        store.log("WARN", f"读取音量失败：{type(e).__name__} {e}")
        current = state.get("last_volume", 50)
    return {
        "did": did,
        "volume": current,
        "muted": bool(state.get("muted")),
        "last_volume": int(state.get("last_volume", 50)),
    }


def change_volume(did: str, volume: int) -> dict:
    """调节音量。从静音状态调音量会自动解除静音。"""
    with _lock:
        volume = max(0, min(100, int(volume)))
        applied = set_volume(did, volume)
        state = store.load_state()
        state["muted"] = False
        if applied > 0:
            state["last_volume"] = applied
        store.save_state(state)
        store.log("INFO", f"音量已设为 {applied}")
        return {"volume": applied, "muted": False, "last_volume": state["last_volume"]}


def set_mute(did: str, mute: bool) -> dict:
    """静音 / 取消静音。静音时记住当前音量，取消时恢复。"""
    with _lock:
        state = store.load_state()
        if mute:
            current = get_volume(did)
            if current > 0:
                state["last_volume"] = current
            set_volume(did, 0)
            state["muted"] = True
            store.save_state(state)
            store.log("INFO", f"已静音（记住音量 {state['last_volume']}）")
            return {"volume": 0, "muted": True, "last_volume": state["last_volume"]}

        restore = int(state.get("last_volume") or 50)
        if restore <= 0:
            restore = 50
        applied = set_volume(did, restore)
        state["muted"] = False
        store.save_state(state)
        store.log("INFO", f"已取消静音，恢复音量 {applied}")
        return {"volume": applied, "muted": False, "last_volume": applied}
