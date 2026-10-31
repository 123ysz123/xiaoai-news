"""xiaomusic 网关 + 新闻播报服务

原有 TTS 转发接口（/tts /devices /health）保持不变；
新增新闻播报模块，挂载在 /news 前缀下。

启动：
    uvicorn gateway:app --host 0.0.0.0 --port 8091 --app-dir /gw
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from news import scheduler, store
from news.api import router as news_router
from news.auth import auth, AUTH_ENABLED

UPSTREAM = os.environ.get("UPSTREAM", "http://host.docker.internal:58090").rstrip("/")
DEFAULT_DID = os.environ.get("DEFAULT_DID", "").strip()
MAX_TEXT = int(os.environ.get("MAX_TEXT_LEN", "500"))
STATIC_DIR = os.environ.get("NEWS_STATIC", os.path.join(os.path.dirname(__file__), "static"))


def log(msg: str) -> None:
    print(msg, flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化新闻服务与调度器，退出时优雅停止。"""
    store.ensure_dirs()
    cfg = store.load_config()
    scheduler.apply(cfg)
    store.log(
        "INFO",
        f"新闻服务就绪：{len(cfg['schedule']['hours'])} 个播报整点，"
        f"{len([s for s in cfg['sources'] if s.get('enabled')])} 个启用源",
    )
    log(f"gateway listening on 0.0.0.0 -> upstream {UPSTREAM}")
    log(f"鉴权状态：{'已开启' if AUTH_ENABLED else '已关闭（局域网可直接调用）'}")
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="xiaomusic gateway", version="2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- 鉴权
# 统一使用 news.auth.auth：默认关闭，可用 AUTH_ENABLED=1 重新开启


# ---------------------------------------------------------------- 上游工具
def upstream_get(path: str, params: dict, timeout: int = 30) -> dict:
    url = f"{UPSTREAM}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else {}


# ---------------------------------------------------------------- 原有接口
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/tts", dependencies=auth)
def tts_get(text: str = "", did: str = DEFAULT_DID):
    return _do_tts(text, did)


@app.post("/tts", dependencies=auth)
def tts_post(payload: dict):
    return _do_tts(str(payload.get("text", "")), str(payload.get("did") or DEFAULT_DID))


def _do_tts(text: str, did: str):
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text_required")
    if len(text) > MAX_TEXT:
        raise HTTPException(status_code=400, detail=f"text_too_long (max {MAX_TEXT})")
    if not did:
        raise HTTPException(status_code=400, detail="did_required")

    try:
        data = upstream_get("/playtts", {"text": text, "did": did})
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"upstream_http_error {e.code}")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"upstream_failed: {e}")

    if data.get("ret") != "OK":
        raise HTTPException(status_code=400, detail="device_not_found")

    log(f"tts did={did} text={text[:60]}")
    return {"ok": True, "did": did, "text": text}


@app.get("/devices", dependencies=auth)
def devices():
    try:
        data = upstream_get("/device_list", {})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"upstream_failed: {e}")
    return {
        "devices": [
            {
                "did": d.get("miotDID"),
                "name": d.get("name"),
                "hardware": d.get("hardware"),
                "online": d.get("presence") == "online",
            }
            for d in data.get("devices", [])
        ]
    }


# ---------------------------------------------------------------- 新闻模块
# 注意：先注册路由，再挂载静态目录，避免 /news/api/* 被静态文件拦截
app.include_router(news_router)

if os.path.isdir(STATIC_DIR):
    app.mount("/news", StaticFiles(directory=STATIC_DIR, html=True), name="news-static")
else:
    log(f"[warn] 静态目录不存在：{STATIC_DIR}")


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
