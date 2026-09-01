"""WiiM HTTP API の外部仕様が想定どおりかを実機で検証する CLI。

プロダクトの動作確認ではなく、設計の前提そのものを実機に照らして確かめるためのもの。
"""

from __future__ import annotations

import argparse
import io
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Any

from tools.wiim_raw import (
    WiimError,
    decode_hex_text,
    fetch_bytes,
    fetch_json,
    fetch_raw,
    save_capture,
)
from wiim_display.config import load_config

# 想定するフィールド
STATUS_FIELDS = [
    "status",
    "vol",
    "mute",
    "curpos",
    "totlen",
    "offset_pts",
    "loop",
    "mode",
    "type",
    "ch",
    "eq",
    "plicount",
    "plicurr",
    "alarmflag",
    "vendor",
]
STATUS_HEX_FIELDS = ["Title", "Artist", "Album"]
STATUS_NUMERIC_FIELDS = ["vol", "mute", "curpos", "totlen", "plicount", "plicurr"]
META_FIELDS = [
    "title",
    "artist",
    "album",
    "albumArtURI",
    "subtitle",
    "trackId",
    "bitDepth",
    "bitRate",
    "sampleRate",
]

OK = "  OK  "
NG = "  NG  "
INFO = " -- "


def _line(mark: str, text: str) -> None:
    print(f"[{mark}] {text}")


def _report_fields(payload: dict[str, Any], expected: list[str], label: str) -> bool:
    missing = [f for f in expected if f not in payload]
    extra = sorted(set(payload) - set(expected))
    if missing:
        _line(NG, f"{label}: 想定フィールドが欠落 -> {', '.join(missing)}")
    else:
        _line(OK, f"{label}: 想定フィールドが揃っている（{len(expected)} 件）")
    if extra:
        _line(INFO, f"{label}: 想定外のフィールド -> {', '.join(extra)}")
    return not missing


def _report_all_strings(payload: dict[str, Any], fields: list[str], label: str) -> bool:
    non_str = {
        f: type(payload[f]).__name__
        for f in fields
        if f in payload and not isinstance(payload[f], str)
    }
    if non_str:
        _line(NG, f"{label}: 文字列で返らないフィールドがある -> {non_str}")
        return False
    _line(OK, f"{label}: 数値も文字列で返る（{', '.join(fields)}）")
    return True


def check_status(host: str, timeout: float, save: bool, dump: bool) -> bool:
    print("== getPlayerStatus ==")
    payload, body = fetch_json(host, "getPlayerStatus", timeout)
    if dump:
        print(body)
    if save:
        _line(INFO, f"保存: {save_capture('getPlayerStatus', body)}")

    ok = _report_fields(payload, STATUS_FIELDS + STATUS_HEX_FIELDS, "getPlayerStatus")
    ok &= _report_all_strings(payload, STATUS_NUMERIC_FIELDS, "getPlayerStatus")

    for field in STATUS_HEX_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str):
            _line(NG, f"{field}: 文字列で返っていない -> {value!r}")
            ok = False
            continue
        decoded, kind = decode_hex_text(value)
        if kind == "hex":
            _line(OK, f"{field}: 16進デコード可 -> {decoded!r}")
        elif kind == "plain":
            _line(INFO, f"{field}: 16進エンコードされていない -> {value!r}")
        else:
            _line(NG, f"{field}: 16進だが UTF-8 として解釈できない -> {value!r}")
            ok = False

    _line(
        INFO,
        f"status={payload.get('status')!r} vol={payload.get('vol')!r} mute={payload.get('mute')!r}",
    )
    return ok


def check_meta(host: str, timeout: float, save: bool, dump: bool) -> bool:
    print("== getMetaInfo ==")
    payload, body = fetch_json(host, "getMetaInfo", timeout)
    if dump:
        print(body)
    if save:
        _line(INFO, f"保存: {save_capture('getMetaInfo', body)}")

    meta = payload.get("metaData")
    if not isinstance(meta, dict):
        _line(NG, "metaData オブジェクトが無い。レスポンス構造が想定と異なる")
        return False
    _line(OK, "metaData オブジェクト下に返っている")

    ok = _report_fields(meta, META_FIELDS, "metaData")

    # metaData は 16進エンコードなしで返る
    for field in ("title", "artist", "album"):
        value = meta.get(field)
        if not isinstance(value, str) or not value:
            continue
        _, kind = decode_hex_text(value)
        if kind == "hex":
            _line(NG, f"metaData.{field}: 16進エンコードされている（プレーンテキストの想定）")
            ok = False
        else:
            _line(OK, f"metaData.{field}: プレーンテキスト -> {value!r}")

    ok &= _check_album_art(meta.get("albumArtURI"), timeout)
    return ok


