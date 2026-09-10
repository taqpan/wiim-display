"""アルバムアートの取得・縮小・色調抽出・キャッシュ。

取得元のアートは表示実寸に対して過大なことが多く、そのままブラウザに渡すと
デコード後のビットマップが RAM を圧迫する。サーバ側で縮小してから配信する。
背景の色調も、すでに展開済みの画素をここで使い回して求める。
"""

from __future__ import annotations

import asyncio
import colorsys
import hashlib
import io
import logging
import math
import ssl
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from PIL import Image

logger = logging.getLogger(__name__)

JPEG_QUALITY = 92
CACHE_CAPACITY = 16

TINT_SAMPLE = 32
TINT_COLORS = 8
# 明度がこの範囲を外れた色は色相が当てにならないため、色調の集計から除く
TINT_VALUE_MIN = 0.12
TINT_VALUE_MAX = 0.96
# 集計値は鮮やかなアートでも 0.5 前後にとどまるため、指定域 0..1 へ引き伸ばす
TINT_GAIN = 2.0


@dataclass(frozen=True)
class Art:
    data: bytes
    hue: int
    chroma: float


def _tint(image: Image.Image) -> tuple[int, float]:
    """代表的な色相と、それをどれだけ効かせてよいかを 0..1 で返す。

    明度と彩度の上限は表示側が握る。ここで色を決めきると、明るいアートで
    文字とのコントラストが落ちるのを止められない。
    """
    small = image.resize((TINT_SAMPLE, TINT_SAMPLE), Image.Resampling.BOX)
    palette = small.quantize(colors=TINT_COLORS, method=Image.Quantize.MEDIANCUT)
    table = palette.getpalette() or []

    x = y = weight = 0.0
    for count, index in palette.getcolors() or []:
        r, g, b = table[index * 3 : index * 3 + 3]
        hue, sat, value = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if not TINT_VALUE_MIN <= value <= TINT_VALUE_MAX:
            continue
        w = count * sat
        # 色相は角度なので単純平均できない。単位ベクトルの和として平均を取る
        x += w * math.cos(2 * math.pi * hue)
        y += w * math.sin(2 * math.pi * hue)
        weight += w
    if weight <= 0:
        return 0, 0.0

    # 色相の揃い具合。赤と青が同量あるようなアートでは背景を無彩色に寄せる
    agreement = math.hypot(x, y) / weight
    chroma = min(1.0, weight / TINT_SAMPLE**2 * agreement * TINT_GAIN)
    return round(math.degrees(math.atan2(y, x))) % 360, round(chroma, 3)


def render(data: bytes, size: int) -> Art:
    """取得したバイト列を配信用の JPEG と色調に変換する。"""
    with Image.open(io.BytesIO(data)) as image:
        # JPEG は DCT 段階から縮小デコードでき、全画素を展開せずに済む
        image.draft("RGB", (size, size))
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        rgb = image.convert("RGB")

    buffer = io.BytesIO()
    rgb.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True, subsampling=0)
    hue, chroma = _tint(rgb)
    return Art(buffer.getvalue(), hue, chroma)


class ArtCache:
    """縮小済み JPEG と色調をメモリ上に LRU で保持する。ディスクには書かない。"""

    def __init__(
        self, size: int, timeout: float, wiim_host: str, capacity: int = CACHE_CAPACITY
    ) -> None:
        self._size = size
        self._capacity = capacity
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._wiim_host = wiim_host.split(":")[0].lower()
        self._items: OrderedDict[str, Art] = OrderedDict()
        self._session: aiohttp.ClientSession | None = None

        # DLNA 再生時、アートは WiiM 自身が自己署名証明書の HTTPS で配信する。
        # 配信サービスのアートは公開 CDN 上にあるため、検証を切るのは WiiM 宛だけとする
        self._wiim_ssl = ssl.create_default_context()
        self._wiim_ssl.check_hostname = False
        self._wiim_ssl.verify_mode = ssl.CERT_NONE

    def _ssl_for(self, uri: str) -> ssl.SSLContext | bool:
        host = (urlsplit(uri).hostname or "").lower()
        return self._wiim_ssl if host == self._wiim_host else True

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(timeout=self._timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    @staticmethod
    def key_for(uri: str) -> str:
        return hashlib.sha1(uri.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]

    @staticmethod
    def path_for(key: str) -> str:
        return f"/art/{key}.jpg"

    @staticmethod
    def fields(key: str, art: Art) -> dict[str, Any]:
        """表示状態へ反映する項目。色調は常にアートと同時に差し替える。"""
        return {"art": ArtCache.path_for(key), "art_hue": art.hue, "art_chroma": art.chroma}

    def get(self, key: str) -> Art | None:
        art = self._items.get(key)
        if art is not None:
            self._items.move_to_end(key)
        return art

    def put(self, key: str, art: Art) -> None:
        self._items[key] = art
        self._items.move_to_end(key)
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def cached(self, uri: str) -> dict[str, Any] | None:
        key = self.key_for(uri)
        art = self.get(key)
        return None if art is None else self.fields(key, art)

    async def fetch(self, uri: str) -> dict[str, Any] | None:
        """アートを取得して縮小し、表示状態へ反映する項目を返す。取得できなければ None。"""
        cached = self.cached(uri)
        if cached is not None:
            return cached
        if self._session is None:
            raise RuntimeError("fetch() called before start()")

        try:
            async with self._session.get(uri, ssl=self._ssl_for(uri)) as response:
                response.raise_for_status()
                raw = await response.read()
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("cannot fetch album art: %s: %s", uri, e)
            return None

        try:
            art = await asyncio.to_thread(render, raw, self._size)
        except OSError as e:
            logger.warning("cannot convert album art: %s: %s", uri, e)
            return None

        key = self.key_for(uri)
        self.put(key, art)
        logger.debug(
            "cached album art: %s (%d KiB, hue=%d chroma=%.2f)",
            key,
            len(art.data) // 1024,
            art.hue,
            art.chroma,
        )
        return self.fields(key, art)
