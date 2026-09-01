"""設定値の読み込み。

`.env` はカレントディレクトリから読み込む。systemd ユニットは `WorkingDirectory`、
compose は `working_dir` でこれを保証する。既に設定されている環境変数を優先し、
`.env` の値では上書きしない。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_env_file(root: Path | None = None) -> None:
    """`.env` を環境変数へ取り込む。ファイルが無い場合は何もしない。"""
    path = (root or Path.cwd()) / ENV_FILE
    if not path.is_file():
        return
    for key, value in _parse_env_file(path).items():
        os.environ.setdefault(key, value)


def _str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _int(key: str, default: int) -> int:
    return int(os.environ.get(key, "").strip() or default)


def _float(key: str, default: float) -> float:
    return float(os.environ.get(key, "").strip() or default)


def _bool(key: str, default: bool) -> bool:
    return (os.environ.get(key, "").strip() or str(int(default))) == "1"


@dataclass(frozen=True)
class Config:
    wiim_host: str
    wiim_timeout: float
    poll_interval_playing: float
    poll_interval_paused: float
    poll_interval_idle: float
    poll_max_interval: float
    command_confirm_interval: float
    command_confirm_timeout: float
    server_host: str
    server_port: int
    art_size: int
    backlight_path: str
    backlight_level_on: int
    backlight_level_idle: int
    idle_timeout: int
    allow_power: bool
    dev_mode: bool
    wiim_mock: bool
    log_level: str

    @property
    def backlight_enabled(self) -> bool:
        return bool(self.backlight_path)


def load_config(root: Path | None = None) -> Config:
    load_env_file(root)
    return Config(
        wiim_host=_str("WIIM_HOST", ""),
        wiim_timeout=_float("WIIM_TIMEOUT", 3.0),
        poll_interval_playing=_float("POLL_INTERVAL_PLAYING", 3.0),
        poll_interval_paused=_float("POLL_INTERVAL_PAUSED", 5.0),
        poll_interval_idle=_float("POLL_INTERVAL_IDLE", 15.0),
        poll_max_interval=_float("POLL_MAX_INTERVAL", 30.0),
        command_confirm_interval=_float("COMMAND_CONFIRM_INTERVAL", 0.1),
        command_confirm_timeout=_float("COMMAND_CONFIRM_TIMEOUT", 1.0),
        server_host=_str("SERVER_HOST", "127.0.0.1"),
        server_port=_int("SERVER_PORT", 8080),
        art_size=_int("ART_SIZE", 400),
        backlight_path=_str("BACKLIGHT_PATH", ""),
        backlight_level_on=_int("BACKLIGHT_LEVEL_ON", 255),
        backlight_level_idle=_int("BACKLIGHT_LEVEL_IDLE", 0),
        idle_timeout=_int("IDLE_TIMEOUT", 300),
        allow_power=_bool("ALLOW_POWER", False),
        dev_mode=_bool("DEV_MODE", False),
        wiim_mock=_bool("WIIM_MOCK", False),
        log_level=_str("LOG_LEVEL", "INFO").upper(),
    )
