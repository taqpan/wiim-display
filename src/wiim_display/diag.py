"""管理パネルに表示する診断情報の収集。

パネルを開いたときにだけ呼ばれる。常時ポーリングの経路には載せない。
"""

from __future__ import annotations

import asyncio
import re
import socket

THERMAL_PATH = "/sys/class/thermal/thermal_zone0/temp"
MEMINFO_PATH = "/proc/meminfo"

# vcgencmd get_throttled のビット割り当て。下位4bit が現在の状態、
# bit16-19 が起動以降に一度でも発生したかを表す
THROTTLE_NOW_MASK = 0x0000F
THROTTLE_PAST_MASK = 0xF0000


def _ip_address() -> str | None:
    """外向きの経路に割り当てられたアドレスを返す。UDP のため実際の送信は起きない。"""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 1))
            return sock.getsockname()[0]
        except OSError:
            return None


def _temperature_c() -> float | None:
    try:
        with open(THERMAL_PATH) as f:
            return round(int(f.read().strip()) / 1000, 1)
    except (OSError, ValueError):
        return None


def _memory_mb() -> tuple[int, int] | None:
    """(利用可能, 総量) を MiB で返す。"""
    values: dict[str, int] = {}
    try:
        with open(MEMINFO_PATH) as f:
            for line in f:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    values[key] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        return None
    if len(values) != 2:
        return None
    return values["MemAvailable"] // 1024, values["MemTotal"] // 1024


async def _throttle() -> tuple[str, str] | None:
    """(判定, 生の値) を返す。判定は ok / past / now。"""
    try:
        process = await asyncio.create_subprocess_exec(
            "vcgencmd",
            "get_throttled",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
    except OSError:
        return None
    if process.returncode != 0:
        return None
    match = re.search(r"throttled=(0x[0-9a-fA-F]+)", stdout.decode(errors="replace"))
    if match is None:
        return None
    raw = match.group(1)
    bits = int(raw, 16)
    if bits & THROTTLE_NOW_MASK:
        return "now", raw
    if bits & THROTTLE_PAST_MASK:
        return "past", raw
    return "ok", raw


async def collect() -> dict[str, object]:
    memory = _memory_mb()
    throttle = await _throttle()
    return {
        "hostname": socket.gethostname(),
        "ip": _ip_address(),
        "throttle": throttle[0] if throttle else None,
        "throttle_raw": throttle[1] if throttle else None,
        "temp_c": _temperature_c(),
        "mem_available_mb": memory[0] if memory else None,
        "mem_total_mb": memory[1] if memory else None,
    }
