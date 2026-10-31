#!/usr/bin/env python3
"""xiaomusic TTS 客户端示例

通过网关（默认 58091 端口）让小米音箱说话。

用法：
    export XM_HOST=192.168.1.100      # 网关所在机器
    export XM_DID=123456789           # 音箱 DID（可用 --devices 查询）

    python xiaomusic_tts_client.py "你好，世界"
    python xiaomusic_tts_client.py "指定设备播报" --did 987654321
    python xiaomusic_tts_client.py --devices

依赖：仅标准库，无需 pip 安装。
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# ---- 配置 ----
HOST = os.environ.get("XM_HOST", "127.0.0.1")
PORT = os.environ.get("XM_PORT", "58091")
TOKEN_FILE = os.environ.get(
    "XM_TOKEN_FILE", os.path.expanduser("~/.xiaomusic_token")
)
DEFAULT_DID = os.environ.get("XM_DID", "")


def load_token() -> str:
    """读取 Token（可选）。

    网关默认已关闭鉴权，此时不需要 Token；若重新开启鉴权，
    可用 XM_TOKEN 环境变量或 Token 文件提供。
    """
    env_token = os.environ.get("XM_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            first = f.readline().strip()
    except OSError:
        return ""  # 没有 Token 文件视为无需鉴权
    # 只接受干净的令牌，避免文件里混入说明文字被当成 header 发送
    if first and len(first) <= 128 and " " not in first:
        return first
    return ""


class XiaoMusicTTS:
    def __init__(self, host=HOST, port=PORT, token=None, timeout=30):
        self.base = f"http://{host}:{port}"
        self.token = token or load_token()
        self.timeout = timeout

    def _request(self, path, params=None, payload=None):
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise SystemExit(f"HTTP {e.code}: {body}")
        except urllib.error.URLError as e:
            raise SystemExit(f"连接失败：{self.base} ({e.reason})")

    def speak(self, text: str, did: str = DEFAULT_DID) -> dict:
        """让音箱播报文字。返回受理结果（异步，不代表已播完）。"""
        return self._request("/tts", payload={"text": text, "did": did})

    def devices(self) -> list:
        return self._request("/devices").get("devices", [])

    def health(self) -> bool:
        try:
            url = f"{self.base}/health"
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False


def main():
    p = argparse.ArgumentParser(description="xiaomusic TTS 客户端")
    p.add_argument("text", nargs="?", help="要播报的文字")
    p.add_argument("--did", default=DEFAULT_DID, help=f"设备 DID（默认 {DEFAULT_DID}）")
    p.add_argument("--devices", action="store_true", help="列出设备")
    args = p.parse_args()

    client = XiaoMusicTTS()

    if args.devices:
        for d in client.devices():
            status = "在线" if d.get("online") else "离线"
            print(f"{d['did']:<12} {d['name']:<14} {d.get('hardware',''):<8} {status}")
        return

    if not args.text:
        p.print_help()
        sys.exit(1)

    if not client.health():
        raise SystemExit(f"网关不可达：{client.base}，请确认容器 xiaomusic-gateway 在运行")

    print(json.dumps(client.speak(args.text, args.did), ensure_ascii=False))


if __name__ == "__main__":
    main()
