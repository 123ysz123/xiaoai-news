# 在官方 xiaomusic 镜像上打两个补丁，并内置新闻播报所需的依赖。
#
# 构建：
#   docker build -t xiaomusic:news .
FROM hanxi/xiaomusic:latest

# ---------------------------------------------------------------------------
# 补丁 1：修复 TTS 无声
#
# 基础镜像自带的 edge-tts 7.2.8 在 WSS 握手时发送 Sec-MS-GEC-Version: 1-xxx，
# 微软已要求版本号 v2，服务端返回 403 → 合成出 0 字节 mp3 → 音箱拉流 416。
# 7.3.1 起改为 Sec-MS-GEC-Version: 2-xxx，恢复正常。
#
# 补丁 2：新闻播报依赖
#   feedparser 用于解析 RSS。APScheduler / FastAPI / uvicorn 基础镜像已自带。
# ---------------------------------------------------------------------------
RUN pip3 --python /app/.venv/bin/python3 install --no-cache-dir --no-warn-script-location \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --upgrade edge-tts==7.3.1 feedparser==6.0.14 \
    && /app/.venv/bin/python3 -c "import edge_tts, edge_tts.constants as c, feedparser, apscheduler, fastapi; \
print('edge-tts:', c.SEC_MS_GEC_VERSION); \
print('feedparser:', feedparser.__version__); \
print('apscheduler:', apscheduler.__version__); \
print('fastapi:', fastapi.__version__)"

# ---------------------------------------------------------------------------
# 补丁 3：修复音量调不动
#
# miservice 的 player_set_volume() 硬编码 media="app_ios"，小米 AI 音箱（S12A）
# 不认这个通道——接口返回 code:0 但音量纹丝不动。改成 media="common" 后生效。
#
# 用通配符匹配 Python 版本目录，避免基础镜像升级小版本后路径失效。
# ---------------------------------------------------------------------------
RUN set -eux; \
    F="$(ls /app/.venv/lib/python3.*/site-packages/miservice/minaservice.py | head -n 1)"; \
    sed -i 's/{"volume": volume, "media": "app_ios"}/{"volume": volume, "media": "common"}/' "$F"; \
    grep -n 'player_set_volume' -A 6 "$F" | head -n 8