def _check_album_art(uri: Any, timeout: float) -> bool:
    if not isinstance(uri, str) or not uri.strip():
        _line(INFO, "albumArtURI が空。アート無しのトラックを再生している可能性がある")
        return True
    _line(INFO, f"albumArtURI: {uri}")
    try:
        data, content_type = fetch_bytes(uri, timeout)
    except WiimError as e:
        _line(NG, f"albumArtURI を取得できない: {e}")
        return False

    kib = len(data) / 1024
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            _line(
                OK,
                f"アート取得: {img.format} {img.width}x{img.height} {kib:.0f} KiB ({content_type})",
            )
            # サーバ側で縮小する前提は、配信サービスのアートが 1000〜1500px 級であること
            if max(img.width, img.height) < 600:
                _line(INFO, "実寸が想定より小さい。サーバ側縮小の前提を見直す余地がある")
    except Exception as e:
        _line(NG, f"画像として開けない: {e} ({kib:.0f} KiB, {content_type})")
        return False
    return True


def check_probe(host: str, timeout: float) -> bool:
    print(f"== 疎通確認: {host} ==")
    started = time.monotonic()
    payload, _ = fetch_json(host, "getPlayerStatus", timeout)
    elapsed = (time.monotonic() - started) * 1000
    _line(OK, f"getPlayerStatus に応答あり（{elapsed:.0f} ms）")
    _line(
        INFO,
        f"status={payload.get('status')!r} vol={payload.get('vol')!r} "
        f"mute={payload.get('mute')!r} vendor={payload.get('vendor')!r}",
    )
    return True


def _describe(field: str, value: Any) -> str:
    if field in STATUS_HEX_FIELDS:
        return repr(decode_hex_text(str(value))[0] or value)
    return repr(value)


@dataclass
class Measurement:
    """コマンド送出から状態反映までの1回分の計測結果。時刻はすべて送出時点からの ms。"""

    command: str
    changes: list[tuple[str, Any, Any]]
    ack_ms: float
    lower_ms: float
    upper_ms: float
    polls: int


def _build_command(spec: str) -> str:
    """`pause` や `vol:40` を setPlayerCmd の形に整える。"""
    return f"setPlayerCmd:{spec}"


def _measure(host: str, timeout: float, command: str, wait: float, interval: float) -> Measurement:
    """コマンドを送り、状態が反映されるまでの時間を範囲で測る。

    反映の時刻は直接は観測できず、「変化が無かった最後の取得」と「変化を検出した取得」の
    間にあることしか分からない。単一の値ではなくこの範囲を返す。
    """
    before, _ = fetch_json(host, "getPlayerStatus", timeout)
    watched = ["status", "vol", "mute", "plicurr", *STATUS_HEX_FIELDS]

    sent = time.monotonic()
    fetch_raw(host, command, timeout)
    acked = time.monotonic()

    deadline = sent + wait
    changes: list[tuple[str, Any, Any]] = []
    lower = acked  # ここまでは未反映だと確認できている時刻
    upper = acked
    polls = 0
    while time.monotonic() < deadline:
        time.sleep(interval)
        after, _ = fetch_json(host, "getPlayerStatus", timeout)
        upper = time.monotonic()
        polls += 1
        changes = [
            (f, before.get(f), after.get(f)) for f in watched if before.get(f) != after.get(f)
        ]
        if changes:
            break
        lower = upper

    return Measurement(
        command=command,
        changes=changes,
        ack_ms=(acked - sent) * 1000,
        lower_ms=(lower - sent) * 1000,
        upper_ms=(upper - sent) * 1000,
        polls=polls,
    )


