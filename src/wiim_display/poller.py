"""WiiM を定期的に取得して状態へ反映する単一タスク。

プロセス内に1本だけ持ち、クライアントの接続数と独立させる。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from .art import ArtCache
from .config import Config
from .state import CONN_DOWN, CONN_OK, CONN_STALE, StateStore
from .wiim_client import PlayerStatus, WiimClient, WiimUnavailable

logger = logging.getLogger(__name__)

# この回数だけ連続で失敗したら conn を stale から down に落とす
DOWN_AFTER_FAILURES = 5


class Poller:
    def __init__(
        self, client: WiimClient, store: StateStore, art: ArtCache, config: Config
    ) -> None:
        self._client = client
        self._store = store
        self._art = art
        self._config = config
        self._failures = 0
        self._ever_succeeded = False
        self._track_key: str | None = None
        self._last_status = ""
        self._art_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        while True:
            delay = await self._tick()
            await asyncio.sleep(delay)

    async def aclose(self) -> None:
        if self._art_task and not self._art_task.done():
            self._art_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._art_task

    async def _tick(self) -> float:
        try:
            status = await self._client.player_status()
        except WiimUnavailable as e:
            return self._on_failure(e)
        return await self._on_success(status)

    def _on_failure(self, error: WiimUnavailable) -> float:
        self._failures += 1
        # 前回取得した表示内容は保持し、conn だけを落とす。
        # 表示できる値をまだ一度も得ていない間は stale にならず down のままとする
        stale = self._ever_succeeded and self._failures < DOWN_AFTER_FAILURES
        conn = CONN_STALE if stale else CONN_DOWN
        self._store.apply(conn=conn)
        delay = min(
            self._config.poll_interval_playing * 2 ** (self._failures - 1),
            self._config.poll_max_interval,
        )
        logger.warning("poll failed (attempt %d, retry in %.0fs): %s", self._failures, delay, error)
        return delay

    async def _on_success(self, status: PlayerStatus) -> float:
        recovered = self._store.get("conn") != CONN_OK
        self._failures = 0
        self._ever_succeeded = True
        self._store.apply(
            status=status.status,
            vol=status.vol,
            muted=status.muted,
            title=status.title,
            artist=status.artist,
            album=status.album,
            conn=CONN_OK,
        )

        if self._needs_meta(status, recovered):
            await self._refresh_meta()
        self._track_key = status.track_key
        self._last_status = status.status
        return self._interval(status)

    def _needs_meta(self, status: PlayerStatus, recovered: bool) -> bool:
        if self._track_key != status.track_key:
            return True
        if status.status == "play" and self._last_status in ("stop", "pause"):
            return True
        return recovered

    async def _refresh_meta(self) -> None:
        try:
            meta = await self._client.meta_info()
        except WiimUnavailable as e:
            logger.warning("cannot fetch metadata: %s", e)
            return

        changes = {
            key: value
            for key, value in (
                ("title", meta.title),
                ("artist", meta.artist),
                ("album", meta.album),
            )
            if value
        }
        if changes:
            self._store.apply(**changes)

        if meta.album_art_uri:
            self._start_art(meta.album_art_uri)
        else:
            self._store.apply(art=None)

    def _start_art(self, uri: str) -> None:
        """アートの取得は別タスクにする。取得の遅延で状態更新を止めないため。"""
        cached = self._art.get(self._art.key_for(uri))
        if cached is not None:
            self._store.apply(art=self._art.path_for(self._art.key_for(uri)))
            return
        if self._art_task and not self._art_task.done():
            self._art_task.cancel()
        self._art_task = asyncio.create_task(self._load_art(uri))

    async def _load_art(self, uri: str) -> None:
        path = await self._art.fetch(uri)
        self._store.apply(art=path)

    def _interval(self, status: PlayerStatus) -> float:
        # 消灯中は誰も見ていないため、さらに間隔を落とす
        if self._store.get("idle"):
            return self._config.poll_interval_idle
        if status.status == "play":
            return self._config.poll_interval_playing
        return self._config.poll_interval_paused
