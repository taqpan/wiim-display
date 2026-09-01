"""バックライトの制御と消灯判定。

消灯は sysfs への輝度書き込みで行う。X の DPMS は使わない。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .state import StateStore

logger = logging.getLogger(__name__)

# 消灯判定を行う間隔。IDLE_TIMEOUT に対して十分細かければよい
CHECK_INTERVAL = 1.0


class Backlight:
    """`BACKLIGHT_PATH` が空、または書き込めない場合は制御を行わない。"""

    def __init__(self, path: str) -> None:
        self._path = Path(path) if path else None
        self._level: int | None = None

    @property
    def enabled(self) -> bool:
        return self._path is not None

    def set_level(self, level: int) -> None:
        if self._path is None or level == self._level:
            return
        try:
            self._path.write_text(f"{level}\n", encoding="ascii")
        except OSError as e:
            logger.error("cannot write brightness, disabling control: %s: %s", self._path, e)
            self._path = None
            return
        self._level = level
        logger.debug("brightness: %d", level)


class IdleController:
    """再生中でなく操作もない状態が続いたら消灯し、操作で復帰する。

    再生中は無操作が続いても消灯しない。再生が止まった時刻と最後に操作された時刻の
    新しいほうを起点として、`IDLE_TIMEOUT` を数える。
    """

    def __init__(
        self, store: StateStore, backlight: Backlight, timeout: float, on: int, idle: int
    ) -> None:
        self._store = store
        self._backlight = backlight
        self._timeout = timeout
        self._on_level = on
        self._idle_level = idle
        self._since = 0.0

    def start(self) -> None:
        """起動時は必ず点灯させる。前回の輝度を引き継がない。"""
        self._backlight.set_level(self._on_level)
        self._store.apply(idle=False)
        self._since = asyncio.get_running_loop().time()

    def note_activity(self) -> None:
        self._since = asyncio.get_running_loop().time()
        if self._store.get("idle"):
            self._wake()

    async def run(self) -> None:
        while True:
            self._evaluate()
            await asyncio.sleep(CHECK_INTERVAL)

    def _evaluate(self) -> None:
        now = asyncio.get_running_loop().time()
        if self._store.get("status") == "play":
            self._since = now
        if self._store.get("idle"):
            return
        if now - self._since >= self._timeout:
            self._store.apply(idle=True)
            self._backlight.set_level(self._idle_level)
            logger.info("backlight off")

    def _wake(self) -> None:
        self._store.apply(idle=False)
        self._backlight.set_level(self._on_level)
        logger.info("backlight on")
