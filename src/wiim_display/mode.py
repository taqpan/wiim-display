"""表示モードの自動切り替え。"""

from __future__ import annotations

import asyncio
import logging

from .state import CONN_DOWN, MODE_CLOCK, MODE_MUSIC, StateStore

logger = logging.getLogger(__name__)

# 切り替え判定を行う間隔。AUTO_CLOCK_DELAY に対して十分細かければよい
CHECK_INTERVAL = 1.0


def has_track(store: StateStore) -> bool:
    """楽曲画面に表示すべき曲があるか。一時停止中は曲があるものとして扱う。

    WiiM は停止後も直前の曲名を返すことがあるため、曲名の有無だけでは判定しない。
    """
    if store.get("conn") == CONN_DOWN or store.get("status") == "stop":
        return False
    return bool(store.get("title") or store.get("artist"))


class ModeController:
    """曲が無い状態が続いたら時計にし、曲が現れたら楽曲画面に戻す。

    曲が無くなった時刻と最後に操作された時刻の新しいほうを起点として
    `AUTO_CLOCK_DELAY` を数える。曲が無い間に手動で楽曲画面へ戻しても、
    放置すれば時計に戻る。曲がある間に手動で時計にした場合は、曲が
    いったん無くなってから再び現れるまで時計のままにする。
    """

    def __init__(self, store: StateStore, delay: float) -> None:
        self._store = store
        self._delay = delay
        self._since = 0.0
        self._had_track = False

    def start(self) -> None:
        self._since = asyncio.get_running_loop().time()
        self._had_track = has_track(self._store)

    def note_activity(self) -> None:
        self._since = asyncio.get_running_loop().time()

    def select(self, mode: str) -> None:
        self._store.apply(mode=mode)
        self.note_activity()

    async def run(self) -> None:
        while True:
            self._evaluate()
            await asyncio.sleep(CHECK_INTERVAL)

    def _evaluate(self) -> None:
        now = asyncio.get_running_loop().time()
        track = has_track(self._store)
        if track:
            self._since = now
            if not self._had_track and self._store.apply(mode=MODE_MUSIC):
                logger.info("mode: music (track appeared)")
        elif self._store.get("mode") == MODE_MUSIC and now - self._since >= self._delay:
            self._store.apply(mode=MODE_CLOCK)
            logger.info("mode: clock (no track)")
        self._had_track = track
