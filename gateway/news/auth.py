"""统一鉴权模块。

当前默认 **关闭鉴权**（AUTH_ENABLED=0），局域网内可直接调用所有接口。

如需重新开启，启动容器时加 `-e AUTH_ENABLED=1`，
再用 `TTS_TOKEN` 指定令牌；未指定时使用下面写死的内部令牌。
"""

import hmac
import os

from fastapi import Depends, HTTPException, Request

# 兜底令牌：仅在开启鉴权（AUTH_ENABLED=1）且没有设置 TTS_TOKEN 时生效。
# 请务必改成你自己的随机字符串，不要沿用仓库里的默认值。
HARDCODED_TOKEN = "change-me-please"

TOKEN = (os.environ.get("TTS_TOKEN") or HARDCODED_TOKEN).strip()
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def require_token(request: Request) -> None:
    """鉴权关闭时直接放行；开启时校验 Bearer / X-Token。"""
    if not AUTH_ENABLED:
        return

    provided = ""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        provided = auth_header[7:].strip()
    elif request.headers.get("X-Token"):
        provided = request.headers.get("X-Token", "").strip()

    if not hmac.compare_digest(provided.encode(), TOKEN.encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


auth = [Depends(require_token)]
