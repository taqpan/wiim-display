"""WiiM HTTP API を生のまま叩くための最小クライアント。

プロダクトコード（src/wiim_display）からは独立させ、標準ライブラリだけで完結させる。
検証対象の実装を検証手段が共有しないようにするため。
"""

from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

CAPTURE_DIR = Path("tools/captured")

# WiiM は自己署名証明書の HTTPS のみを提供する
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


class WiimError(RuntimeError):
    pass


def api_url(host: str, command: str) -> str:
    return f"https://{host}/httpapi.asp?command={command}"


def fetch_raw(host: str, command: str, timeout: float) -> str:
    url = api_url(host, command)
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=_SSL_CONTEXT) as res:
            return res.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        raise WiimError(f"HTTP {e.code} {e.reason}: {url}") from e
    except (URLError, TimeoutError, OSError) as e:
        raise WiimError(f"接続失敗: {e}: {url}") from e


def fetch_json(host: str, command: str, timeout: float) -> tuple[dict[str, Any], str]:
    """レスポンスを (パース結果, 生テキスト) で返す。"""
    body = fetch_raw(host, command, timeout)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise WiimError(f"JSON として解釈できない: {body[:200]!r}") from e
    if not isinstance(parsed, dict):
        raise WiimError(f"オブジェクトが返らなかった: {type(parsed).__name__}")
    return parsed, body


def fetch_bytes(url: str, timeout: float) -> tuple[bytes, str]:
    """任意の URL を取得し (本体, Content-Type) で返す。アルバムアートの検証に使う。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=_SSL_CONTEXT) as res:
            return res.read(), res.headers.get("Content-Type", "")
    except HTTPError as e:
        raise WiimError(f"HTTP {e.code} {e.reason}") from e
    except (URLError, TimeoutError, OSError) as e:
        raise WiimError(f"接続失敗: {e}") from e


def decode_hex_text(value: str) -> tuple[str | None, str]:
    """16進エンコードされた UTF-8 をデコードし (結果, 判定) を返す。

    判定は `hex` / `plain`（16進ではない） / `invalid`（16進だが UTF-8 にならない）。
    """
    stripped = value.strip()
    if not stripped or len(stripped) % 2 != 0:
        return None, "plain"
    try:
        raw = bytes.fromhex(stripped)
    except ValueError:
        return None, "plain"
    try:
        return raw.decode("utf-8"), "hex"
    except UnicodeDecodeError:
        return None, "invalid"


def save_capture(name: str, body: str) -> Path:
    """生レスポンスを保存する。mock.py のフィクスチャの元データにする。"""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = CAPTURE_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.json"
    path.write_text(body, encoding="utf-8")
    return path
