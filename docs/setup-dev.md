# 開発環境セットアップ手順

Windows + WSL2 上に開発環境を構築する手順。Python の実行はすべて Docker コンテナ内で行い、
ホスト側に venv を作らない。実機側の手順は [setup-pi.md](setup-pi.md) を参照。

## 1. 必要なもの

| 要件 | 備考 |
|---|---|
| WSL2 (Ubuntu 24.04) | 開発作業はこの中で完結する |
| Docker Desktop | Settings → Resources → **WSL Integration で対象ディストロを有効化**しておく |
| go-task | `task` コマンド。[インストール手順](https://taskfile.dev/installation/) |

WSL2 側に Python や venv を用意する必要はない。`python3` を直接使う手順は無い。

確認:

```bash
docker compose version
task --version
```

## 2. セットアップ

```bash
git clone <リポジトリURL> wiim-display
cd wiim-display
task setup
```

`task setup` は `.env` の作成（無い場合のみ `.env.example` から複製）とイメージのビルドを行う。

### 2.1 開発用の `.env`

作成された `.env` を開発用の値に変更する。

| 変数 | 開発環境での値 | 理由 |
|---|---|---|
| `WIIM_HOST` | WiiM Pro の固定IPアドレス | 検証コマンド（§4）が参照する |
| `SERVER_HOST` | `0.0.0.0` | コンテナ内で待ち受け、compose のポート公開でホストへ届ける |
| `BACKLIGHT_PATH` | 空 | 開発環境に sysfs のバックライトが無いため制御を無効化する |
| `DEV_MODE` | `1` | モック状態の切替と CSS ホットリロードを有効にする |
| `WIIM_MOCK` | `1` | WiiM 実機に接続せず画面を確認する |

`.env` はコンテナに環境変数として注入していない。`config.py` が bind mount された `/app/.env` を
直接読むため、読み込み経路が本番と同じになる。変更を反映するにはサーバの再起動が必要。

## 3. 起動

```bash
task dev
```

Windows 側のブラウザから `http://localhost:8080` を開く。WSL2 の localhostForwarding によって
そのまま到達する。

- `src/` と `static/` はワークツリーごとコンテナに bind mount される。
  **CSS と HTML の編集は再ビルド不要で、ブラウザのリロードだけで反映される**
- Python コードの変更はサーバの再起動が必要（`Ctrl-C` → `task dev`）
- `pyproject.toml` の依存を変更したときだけ `task build` が必要

## 4. タスク一覧

```
task                タスク一覧を表示する
task setup          .env を用意してイメージをビルドする
task build          開発用イメージをビルドする
task dev            サーバを起動する（Ctrl-C で停止）
task down           コンテナを停止して削除する
task logs           サーバのログを追尾する
task shell          コンテナ内のシェルに入る
task lint           ruff で検査する
task fmt            ruff で整形し、自動修正できる指摘を直す
task probe          .env の WIIM_HOST へ疎通確認する
task api:status     getPlayerStatus のレスポンスが想定どおりか検証する
task api:meta       getMetaInfo のレスポンスとアルバムアートの到達性を検証する
task api:all        読み取り系をまとめて検証し、生レスポンスを保存する
task api:cmd        setPlayerCmd を送り、前後の getPlayerStatus の差分を出す

task deploy         アプリケーションを実機へ転送し、サーバとキオスクを再起動する
task deploy:static  static/ だけを転送し、キオスクを再起動する
task deploy:deps    実機で依存を再インストールし、サーバを再起動する
task pi:logs        実機のログを追尾する
```

`task dev` の実行中でも他のタスクは実行できる。`task dev` 以外は使い捨てのコンテナで動き、
ポートを占有しない。

`deploy` 系と `pi:logs` はコンテナを使わず、ホストから直接 ssh / scp を実行する。
**宛先は引数で指定する。**

```bash
task deploy -- pi@wiim-display.local
task deploy:static -- pi@192.168.1.50
```

実機側の準備は [setup-pi.md](setup-pi.md) を参照。

## 5. WiiM API 検証コマンド

`tools/check.py` は、WiiM HTTP API の外部仕様が実機と一致しているかを確かめる。プロダクトの
動作確認ではなく、**設計の前提そのものを実機に照らす**ためのものである。検証対象の実装を検証手段が
共有しないよう、`src/wiim_display/` からは独立させ、HTTP 呼び出しも標準ライブラリだけで実装している。

WiiM 実機への到達が前提となる。`WIIM_MOCK` の値には影響されない。

### 読み取り系（副作用なし）

```bash
task probe        # 疎通と応答時間
task api:status   # フィールドの過不足、16進デコード、数値が文字列で返るか
task api:meta     # metaData の構造、albumArtURI の到達性と画像実寸
task api:all      # 上記2つをまとめて実行し、生レスポンスを tools/captured/ に保存する
```

`tools/captured/` に保存した生レスポンスは、`mock.py` のフィクスチャの元データとして使う。
このディレクトリはコミットしない。

### 書き込み系（WiiM の再生状態が変わる）

```bash
task api:cmd -- pause
task api:cmd -- resume
task api:cmd -- next
task api:cmd -- vol 40
task api:cmd -- mute 1
```

コマンドを送出し、状態が変化するまで `getPlayerStatus` を再取得して、反映までの時間を範囲で
表示する。

`next` / `prev` が外部ソース経由で効くかどうかの確認にも使う。これらは AirPlay 等を経由する場合、
ソースアプリの対応状況に依存する。

### 反映時間の分布

```bash
task api:latency -- pause resume --repeat 30
task api:latency -- vol:40 vol:41 --repeat 30   # 音を止めずに計測する
```

2つのコマンドを交互に送り、反映までの時間を分布で出す。1回の計測では環境要因による外れ値を
捉えられないため、待機幅のような設計上の定数を決めるときはこちらを使う。

## 6. トラブルシュート

| 症状 | 確認 |
|---|---|
| `docker` が見つからない | Docker Desktop が起動しているか、WSL Integration が有効か |
| ブラウザから繋がらない | `.env` の `SERVER_HOST` が `0.0.0.0` か。`curl http://localhost:8080/healthz` |
| CSS を編集しても反映されない | `DEV_MODE=1` か（静的ファイルに `Cache-Control: no-store` が付く） |
| ワークツリーに root 所有のファイルができる | `task build` を実行し直す。ホストの uid/gid をビルド時に渡している |
| `task probe` が接続失敗する | `.env` の `WIIM_HOST`。WSL2 から `ping <WIIM_HOST>` が通るか |
| 依存を追加したのに import できない | `task build` でイメージを再ビルドする |
