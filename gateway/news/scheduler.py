"""定时调度引擎（APScheduler）。

作为网关主进程的后台线程运行，随进程启停；配置变更后热更新，无需重启。
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import store
from .store import log

TIMEZONE = os.environ.get("NEWS_TZ", "Asia/Shanghai")

_scheduler: BackgroundScheduler | None = None


def in_quiet_hours(cfg: dict, hour: int | None = None) -> bool:
    """判断某小时是否落在静音时段内（支持跨零点）。"""
    sch = cfg.get("schedule", {})
    start = int(sch.get("quiet_start", 23))
    end = int(sch.get("quiet_end", 7))
    if start == end:
        return False
    h = datetime.now().hour if hour is None else hour
    if start < end:
        return start <= h < end
    return h >= start or h < end  # 跨零点，如 23 -> 7


def _job(hour: int) -> None:
    """整点任务：重新读取配置（保证热生效），检查静音，然后播报。"""
    from . import service

    try:
        cfg = store.load_config()
        if hour not in [int(x) for x in cfg.get("schedule", {}).get("hours", [])]:
            log("INFO", f"{hour} 点任务已从配置中移除，跳过")
            return
        if in_quiet_hours(cfg, hour):
            log("INFO", f"{hour} 点处于静音时段，跳过播报")
            return
        log("INFO", f"{hour} 点定时任务触发")
        service.run_broadcast(trigger="schedule", cfg=cfg)
    except Exception as e:  # noqa: BLE001 单次失败不能拖垮调度器
        log("ERROR", f"定时任务异常：{type(e).__name__}: {e}")


def _cleanup_job() -> None:
    try:
        cfg = store.load_config()
        days = int(cfg.get("history", {}).get("keep_days", 7))
        store.save_history(store.load_history(), days)
        store.cleanup_logs(30)
    except Exception as e:  # noqa: BLE001
        log("WARN", f"清理任务异常：{e}")


def apply(cfg: dict) -> None:
    """按配置重建定时任务（热更新）。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=TIMEZONE)
        _scheduler.start()
        _scheduler.add_job(
            _cleanup_job,
            CronTrigger(hour=3, minute=30, timezone=TIMEZONE),
            id="news-cleanup",
            replace_existing=True,
        )
        log("INFO", f"调度器已启动（时区 {TIMEZONE}）")

    for job in _scheduler.get_jobs():
        if job.id.startswith("news-hour-"):
            _scheduler.remove_job(job.id)

    hours = sorted({int(h) for h in cfg.get("schedule", {}).get("hours", []) if 0 <= int(h) <= 23})
    for h in hours:
        _scheduler.add_job(
            _job,
            CronTrigger(hour=h, minute=0, second=0, timezone=TIMEZONE),
            args=[h],
            id=f"news-hour-{h}",
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )
    log("INFO", f"定时任务已更新：{len(hours)} 个整点 -> {hours}")


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running


def next_scheduled_time() -> str | None:
    """下一个「定时任务触发点」（可能落在静音时段，届时会被跳过）。"""
    if not is_running():
        return None
    times = [
        j.next_run_time
        for j in _scheduler.get_jobs()
        if j.id.startswith("news-hour-") and j.next_run_time
    ]
    return min(times).strftime("%Y-%m-%d %H:%M:%S") if times else None


def next_run_time() -> str | None:
    """下一次「真正会播报」的时间。

    与 next_scheduled_time 的区别：这里会跳过静音时段里的小时，
    因此即使配置了全天整点，静音时段内的点也不会被算作下次播报。
    """
    cfg = store.load_config()
    hours = sorted({int(h) for h in cfg.get("schedule", {}).get("hours", [])})
    if not hours or not is_running():
        return None

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    # 最多往后找 8 天，避免全部时段都在静音时死循环
    for offset in range(0, 9):
        base = now + timedelta(days=offset)
        for h in hours:
            cand = base.replace(hour=h, minute=0, second=0, microsecond=0)
            if cand <= now:
                continue
            if in_quiet_hours(cfg, h):
                continue
            return cand.strftime("%Y-%m-%d %H:%M:%S")
    return None


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log("INFO", "调度器已停止")
    _scheduler = None
