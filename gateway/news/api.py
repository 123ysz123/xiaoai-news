"""新闻服务 API 路由，统一挂载在 /news 前缀下。"""

from fastapi import APIRouter, HTTPException

from . import scheduler, service, store, volume
from .auth import auth
from .defaults import CATEGORIES

router = APIRouter(prefix="/news", tags=["news"])


# ---------------------------------------------------------------- 配置
def _clamp(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _sanitize(payload: dict, current: dict) -> dict:
    """只接受已知字段并做范围校验，防止前端传入脏数据破坏调度。"""
    cfg = {
        "version": 1,
        "schedule": {},
        "sources": [],
        "rules": {},
        "tts": {},
        "history": {},
    }

    sch = payload.get("schedule") or {}
    hours = sch.get("hours", current["schedule"]["hours"])
    cfg["schedule"] = {
        "hours": sorted({_clamp(h, 0, 23, 0) for h in hours}) if isinstance(hours, list) else current["schedule"]["hours"],
        "quiet_start": _clamp(sch.get("quiet_start"), 0, 23, current["schedule"]["quiet_start"]),
        "quiet_end": _clamp(sch.get("quiet_end"), 0, 23, current["schedule"]["quiet_end"]),
    }

    srcs = payload.get("sources")
    if isinstance(srcs, list):
        cleaned, used_ids = [], set()
        for i, s in enumerate(srcs):
            if not isinstance(s, dict):
                continue
            url = str(s.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                continue
            sid = str(s.get("id") or f"custom-{i}").strip()
            if sid in used_ids:
                sid = f"{sid}-{i}"
            used_ids.add(sid)
            cat = s.get("category") if s.get("category") in CATEGORIES else "国内"
            cleaned.append(
                {
                    "id": sid,
                    "name": str(s.get("name", "未命名源"))[:40],
                    "url": url[:500],
                    "category": cat,
                    "enabled": bool(s.get("enabled", True)),
                }
            )
        cfg["sources"] = cleaned or current["sources"]
    else:
        cfg["sources"] = current["sources"]

    r = payload.get("rules") or {}
    cur_r = current["rules"]
    cats = r.get("categories")
    cfg["rules"] = {
        "max_chars_per_item": _clamp(r.get("max_chars_per_item"), 10, 300, cur_r["max_chars_per_item"]),
        "max_items": _clamp(r.get("max_items"), 1, 20, cur_r["max_items"]),
        "max_duration_sec": _clamp(r.get("max_duration_sec"), 20, 1800, cur_r["max_duration_sec"]),
        "categories": [c for c in cats if c in CATEGORIES] if isinstance(cats, list) else cur_r["categories"],
        "dedup": bool(r.get("dedup", cur_r["dedup"])),
        "dedup_hours": _clamp(r.get("dedup_hours"), 1, 168, cur_r["dedup_hours"]),
        "chars_per_sec": max(1.0, min(12.0, float(r.get("chars_per_sec") or cur_r["chars_per_sec"]))),
    }
    if not cfg["rules"]["categories"]:
        cfg["rules"]["categories"] = list(CATEGORIES)

    t = payload.get("tts") or {}
    cur_t = current["tts"]
    cfg["tts"] = {
        "url": str(t.get("url", cur_t["url"]) or "")[:300],
        "did": str(t.get("did", cur_t["did"]) or "")[:40],
        "pause_music": bool(t.get("pause_music", cur_t["pause_music"])),
        "retry": _clamp(t.get("retry"), 0, 5, cur_t["retry"]),
        "timeout": _clamp(t.get("timeout"), 30, 600, cur_t["timeout"]),
        "intro": str(t.get("intro", cur_t["intro"]) or "")[:200],
        "outro": str(t.get("outro", cur_t["outro"]) or "")[:200],
    }

    h = payload.get("history") or {}
    cfg["history"] = {"keep_days": _clamp(h.get("keep_days"), 1, 365, current["history"]["keep_days"])}
    return cfg


@router.get("/api/config", dependencies=auth)
def get_config():
    return store.load_config()


@router.post("/api/config", dependencies=auth)
def post_config(payload: dict):
    current = store.load_config()
    cfg = _sanitize(payload, current)
    store.save_config(cfg)
    scheduler.apply(cfg)  # 热更新，无需重启
    store.log("INFO", f"配置已保存并热更新（{len(cfg['schedule']['hours'])} 个整点，{len(cfg['sources'])} 个源）")
    return {"ok": True, "config": cfg, "next_run": scheduler.next_run_time()}


@router.post("/api/config/reset", dependencies=auth)
def reset_config():
    cfg = store.reset_config()
    scheduler.apply(cfg)
    return {"ok": True, "config": cfg}


# ---------------------------------------------------------------- 新闻源
@router.get("/api/sources", dependencies=auth)
def get_sources():
    cfg = store.load_config()
    return {"sources": cfg.get("sources", []), "categories": CATEGORIES}


# ---------------------------------------------------------------- 执行
@router.get("/api/status", dependencies=auth)
def get_status():
    return service.status()


@router.post("/api/preview", dependencies=auth)
def preview(payload: dict | None = None):
    """只采集不播报。payload 可选 {limit: N}。"""
    cfg = store.load_config()
    items, stats = service.preview(cfg)
    limit = None
    if isinstance(payload, dict) and payload.get("limit"):
        try:
            limit = max(1, int(payload["limit"]))
        except (TypeError, ValueError):
            limit = None
    shown = items[:limit] if limit else items
    return {"ok": True, "items": shown, "stats": stats, "total": len(items)}


@router.post("/api/broadcast", dependencies=auth)
def broadcast():
    cfg = store.load_config()
    result = service.run_broadcast(trigger="manual", cfg=cfg)
    if not result.get("ok") and result.get("reason") == "no_news":
        raise HTTPException(status_code=409, detail="没有可播报的新闻（可能被去重规则全部过滤）")
    return result


# ---------------------------------------------------------------- 日志与历史
@router.get("/api/logs", dependencies=auth)
def get_logs(limit: int = 100):
    return {"logs": store.recent_logs(max(1, min(500, limit)))}


@router.get("/api/history", dependencies=auth)
def get_history(limit: int = 20):
    data = store.load_history()
    records = list(reversed(data.get("records", [])))[: max(1, min(100, limit))]
    return {"records": records, "total": len(data.get("records", []))}


# ---------------------------------------------------------------- 音量与静音
@router.get("/api/volume", dependencies=auth)
def get_volume():
    try:
        return volume.status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"volume_unavailable: {e}")


@router.post("/api/volume", dependencies=auth)
def post_volume(payload: dict):
    if "volume" not in payload:
        raise HTTPException(status_code=400, detail="volume_required")
    did = str(payload.get("did") or "").strip() or volume.resolve_did()
    try:
        return volume.change_volume(did, int(payload["volume"]))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="volume_invalid")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"set_volume_failed: {e}")


@router.post("/api/mute", dependencies=auth)
def post_mute(payload: dict | None = None):
    mute = True
    if isinstance(payload, dict) and "mute" in payload:
        mute = bool(payload["mute"])
    did = ""
    if isinstance(payload, dict):
        did = str(payload.get("did") or "").strip()
    did = did or volume.resolve_did()
    try:
        return volume.set_mute(did, mute)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"mute_failed: {e}")