def run_command(
    host: str,
    timeout: float,
    name: str,
    arg: str | None,
    wait: float,
    interval: float,
    limit_ms: float,
) -> bool:
    """setPlayerCmd を1回送り、反映までの時間を範囲で表示する。"""
    command = _build_command(f"{name}:{arg}" if arg else name)
    print(f"== {command} ==")

    m = _measure(host, timeout, command, wait, interval)
    _line(INFO, f"送出: {command}（{m.ack_ms:.0f} ms で応答）")

    if not m.changes:
        _line(
            NG,
            f"{wait:.1f} 秒待っても状態が変化しない（{m.polls} 回取得）。"
            "コマンドが効いていないか、送出前から同じ状態だった可能性がある",
        )
        return False

    for field, old, new_value in m.changes:
        _line(OK, f"{field}: {_describe(field, old)} -> {_describe(field, new_value)}")
    _line(
        INFO,
        f"反映: 送出から {m.lower_ms:.0f}〜{m.upper_ms:.0f} ms の間"
        f"（{m.polls} 回目の取得で検出、間隔 {interval * 1000:.0f} ms）",
    )
    if m.polls == 1:
        hint = (
            f"--interval を {interval * 1000:.0f} ms より小さくすると範囲が狭まる"
            if interval > 0
            else "間隔は既に 0 で、下限は HTTP の往復時間で決まっている"
        )
        _line(INFO, f"1回目の取得で既に反映されていた。実際の反映はこの下限より速い。{hint}")

    if m.lower_ms > limit_ms:
        _line(NG, f"COMMAND_CONFIRM_TIMEOUT ({limit_ms:.0f} ms) 内に反映されない")
        return False
    _line(OK, f"COMMAND_CONFIRM_TIMEOUT ({limit_ms:.0f} ms) 内に反映される")
    return True


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(q * len(ordered)), len(ordered) - 1)]


def _summarize(label: str, values: list[float]) -> None:
    _line(
        INFO,
        f"{label}: min {min(values):.0f} / median {statistics.median(values):.0f} / "
        f"p90 {_quantile(values, 0.9):.0f} / max {max(values):.0f} ms",
    )


def measure_latency(
    host: str,
    timeout: float,
    specs: list[str],
    repeat: int,
    wait: float,
    interval: float,
    settle: float,
    limit_ms: float,
) -> bool:
    """2つのコマンドを交互に送り、反映時間の分布を出す。

    1回の計測では環境要因による外れ値を捉えられないため、繰り返して分布で判断する。
    交互に送るのは、同じコマンドを続けても状態が変化せず反映を観測できないため。
    """
    commands = [_build_command(spec) for spec in specs]
    print(f"== 反映時間の分布: {' / '.join(commands)} ==")
    _line(
        INFO,
        f"{repeat} 回計測（取得間隔 {interval * 1000:.0f} ms、"
        f"1回あたりの上限 {wait:.1f} 秒、コマンド間の待機 {settle:.1f} 秒）",
    )

    # 1つ目のコマンドを先に送って状態を揃える。送出前から同じ状態だと変化を観測できないため
    fetch_raw(host, commands[0], timeout)
    time.sleep(settle)

    uppers: list[float] = []
    acks: list[float] = []
    failures = 0
    for i in range(repeat):
        if i:
            time.sleep(settle)
        m = _measure(host, timeout, commands[(i + 1) % len(commands)], wait, interval)
        if not m.changes:
            failures += 1
            _line(NG, f"{i + 1:2d}: {m.command} 変化を検出できず")
            continue
        uppers.append(m.upper_ms)
        acks.append(m.ack_ms)
        print(
            f"     {i + 1:2d}: {m.command:<24} 応答 {m.ack_ms:5.0f} ms / "
            f"反映 {m.lower_ms:.0f}〜{m.upper_ms:.0f} ms（{m.polls} 回取得）"
        )

    if not uppers:
        _line(NG, "有効な計測が1件も取れなかった")
        return False

    print()
    _summarize("反映（上限値）", uppers)
    _summarize("コマンド応答", acks)

    over = [v for v in uppers if v > limit_ms]
    if failures:
        _line(NG, f"変化を検出できなかった回数: {failures} / {repeat}")
    if over:
        _line(
            NG,
            f"COMMAND_CONFIRM_TIMEOUT ({limit_ms:.0f} ms) を超えた回数: "
            f"{len(over)} / {len(uppers)}（最大 {max(over):.0f} ms）",
        )
        return False
    _line(
        OK,
        f"全 {len(uppers)} 回とも COMMAND_CONFIRM_TIMEOUT ({limit_ms:.0f} ms) 以内に反映された",
    )
    return not failures


