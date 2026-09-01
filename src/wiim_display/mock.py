"""開発モード用のフィクスチャ。

800x480 の固定レイアウトが破綻しうる入力を網羅する。WiiM 実機に接続せずに
これらを任意に呼び出せることが、レイアウト調整の質を決める。
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image

from .state import CONN_DOWN, CONN_OK, CONN_STALE

ART_KEY = "mockart"
ART_PATH = f"/art/{ART_KEY}.jpg"

DEFAULT_SCENARIO = "normal"

_BASE: dict[str, Any] = {
    "status": "play",
    "vol": 42,
    "muted": False,
    "title": "KNIGHT'S SONG",
    "artist": "T-SQUARE",
    "album": "BLUE IN RED",
    "art": ART_PATH,
    "conn": CONN_OK,
}


def _with(**changes: Any) -> dict[str, Any]:
    return {**_BASE, **changes}


SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": _with(),
    "long_title_ja": _with(
        title="交響組曲「幻想の大陸をこえて」第三楽章 ― 遥かなる地平線と失われた王国の記憶",
        artist="オーケストラ・フィルハーモニア東京",
        album="交響組曲「幻想の大陸をこえて」全曲集 デラックス・エディション",
    ),
    "long_artist": _with(
        title="Adagio for Strings",
        artist="The Royal Philharmonic Orchestra & The London Chamber Ensemble feat. A. Kensington",
        album="Essential Classical Collection Volume Three",
    ),
    "no_art": _with(art=None),
    "muted": _with(muted=True),
    "vol_0": _with(vol=0),
    "vol_100": _with(vol=100),
    "stopped": _with(status="stop", title="", artist="", album="", art=None),
    "stale": _with(conn=CONN_STALE),
    "down": _with(conn=CONN_DOWN),
    "ascii_only": _with(
        title="Yesterday",
        artist="The Beatles",
        album="Help!",
    ),
}


def scenario(name: str) -> dict[str, Any] | None:
    fields = SCENARIOS.get(name)
    return dict(fields) if fields else None


def art_bytes(size: int) -> bytes:
    """アート枠の寸法と角丸を確認できる程度の画像を生成する。"""
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    assert pixels is not None
    for y in range(size):
        for x in range(size):
            pixels[x, y] = (30 + x * 160 // size, 40 + y * 120 // size, 90 + x * 140 // size)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=82)
    return buffer.getvalue()
