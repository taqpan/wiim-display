"""WiiM への疎通確認 CLI。"""

from __future__ import annotations

import asyncio
import sys

from .config import load_config
from .wiim_client import WiimClient, WiimUnavailable


async def _probe() -> int:
    config = load_config()
    if not config.wiim_host:
        print("WIIM_HOST is not set; check .env", file=sys.stderr)
        return 2

    client = WiimClient(config.wiim_host, config.wiim_timeout)
    try:
        status = await client.player_status()
        meta = await client.meta_info()
    except WiimUnavailable as e:
        print(f"cannot connect to {config.wiim_host}: {e}", file=sys.stderr)
        return 1
    finally:
        await client.close()

    print(f"host:   {config.wiim_host}")
    print(f"status: {status.status}  vol: {status.vol}  muted: {status.muted}")
    print(f"title:  {meta.title or status.title}")
    print(f"artist: {meta.artist or status.artist}")
    print(f"album:  {meta.album or status.album}")
    print(f"art:    {meta.album_art_uri or '(none)'}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_probe()))


if __name__ == "__main__":
    main()
