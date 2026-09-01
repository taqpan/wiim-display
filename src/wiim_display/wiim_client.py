"""WiiM HTTP API クライアント。

レスポンスの表現形式（16進エンコード、HTML エンティティ、値がすべて文字列であること）は
このモジュール内で吸収し、呼び出し側にはデコード済みの値だけを渡す。
"""

from __future__ import annotations

import contextlib
import html
import json
import logging
import ssl
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# 値が無いときに WiiM が返すリテラル
_EMPTY_VALUES = {"", "unknow", "unknown", "none", "null"}


class WiimUnavailable(RuntimeError):
    """WiiM に到達できない、または応答を解釈できない。"""


@dataclass(frozen=True)
class PlayerStatus:
    status: str
    vol: int
    muted: bool
    title: str
    artist: str
    album: str
    # デコード前の値から作る。曲が変わったかの判定にだけ使う
    track_key: str


@dataclass(frozen=True)
class MetaInfo:
    title: str
    artist: str
    album: str
    album_art_uri: str | None


def _decode_text(value: str) -> str:
    """16進エンコードされた UTF-8 をデコードし、HTML エンティティを戻す。

    getPlayerStatus の Title / Artist / Album はこの形式で返る。
    16進として解釈できない場合はそのまま扱う。
    """
    text = value.strip()
    if text and len(text) % 2 == 0:
        with contextlib.suppress(ValueError, UnicodeDecodeError):
            text = bytes.fromhex(text).decode("utf-8")
    return html.unescape(text)


def _clean(value: str) -> str:
    return "" if value.strip().lower() in _EMPTY_VALUES else value.strip()


def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _parse_status(payload: dict[str, Any]) -> PlayerStatus:
    def field(key: str) -> str:
        return str(payload.get(key, ""))

    return PlayerStatus(
        status=field("status") or "stop",
        vol=_to_int(field("vol"), 0),
        muted=field("mute") == "1",
        title=_clean(_decode_text(field("Title"))),
        artist=_clean(_decode_text(field("Artist"))),
        album=_clean(_decode_text(field("Album"))),
        track_key=f"{field('Title')}/{field('Artist')}/{field('plicurr')}",
    )


def _parse_meta(payload: dict[str, Any]) -> MetaInfo:
    meta = payload.get("metaData")
    if not isinstance(meta, dict):
        raise WiimUnavailable("getMetaInfo returned no metaData")

    def field(key: str) -> str:
        return _clean(str(meta.get(key, "")))

    uri = field("albumArtURI")
    return MetaInfo(
        title=field("title"),
        artist=field("artist"),
        album=field("album"),
        album_art_uri=uri or None,
    )


class WiimClient:
    """`ClientSession` と `SSLContext` を1つだけ持ち、TLS ハンドシェイクを繰り返さない。"""

    def __init__(self, host: str, timeout: float) -> None:
        self._host = host
        # WiiM は自己署名証明書の HTTPS のみを提供する
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=context, limit=2),
            timeout=aiohttp.ClientTimeout(total=timeout),
        )

    async def close(self) -> None:
        await self._session.close()

    async def _request(self, command: str) -> str:
        url = f"https://{self._host}/httpapi.asp?command={command}"
        try:
            async with self._session.get(url) as response:
                response.raise_for_status()
                return await response.text()
        except (aiohttp.ClientError, TimeoutError) as e:
            # 接続タイムアウトなど str() が空になる例外があるため、型名を添える
            raise WiimUnavailable(f"{command}: {type(e).__name__}: {e}") from e

    async def _request_json(self, command: str) -> dict[str, Any]:
        body = await self._request(command)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            raise WiimUnavailable(f"{command}: response is not valid JSON") from e
        if not isinstance(payload, dict):
            raise WiimUnavailable(f"{command}: response is not an object")
        return payload

    async def player_status(self) -> PlayerStatus:
        return _parse_status(await self._request_json("getPlayerStatus"))

    async def meta_info(self) -> MetaInfo:
        return _parse_meta(await self._request_json("getMetaInfo"))

    async def send(self, command: str) -> str:
        return (await self._request(command)).strip()
