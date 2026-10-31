"""默认配置与内置新闻源清单。

所有内置源均已在容器网络环境下实测可访问（见 README 验证记录）。
"""

CATEGORIES = ["国内", "国际", "财经", "科技", "社会", "体育"]

# 顺序即默认优先级（从上到下优先）
BUILTIN_SOURCES = [
    # 人民网：分类最全，更新稳定
    {"id": "people-politics", "name": "人民网-时政", "url": "http://www.people.com.cn/rss/politics.xml", "category": "国内", "enabled": True},
    {"id": "people-world", "name": "人民网-国际", "url": "http://www.people.com.cn/rss/world.xml", "category": "国际", "enabled": True},
    {"id": "people-finance", "name": "人民网-财经", "url": "http://www.people.com.cn/rss/finance.xml", "category": "财经", "enabled": True},
    {"id": "people-tech", "name": "人民网-科技", "url": "http://www.people.com.cn/rss/it.xml", "category": "科技", "enabled": True},
    {"id": "people-sports", "name": "人民网-体育", "url": "http://www.people.com.cn/rss/sports.xml", "category": "体育", "enabled": True},
    {"id": "people-society", "name": "人民网-社会", "url": "http://www.people.com.cn/rss/society.xml", "category": "社会", "enabled": True},
    # 中新网
    {"id": "chinanews-roll", "name": "中新网-要闻", "url": "http://www.chinanews.com.cn/rss/scroll-news.xml", "category": "国内", "enabled": True},
    {"id": "chinanews-world", "name": "中新网-国际", "url": "http://www.chinanews.com.cn/rss/world.xml", "category": "国际", "enabled": False},
    {"id": "chinanews-finance", "name": "中新网-财经", "url": "http://www.chinanews.com.cn/rss/finance.xml", "category": "财经", "enabled": False},
    {"id": "chinanews-sports", "name": "中新网-体育", "url": "http://www.chinanews.com.cn/rss/sports.xml", "category": "体育", "enabled": False},
    {"id": "chinanews-society", "name": "中新网-社会", "url": "http://www.chinanews.com.cn/rss/society.xml", "category": "社会", "enabled": False},
    # 新浪
    {"id": "sina-china", "name": "新浪-国内", "url": "http://rss.sina.com.cn/news/china/focus15.xml", "category": "国内", "enabled": True},
    {"id": "sina-world", "name": "新浪-国际", "url": "http://rss.sina.com.cn/news/world/focus15.xml", "category": "国际", "enabled": False},
    {"id": "sina-society", "name": "新浪-社会", "url": "http://rss.sina.com.cn/news/society/focus15.xml", "category": "社会", "enabled": False},
    # 财经
    {"id": "eastmoney", "name": "东方财富-财经", "url": "http://rss.eastmoney.com/rss_partener.xml", "category": "财经", "enabled": True},
    {"id": "jiemian", "name": "界面新闻-财经", "url": "https://a.jiemian.com/index.php?m=article&a=rss", "category": "财经", "enabled": False},
    # 科技
    {"id": "ithome", "name": "IT之家-科技", "url": "https://www.ithome.com/rss/", "category": "科技", "enabled": True},
    {"id": "oschina", "name": "开源中国-科技", "url": "https://www.oschina.net/news/rss", "category": "科技", "enabled": False},
    {"id": "sspai", "name": "少数派-科技", "url": "https://sspai.com/feed", "category": "科技", "enabled": False},
]

DEFAULT_CONFIG = {
    "version": 1,
    "schedule": {
        "hours": [7, 8, 12, 18, 21],
        "quiet_start": 23,
        "quiet_end": 7,
    },
    "sources": BUILTIN_SOURCES,
    "rules": {
        "max_chars_per_item": 60,
        "max_items": 6,
        "max_duration_sec": 180,
        "categories": list(CATEGORIES),
        "dedup": True,
        "dedup_hours": 24,
        "chars_per_sec": 5.0,
    },
    "tts": {
        "url": "",
        "did": "",
        "pause_music": True,
        "retry": 2,
        "timeout": 180,
        "intro": "现在为您播报新闻。",
        "outro": "以上就是本次新闻播报，再见。",
    },
    "history": {
        "keep_days": 7,
    },
}

QUICK_PRESETS = {
    "morning": {"name": "早间档", "hours": [7, 8]},
    "noon": {"name": "午间档", "hours": [12]},
    "evening": {"name": "晚间档", "hours": [18, 21]},
    "all": {"name": "全天整点", "hours": list(range(0, 24))},
}


def default_config() -> dict:
    import copy

    return copy.deepcopy(DEFAULT_CONFIG)


def builtin_sources() -> list:
    import copy

    return copy.deepcopy(BUILTIN_SOURCES)
