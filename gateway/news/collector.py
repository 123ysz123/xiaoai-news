"""新闻采集与处理引擎。

多源并发拉取 → 分类过滤 → 字段标准化 → 去重 → 截断 → 按时长/条数裁剪 → 排序。
"""

import concurrent.futures as cf
import hashlib
import html
import re
import time
import urllib.request

import feedparser

from .store import log

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """去 HTML 标签、反转义、压缩空白。"""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _entry_ts(entry) -> float:
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                return time.mktime(st)
            except (ValueError, OverflowError):
                pass
    return 0.0


def _make_id(entry, source_id: str) -> str:
    raw = entry.get("id") or entry.get("link") or entry.get("title") or ""
    return hashlib.sha1(f"{source_id}:{raw}".encode("utf-8")).hexdigest()[:16]


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit]
    # 尽量在句末断开，读起来更自然
    for sep in ("。", "！", "？", "；", "，", "、"):
        idx = cut.rfind(sep)
        if idx >= limit * 0.6:
            return cut[: idx + 1]
    return cut.rstrip("，、；：") + "。"


def fetch_source(source: dict, timeout: int = 12) -> list:
    """拉取单个 RSS 源，返回标准化条目。异常由调用方处理。"""
    req = urllib.request.Request(source["url"], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    parsed = feedparser.parse(raw)

    items = []
    for entry in parsed.entries[:30]:
        title = _clean(entry.get("title", ""))
        if not title:
            continue
        summary = _clean(entry.get("summary") or entry.get("description") or "")
        items.append(
            {
                "id": _make_id(entry, source["id"]),
                "title": title,
                "summary": summary,
                "source": source["name"],
                "category": source.get("category", ""),
                "link": entry.get("link", ""),
                "published": _entry_ts(entry),
            }
        )
    return items


def collect(cfg: dict, dedup_ids: set | None = None, timeout: int = 12) -> tuple:
    """按配置采集新闻。

    返回 (items, stats)。items 已按优先级排序并应用条数/字数/时长限制。
    """
    rules = cfg.get("rules", {})
    allowed_cats = set(rules.get("categories") or [])
    dedup_ids = dedup_ids or set()

    enabled = [s for s in cfg.get("sources", []) if s.get("enabled")]
    if not enabled:
        log("WARN", "没有启用的新闻源")
        return [], {"sources": 0, "fetched": 0, "after_filter": 0, "failed": []}

    # 并发拉取，保持源顺序
    results = {}
    failed = []

    def work(src):
        try:
            return src["id"], fetch_source(src, timeout), None
        except Exception as e:  # noqa: BLE001 单源失败不影响整体
            return src["id"], [], f"{src['name']}: {type(e).__name__}"

    with cf.ThreadPoolExecutor(max_workers=min(8, len(enabled))) as ex:
        for sid, items, err in ex.map(work, enabled):
            if err:
                failed.append(err)
                log("WARN", f"源拉取失败 {err}")
            results[sid] = items

    # 分类过滤 + 去重 + 同源内去重
    buckets = []
    fetched = 0
    for src in enabled:  # 按配置顺序 = 优先级
        cat = src.get("category", "")
        if allowed_cats and cat not in allowed_cats:
            continue
        bucket, seen_in_bucket = [], set()
        for it in results.get(src["id"], []):
            fetched += 1
            if it["id"] in dedup_ids or it["id"] in seen_in_bucket:
                continue
            seen_in_bucket.add(it["id"])
            bucket.append(it)
        if bucket:
            buckets.append(bucket)

    # 轮询合并：优先级高的源先出，同时保证来源多样性
    ordered, idx = [], 0
    while any(idx < len(b) for b in buckets):
        for b in buckets:
            if idx < len(b):
                ordered.append(b[idx])
        idx += 1

    max_items = int(rules.get("max_items", 6))
    max_chars = int(rules.get("max_chars_per_item", 60))
    max_sec = float(rules.get("max_duration_sec", 180))
    cps = float(rules.get("chars_per_sec", 5.0)) or 5.0
    intro_len = len(cfg.get("tts", {}).get("intro", ""))
    outro_len = len(cfg.get("tts", {}).get("outro", ""))

    selected, used_chars = [], intro_len + outro_len
    for it in ordered:
        if len(selected) >= max_items:
            break
        item = dict(it)
        item["summary"] = _truncate(item["summary"], max_chars)
        # 播报实际消耗的字数：序号 + 标题 + 摘要
        cost = len(item["title"]) + len(item["summary"]) + 4
        if (used_chars + cost) / cps > max_sec:
            break
        used_chars += cost
        selected.append(item)

    stats = {
        "sources": len(enabled),
        "fetched": fetched,
        "after_filter": len(ordered),
        "selected": len(selected),
        "est_seconds": round(used_chars / cps, 1),
        "failed": failed,
    }
    log(
        "INFO",
        f"采集完成：源 {stats['sources']}，抓取 {fetched} 条，过滤后 {len(ordered)} 条，"
        f"选中 {len(selected)} 条，预计 {stats['est_seconds']} 秒",
    )
    return selected, stats


def build_text(items: list, cfg: dict) -> str:
    """拼接播报文本：开场白 + 逐条新闻 + 结束语。"""
    tts = cfg.get("tts", {})
    parts = []
    intro = (tts.get("intro") or "").strip()
    if intro:
        parts.append(intro)

    for i, it in enumerate(items, 1):
        title = it["title"].strip().rstrip("。，、；：！？.,;:!? ")
        summary = (it.get("summary") or "").strip()
        body = f"{title}。{summary}" if summary else f"{title}。"
        # 统一收尾，避免出现「，。」这种叠标点
        body = body.rstrip("。，、；：.,;: ").rstrip("，") + "。"
        parts.append(f"第{i}条，{body}")

    outro = (tts.get("outro") or "").strip()
    if outro:
        parts.append(outro)

    return "\n".join(parts)
