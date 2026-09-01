# wiim-display

WiiM Pro を Raspberry Pi から HTTP API 経由で操作・表示する。
ラズパイに接続した小型タッチモニターに再生中の楽曲情報を表示し、簡単な再生操作を行う。

## 構成

- **本体**: Raspberry Pi 3 Model B + Freenove 5インチ DSI タッチモニター（800x480、横向き）
- **表示**: Pi 上の Python 常駐サーバが画面を配信し、Chromium をキオスクモードで全画面表示する
- **制御**: WiiM Pro の HTTP API をサーバ側から呼び出す

ブラウザは WiiM に直接アクセスしない。WiiM との通信・状態管理・画像変換はすべてサーバ側に集約する。

## ドキュメント

| ファイル | 内容 |
|---|---|
| [.claude/CLAUDE.md](.claude/CLAUDE.md) | 要件（ハードウェア構成、機能要件、開発環境） |
| [docs/setup-dev.md](docs/setup-dev.md) | 開発環境のセットアップ手順 |
| [docs/setup-pi.md](docs/setup-pi.md) | Raspberry Pi 実機のセットアップ手順 |

## 設定

環境依存の値は `.env` に置く。リポジトリにはコミットしない。
設定項目の一覧と既定値は [.env.example](.env.example) を参照。

## 実行形態

- **開発**: WSL2 上の Docker コンテナでサーバを起動し、Windows 側のブラウザから `http://localhost:8080` で確認する。
  操作は `task`（go-task）に集約している。手順は [docs/setup-dev.md](docs/setup-dev.md) を参照
- **本番**: Pi 上で systemd により Python サーバを起動し、Chromium キオスクから参照する

```bash
task setup   # .env の用意とイメージのビルド
task dev     # サーバ起動
```

## モックモード

`.env` の `WIIM_MOCK=1` で有効になる。**開発用 `.env` の既定値はこちら。**
WiiM 実機に接続せず固定データを返すため、WiiM が手元になくても画面のレイアウトを調整できる。

- 画面上部に dev バーが出る。ボタンで表示シナリオを切り替えられる
  （長い日本語タイトル、アート無し、ミュート、音量0/100、停止中、通信断など）
- `static/` を編集すると、ページをリロードせずに CSS が差し替わる
- `?frame=1` を付けると 800x480 の枠を表示する

**この状態では画面の操作は WiiM に届かない。** サーバがメモリ上に持つ状態が変わるだけで、
前の曲 / 次の曲にいたっては何も起きない。実機を操作するには `WIIM_MOCK=0` にして起動する。

| | `WIIM_MOCK=1`（既定） | `WIIM_MOCK=0` |
|---|---|---|
| WiiM への接続 | しない | する |
| 表示内容 | 固定データ | 実機の再生状態 |
| 画面からの操作 | 実機に届かない | 実機に届く |

シナリオ切替と CSS の差し替えは `DEV_MODE=1` の側の機能で、`WIIM_MOCK` とは独立している。
`WIIM_MOCK=0` のまま実機の状態を表示しつつ、dev バーでシナリオを確認することもできる。

## ライセンス

MIT License（[LICENSE](LICENSE)）
