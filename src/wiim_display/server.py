"""aiohttp アプリケーションの構築と起動。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from . import diag, mock, power
from .art import ArtCache
from .backlight import Backlight, IdleController
from .config import Config, load_config
from .poller import Poller
from .state import CONN_OK, StateStore
from .wiim_client import PlayerStatus, WiimClient, WiimUnavailable

logger = logging.getLogger(__name__)

ART_CACHE_CONTROL = "public, max-age=31536000, immutable"

# 操作の指定から setPlayerCmd の引数を組み立てる
_SIMPLE_COMMANDS = {
    "play": "resume",
    "pause": "pause",
    "next": "next",
    "prev": "prev",
}


class CommandError(ValueError):
    pass


def build_command(action: str, value: Any) -> str:
    if action in _SIMPLE_COMMANDS:
        return f"setPlayerCmd:{_SIMPLE_COMMANDS[action]}"
    if action == "vol":
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise CommandError("vol requires an integer value in 0-100")
        return f"setPlayerCmd:vol:{value}"
    if action == "mute":
        if not isinstance(value, bool):
            raise CommandError("mute requires a boolean value")
        return f"setPlayerCmd:mute:{int(value)}"
    raise CommandError(f"unsupported action: {action!r}")


def apply_optimistic(store: StateStore, action: str, value: Any) -> None:
    """コマンドの結果を先に状態へ反映する。モックモードではこれが唯一の反映経路になる。"""
    if action == "play":
        store.apply(status="play")
    elif action == "pause":
        store.apply(status="pause")
    elif action == "vol":
        store.apply(vol=value)
    elif action == "mute":
        store.apply(muted=value)


def _status_key(status: PlayerStatus) -> tuple[Any, ...]:
    return (status.status, status.vol, status.muted, status.track_key)


async def confirm_command(app: web.Application, before: PlayerStatus) -> bool:
    """状態が変化するまで再取得する。上限で打ち切り、最後に取得した状態を反映する。

    固定待機にすると、通常時の応答を犠牲にするか、遅いときを取りこぼすかの
    どちらかになる。変化の検出で打ち切れば待機幅を決め打ちせずに済む。
    """
    config: Config = app["config"]
    client: WiimClient = app["client"]
    store: StateStore = app["store"]

    loop = asyncio.get_running_loop()
    deadline = loop.time() + config.command_confirm_timeout
    while loop.time() < deadline:
        await asyncio.sleep(config.command_confirm_interval)
        try:
            status = await client.player_status()
        except WiimUnavailable as e:
            logger.warning("cannot read status after command: %s", e)
            return False
        store.apply(
            status=status.status,
            vol=status.vol,
            muted=status.muted,
            title=status.title,
            artist=status.artist,
            album=status.album,
            conn=CONN_OK,
        )
        if _status_key(status) != _status_key(before):
            return True
    return False


def _assets_rev(static_dir: Path) -> int:
    return max((int(p.stat().st_mtime) for p in static_dir.rglob("*") if p.is_file()), default=0)


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(request.app["static_dir"] / "index.html")


async def handle_healthz(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def state_payload(app: web.Application, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """状態を返すすべての応答で同じ形にする。

    `assets_rev` の有無がクライアントにとって開発モードの判定そのものになるため、
    エンドポイントによって付いたり付かなかったりしてはならない。
    """
    store: StateStore = app["store"]
    config: Config = app["config"]
    payload = {"rev": store.rev, **fields} if fields else store.snapshot()
    if config.allow_power:
        payload["power"] = True
    if config.dev_mode:
        payload["assets_rev"] = _assets_rev(app["static_dir"])
    return payload


async def handle_state(request: web.Request) -> web.Response:
    app = request.app
    name = request.query.get("mock") if app["config"].dev_mode else None
    if not name:
        return web.json_response(state_payload(app))

    # シナリオは状態を置き換えず、その場の応答としてだけ返す
    fields = mock.scenario(name)
    if fields is None:
        raise web.HTTPNotFound(text=f"unknown scenario: {name}")
    return web.json_response(state_payload(app, fields))


async def handle_art(request: web.Request) -> web.Response:
    art: ArtCache = request.app["art"]
    data = art.get(request.match_info["key"])
    if data is None:
        raise web.HTTPNotFound()
    return web.Response(
        body=data,
        content_type="image/jpeg",
        headers={"Cache-Control": ART_CACHE_CONTROL},
    )


async def handle_command(request: web.Request) -> web.Response:
    app = request.app
    store: StateStore = app["store"]
    client: WiimClient | None = app["client"]

    try:
        body = await request.json()
    except ValueError as e:
        raise web.HTTPBadRequest(text="body is not valid JSON") from e
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="body must be an object")

    action = str(body.get("action", ""))
    value = body.get("value")
    try:
        command = build_command(action, value)
    except CommandError as e:
        raise web.HTTPBadRequest(text=str(e)) from e

    app["idle"].note_activity()

    if client is None:
        apply_optimistic(store, action, value)
        return web.json_response({**state_payload(app), "confirmed": True})

    before = await _current_status(client)
    try:
        response = await client.send(command)
    except WiimUnavailable as e:
        logger.warning("cannot send command: %s", e)
        raise web.HTTPBadGateway(text="cannot send command to WiiM") from e
    logger.info("sent: %s -> %s", command, response)

    apply_optimistic(store, action, value)
    confirmed = False if before is None else await confirm_command(app, before)
    return web.json_response({**state_payload(app), "confirmed": confirmed})


async def handle_diag(request: web.Request) -> web.Response:
    return web.json_response(await diag.collect())


async def handle_power(request: web.Request) -> web.Response:
    app = request.app
    if not app["config"].allow_power:
        raise web.HTTPForbidden(text="power actions are disabled")

    try:
        body = await request.json()
    except ValueError as e:
        raise web.HTTPBadRequest(text="body is not valid JSON") from e
    action = str(body.get("action", "")) if isinstance(body, dict) else ""
    if action not in power.ACTIONS:
        raise web.HTTPBadRequest(text=f"unsupported action: {action!r}")

    logger.info("power action: %s", action)
    # 応答を返しきってから実行するため、タスクにして待たない
    app["power_task"] = asyncio.create_task(power.run(action))
    return web.json_response({"accepted": action})


async def handle_wake(request: web.Request) -> web.Response:
    """画面へのタッチで消灯から復帰する。操作を伴わない接触もここで受ける。"""
    request.app["idle"].note_activity()
    return web.json_response(state_payload(request.app))


async def _current_status(client: WiimClient) -> PlayerStatus | None:
    try:
        return await client.player_status()
    except WiimUnavailable as e:
        logger.warning("cannot read status before command: %s", e)
        return None


@web.middleware
async def no_store_static(request: web.Request, handler: web.Handler) -> web.StreamResponse:
    """開発モードでは静的ファイルをキャッシュさせない。CSS 調整のたびに再読込させるため。"""
    response = await handler(request)
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


async def _start_background(app: web.Application) -> None:
    config: Config = app["config"]
    art: ArtCache = app["art"]
    await art.start()

    idle: IdleController = app["idle"]
    idle.start()
    app["idle_task"] = asyncio.create_task(idle.run())

    if config.wiim_mock:
        art.put(mock.ART_KEY, mock.art_bytes(config.art_size))
        app["store"].apply(**mock.SCENARIOS[mock.DEFAULT_SCENARIO])
        app["client"] = None
        logger.info("mock mode: not connecting to WiiM")
        return

    client = WiimClient(config.wiim_host, config.wiim_timeout)
    app["client"] = client
    poller = Poller(client, app["store"], art, config)
    app["poller"] = poller
    app["poller_task"] = asyncio.create_task(poller.run())


async def _stop_background(app: web.Application) -> None:
    for key in ("poller_task", "idle_task"):
        task: asyncio.Task[None] | None = app.get(key)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    poller: Poller | None = app.get("poller")
    if poller is not None:
        await poller.aclose()
    client: WiimClient | None = app.get("client")
    if client is not None:
        await client.close()
    await app["art"].close()
    # 消灯したまま終了すると輝度が永続化され、次回起動が真っ暗になる
    app["idle"].start()


def create_app(config: Config, root: Path) -> web.Application:
    middlewares = [no_store_static] if config.dev_mode else []
    app = web.Application(middlewares=middlewares)
    app["config"] = config
    app["static_dir"] = root / "static"
    app["store"] = StateStore()
    app["art"] = ArtCache(config.art_size, config.wiim_timeout, config.wiim_host)
    app["client"] = None
    app["idle"] = IdleController(
        app["store"],
        Backlight(config.backlight_path),
        config.idle_timeout,
        config.backlight_level_on,
        config.backlight_level_idle,
    )

    app.router.add_get("/", handle_index)
    app.router.add_get("/healthz", handle_healthz)
    app.router.add_get("/api/state", handle_state)
    app.router.add_post("/api/command", handle_command)
    app.router.add_post("/api/wake", handle_wake)
    app.router.add_post("/api/power", handle_power)
    app.router.add_get("/api/diag", handle_diag)
    app.router.add_get("/art/{key}.jpg", handle_art)
    app.router.add_static("/static/", app["static_dir"])

    app.on_startup.append(_start_background)
    app.on_cleanup.append(_stop_background)
    return app


def main() -> None:
    root = Path.cwd()
    config = load_config(root)
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logger.info(
        "starting: host=%s port=%d dev_mode=%s wiim_mock=%s",
        config.server_host,
        config.server_port,
        config.dev_mode,
        config.wiim_mock,
    )
    web.run_app(
        create_app(config, root),
        host=config.server_host,
        port=config.server_port,
        print=None,
    )


if __name__ == "__main__":
    main()
