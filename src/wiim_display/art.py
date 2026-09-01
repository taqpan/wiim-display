"""アルバムアートの取得・縮小・キャッシュ。

取得元のアートは表示実寸に対して過大なことが多く、そのままブラウザに渡すと
デコード後のビットマップが RAM を圧迫する。サーバ側で縮小してから配信する。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from collections import OrderedDict

import aiohttp
from PIL import Image

logger = logging.getLogger(__name__)

JPEG_QUALITY = 82
CACHE_CAPACITY = 16


def _transcode(data: bytes, size: int) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        # JPEG は DCT 段階から縮小デコードでき、全画素を展開せずに済む
        image.draft("RGB", (size, size))
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return buffer.getvalue()


class ArtCache:
    """縮小済み JPEG をメモリ上に LRU で保持する。ディスクには書かない。"""

    def __init__(self, size: int, timeout: float, capacity: int = CACHE_CAPACITY) -> None:
        self._size = size
        self._capacity = capacity
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._items: OrderedDict[str, bytes] = OrderedDict()
        self._session: aiohttp.ClientSession | None = None

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

    def get(self, key: str) -> bytes | None:
        data = self._items.get(key)
        if data is not None:
            self._items.move_to_end(key)
        return data

    def put(self, key: str, data: bytes) -> None:
        self._items[key] = data
        self._items.move_to_end(key)
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    async def fetch(self, uri: str) -> str | None:
        """アートを取得して縮小し、配信パスを返す。取得できなければ None。"""
        key = self.key_for(uri)
        if self.get(key) is not None:
            return self.path_for(key)
        if self._session is None:
            raise RuntimeError("fetch() called before start()")

        try:
            async with self._session.get(uri) as response:
                response.raise_for_status()
                raw = await response.read()
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("cannot fetch album art: %s: %s", uri, e)
            return None

        try:
            data = await asyncio.to_thread(_transcode, raw, self._size)
        except OSError as e:
            logger.warning("cannot convert album art: %s: %s", uri, e)
            return None

        self.put(key, data)
        logger.debug("cached album art: %s (%d KiB)", key, len(data) // 1024)
        return self.path_for(key)
