"""開発モード用のフィクスチャ。

800x480 の固定レイアウトが破綻しうる入力と、背景の色調が変わる入力を網羅する。
WiiM 実機に接続せずにこれらを任意に呼び出せることが、レイアウト調整の質を決める。
"""

from __future__ import annotations

import colorsys
import io
from typing import Any

from PIL import Image

from .art import ArtCache, render
from .state import CONN_DOWN, CONN_OK, CONN_STALE, NO_ART

DEFAULT_SCENARIO = "normal"

# 生成するモックアートと、その基調となる色相。None は無彩色
ART_HUES: dict[str, int | None] = {"cool": 210, "warm": 25, "mono": None}
DEFAULT_ART = "cool"

# 生成元の一辺。配信寸法まで拡大してから render に渡すため小さくてよい
ART_SOURCE = 64

_BASE: dict[str, Any] = {
    "status": "play",
    "vol": 42,
    "muted": False,
    "title": "KNIGHT'S SONG",
    "artist": "T-SQUARE",
    "album": "BLUE IN RED",
    "conn": CONN_OK,
}


def _with(art: str | None = DEFAULT_ART, **changes: Any) -> dict[str, Any]:
    """`art` はモックアートの種別名。実体のパスと色調は install() が差し込む。"""
    return {**_BASE, "art": art, **changes}


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
    "tint_warm": _with(
        art="warm",
        title="Sunset Boulevard",
        artist="Amber Lane",
        album="Golden Hour",
    ),
    "tint_mono": _with(
        art="mono",
        title="Round Midnight",
        artist="Monochrome Quartet",
        album="Silver Sessions",
    ),
    "muted": _with(muted=True),
    "vol_0": _with(vol=0),
    "vol_100": _with(vol=100),
    "stopped": _with(art=None, status="stop", title="", artist="", album=""),
    "stale": _with(conn=CONN_STALE),
    "down": _with(conn=CONN_DOWN),
    "ascii_only": _with(
        title="Yesterday",
        artist="The Beatles",
        album="Help!",
    ),
}


def art_image(hue: int | None, size: int) -> bytes:
    """アート枠の寸法と角丸、および色調の抽出を確認できる程度の画像を生成する。"""
    small = Image.new("RGB", (ART_SOURCE, ART_SOURCE))
    pixels = small.load()
    assert pixels is not None
    for y in range(ART_SOURCE):
        for x in range(ART_SOURCE):
            value = 0.25 + 0.55 * (x / ART_SOURCE)
            sat = 0.0 if hue is None else 0.35 + 0.45 * (y / ART_SOURCE)
            r, g, b = colorsys.hsv_to_rgb((hue or 0) / 360, sat, value)
            pixels[x, y] = (round(r * 255), round(g * 255), round(b * 255))

    buffer = io.BytesIO()
    small.resize((size, size), Image.Resampling.BICUBIC).save(buffer, "JPEG", quality=82)
    return buffer.getvalue()


def install(cache: ArtCache, size: int) -> dict[str, dict[str, Any]]:
    """モックのアートをキャッシュへ載せ、シナリオのアート指定を実体へ解決する。

    シナリオが持つ色調は生成した画像から実際に抽出する。宣言値を別に持たせると、
    画像と背景の色がずれていてもモックでは気づけない。
    """
    arts: dict[str, dict[str, Any]] = {}
    for name, hue in ART_HUES.items():
        key = f"mockart-{name}"
        art = render(art_image(hue, size), size)
        cache.put(key, art)
        arts[name] = ArtCache.fields(key, art)

    return {
        name: {**fields, **(arts[fields["art"]] if fields["art"] else NO_ART)}
        for name, fields in SCENARIOS.items()
    }