def main(argv: list[str] | None = None) -> int:
    # 接続先の解決だけはプロダクトの設定読み込みに相乗りする（.env のパーサを二重に持たないため）
    config = load_config()

    # 共通オプションはサブコマンド側にだけ置く。引数の位置による違いをなくすため
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default=None, help=".env の WIIM_HOST を上書きする")
    common.add_argument("--timeout", type=float, default=max(config.wiim_timeout, 5.0))
    common.add_argument(
        "--save", action="store_true", help="生レスポンスを tools/captured/ に保存する"
    )
    common.add_argument(
        "--json", dest="dump", action="store_true", help="生レスポンスを標準出力に出す"
    )

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("probe", parents=[common], help="疎通確認")
    sub.add_parser("status", parents=[common], help="getPlayerStatus を検証する")
    sub.add_parser("meta", parents=[common], help="getMetaInfo とアルバムアートを検証する")
    sub.add_parser("all", parents=[common], help="読み取り系をまとめて検証する")
    cmd = sub.add_parser(
        "command", parents=[common], help="setPlayerCmd を送る（WiiM の再生状態が変わる）"
    )
    cmd.add_argument("name", help="play / pause / resume / next / prev / vol / mute")
    cmd.add_argument("arg", nargs="?", help="vol は 0-100、mute は 0 または 1。他の操作では不要")
    cmd.add_argument("--wait", type=float, default=5.0, help="状態変化を待つ上限秒数")
    cmd.add_argument("--interval", type=float, default=0.1, help="getPlayerStatus の取得間隔（秒）")

    lat = sub.add_parser(
        "latency",
        parents=[common],
        help="2つのコマンドを交互に送り、反映時間の分布を出す（WiiM の再生状態が変わる）",
    )
    lat.add_argument(
        "specs",
        nargs=2,
        metavar="COMMAND",
        help="往復する2つの操作。引数はコロンで繋ぐ。例: pause resume / vol:49 vol:50",
    )
    lat.add_argument("--repeat", type=int, default=20, help="計測回数")
    lat.add_argument("--wait", type=float, default=5.0, help="1回あたり状態変化を待つ上限秒数")
    lat.add_argument("--interval", type=float, default=0.0, help="getPlayerStatus の取得間隔（秒）")
    lat.add_argument("--settle", type=float, default=1.0, help="コマンド間の待機秒数")

    args = parser.parse_args(argv)
    host = args.host or config.wiim_host
    if not host:
        print(
            "WIIM_HOST が未設定です。.env を確認するか --host を指定してください",
            file=sys.stderr,
        )
        return 2

    try:
        if args.mode == "probe":
            ok = check_probe(host, args.timeout)
        elif args.mode == "status":
            ok = check_status(host, args.timeout, args.save, args.dump)
        elif args.mode == "meta":
            ok = check_meta(host, args.timeout, args.save, args.dump)
        elif args.mode == "all":
            ok = check_status(host, args.timeout, args.save, args.dump)
            print()
            ok = check_meta(host, args.timeout, args.save, args.dump) and ok
        elif args.mode == "latency":
            ok = measure_latency(
                host,
                args.timeout,
                args.specs,
                args.repeat,
                args.wait,
                args.interval,
                args.settle,
                config.command_confirm_timeout * 1000,
            )
        else:
            ok = run_command(
                host,
                args.timeout,
                args.name,
                args.arg,
                args.wait,
                args.interval,
                config.command_confirm_timeout * 1000,
            )
    except WiimError as e:
        print(f"[{NG}] {e}", file=sys.stderr)
        return 1

    print()
    print("検証: 想定どおり" if ok else "検証: 想定と異なる点あり（上の NG を参照）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
