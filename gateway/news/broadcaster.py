"""TTS 播报执行模块。

默认直接调用上游 xiaomusic 的 /playtts（同容器网络内，无鉴权开销）；
也可在配置里指定 tts.url 走网关自身或其它兼容接口（此时带 Bearer Token）。
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .auth import TOKEN as GATEWAY_TOKEN
from .store import append_record, log

UPSTREAM = os.environ.get("UPSTREAM", "http://host.docker.internal:58090").rstrip("/")
DEFAULT_DID = os.environ.get("DEFAULT_DID", "").strip()


def _resolve_did(cfg: dict) -> str:
    return (cfg.get("tts", {}).get("did") or "").strip() or DEFAULT_DID


def _post_json(url: str, payload: dict, timeout: int, token: str = "") -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else {}


def _get_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else {}


def pause_music(did: str, timeout: int = 10) -> bool:
    """播报前暂停正在播放的音乐。失败不影响播报。"""
    try:
        _post_json(f"{UPSTREAM}/device/stop", {"did": did}, timeout)
        log("INFO", f"已暂停音乐 did={did}")
        return True
    except Exception as e:  # noqa: BLE001
        log("WARN", f"暂停音乐失败（忽略）：{type(e).__name__} {e}")
        return False


def speak(text: str, cfg: dict, timeout: int | None = None) -> dict:
    """调用 TTS 播报文本，带重试。

    返回 {"ok": bool, "attempts": int, "detail": str}
    """
    tts = cfg.get("tts", {})
    did = _resolve_did(cfg)
    timeout = int(timeout or tts.get("timeout") or 180)
    retries = max(0, int(tts.get("retry", 2)))
    custom_url = (tts.get("url") or "").strip()

    if tts.get("pause_music"):
        pause_music(did)

    last_err = ""
    for attempt in range(1, retries + 2):
        try:
            if custom_url:
                payload = _post_json(custom_url, {"text": text, "did": did}, timeout, GATEWAY_TOKEN)
                ok = bool(payload.get("ok") or payload.get("ret") == "OK")
            else:
                url = f"{UPSTREAM}/playtts?" + urllib.parse.urlencode({"text": text, "did": did})
                payload = _get_json(url, timeout)
                ok = payload.get("ret") == "OK"

            if ok:
                log("INFO", f"播报成功（第 {attempt} 次尝试，{len(text)} 字）")
                return {"ok": True, "attempts": attempt, "detail": "ok"}

            last_err = f"上游返回异常：{payload}"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"

        log("WARN", f"播报失败（第 {attempt} 次）：{last_err}")
        if attempt <= retries:
            time.sleep(min(2 * attempt, 5))

    return {"ok": False, "attempts": retries + 1, "detail": last_err}


def broadcast(items: list, cfg: dict, text: str, trigger: str = "manual") -> dict:
    """执行一次完整播报并写入历史。"""
    started = time.time()
    result = speak(text, cfg)
    elapsed = round(time.time() - started, 1)

    record = {
        "ts": time.time(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "trigger": trigger,
        "status": "success" if result["ok"] else "failed",
        "count": len(items),
        "chars": len(text),
        "elapsed": elapsed,
        "detail": result["detail"],
        "items": [{"id": i["id"], "title": i["title"], "source": i["source"]} for i in items],
    }

    rules = cfg.get("rules", {})
    if result["ok"]:
        append_record(
            record,
            items,
            keep_days=int(cfg.get("history", {}).get("keep_days", 7)),
            dedup_hours=int(rules.get("dedup_hours", 24)) if rules.get("dedup") else 0,
        )

    log("INFO" if result["ok"] else "ERROR", f"播报结束 status={record['status']} 用时 {elapsed}s")
    return {"record": record, "result": result}
