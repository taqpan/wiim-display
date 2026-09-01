"""システムの電源操作。

サーバは systemd サービスとして動きセッションを持たないため、logind の電源操作を
直接は行えない。sudoers で `systemctl poweroff` / `reboot` だけを許可し、そこを通す。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

ACTIONS = ("poweroff", "reboot")

# 応答を返してからクライアントが画面を切り替えるまでの猶予
DELAY = 1.0


async def run(action: str) -> None:
    await asyncio.sleep(DELAY)
    try:
        process = await asyncio.create_subprocess_exec(
            "sudo",
            "-n",
            "systemctl",
            action,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        logger.error("cannot execute %s: %s", action, e)
        return
    _, stderr = await process.communicate()
    if process.returncode != 0:
        logger.error("%s failed: %s", action, stderr.decode(errors="replace").strip())
