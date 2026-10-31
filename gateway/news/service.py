"""新闻服务编排层：把采集、播报、调度串起来。"""

from . import broadcaster, collector, store


def _dedup_ids(cfg: dict) -> set:
    rules = cfg.get("rules", {})
    if not rules.get("dedup"):
        return set()
    return store.seen_ids(int(rules.get("dedup_hours", 24)))


def preview(cfg: dict | None = None) -> tuple:
    """只采集不播报，用于页面测试。"""
    cfg = cfg or store.load_config()
    items, stats = collector.collect(cfg, _dedup_ids(cfg))
    return items, stats


def run_broadcast(trigger: str = "manual", cfg: dict | None = None) -> dict:
    """执行一次完整播报。trigger: manual / schedule"""
    cfg = cfg or store.load_config()
    store.log("INFO", f"开始播报（触发方式：{trigger}）")

    items, stats = preview(cfg)
    if not items:
        store.log("WARN", "没有可播报的新闻，本次跳过")
        return {
            "ok": False,
            "reason": "no_news",
            "items": [],
            "stats": stats,
            "text": "",
        }

    text = collector.build_text(items, cfg)
    result = broadcaster.broadcast(items, cfg, text, trigger)
    return {
        "ok": result["result"]["ok"],
        "items": items,
        "stats": stats,
        "text": text,
        "record": result["record"],
    }


def status(cfg: dict | None = None) -> dict:
    """供前端状态卡片使用。"""
    from . import scheduler

    cfg = cfg or store.load_config()
    sch = cfg.get("schedule", {})
    return {
        "scheduler_running": scheduler.is_running(),
        "hours": sch.get("hours", []),
        "next_run": scheduler.next_run_time(),           # 下次真正播报的时间
        "next_scheduled": scheduler.next_scheduled_time(),  # 下个定时触发点（可能被静音跳过）
        "quiet": scheduler.in_quiet_hours(cfg),
        "quiet_window": f"{int(sch.get('quiet_start', 23)):02d}:00 - {int(sch.get('quiet_end', 7)):02d}:00",
        "source_count": len(cfg.get("sources", [])),
        "enabled_source_count": len([s for s in cfg.get("sources", []) if s.get("enabled")]),
    }
