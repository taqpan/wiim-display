"""表示状態の保持。プロセス内に1つだけ持ち、永続化はしない。"""

from __future__ import annotations

from typing import Any

CONN_OK = "ok"
CONN_STALE = "stale"
CONN_DOWN = "down"

_INITIAL: dict[str, Any] = {
    "status": "stop",
    "vol": 0,
    "muted": False,
    "title": "",
    "artist": "",
    "album": "",
    "art": None,
    "conn": CONN_DOWN,
    "idle": False,
}


class StateStore:
    def __init__(self) -> None:
        self._rev = 0
        self._fields: dict[str, Any] = dict(_INITIAL)

    @property
    def rev(self) -> int:
        return self._rev

    def get(self, key: str) -> Any:
        return self._fields[key]

    def apply(self, **changes: Any) -> bool:
        """値が実際に変わったときだけ `rev` を進める。変化があれば True を返す。"""
        unknown = set(changes) - set(_INITIAL)
        if unknown:
            raise KeyError(f"unknown state keys: {sorted(unknown)}")

        updated = {k: v for k, v in changes.items() if self._fields[k] != v}
        if not updated:
            return False
        self._fields.update(updated)
        self._rev += 1
        return True

    def snapshot(self) -> dict[str, Any]:
        return {"rev": self._rev, **self._fields}
