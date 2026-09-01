# Raspberry Pi 実機セットアップ手順

Raspberry Pi 3 Model B を本プロジェクトの表示端末として構成する手順。

- §0 から §7 まで順に実施する
- §6 以降はアプリケーション本体の実装を前提とする。実装前は §5 までを適用しておく
- 問題が起きた場合は §10 を参照する

## 0. 必要なもの

- Raspberry Pi 3 Model B、5V/2.5A 以上の電源
- microSD カード 8GB 以上（信頼できるメーカーのもの）
- Freenove 5インチ タッチスクリーンモニター（FNK0078 シリーズ、800x480 DSI）
- 有線 LAN 接続
- WiiM Pro に固定IPアドレスを割り当て済みであること（ルータ側の DHCP 予約を推奨）
- 作業用 PC（以降の作業は SSH で行う）

---

## 1. OS の書き込み

Raspberry Pi Imager を使用する。

1. OS の選択で **Raspberry Pi OS (other) → Raspberry Pi OS Lite (32-bit)** を選ぶ
2. 「設定を編集する」で以下を設定してから書き込む
   - ホスト名: `wiim-display`
   - ユーザー名: `pi`、パスワードを設定する
   - SSH を有効化し、公開鍵認証を設定する
   - ロケール: タイムゾーン `Asia/Tokyo`、キーボードレイアウト `jp`

## 2. 初回起動と基本設定

microSD を挿し、DSI モニターと有線 LAN を接続して起動する。SSH で接続して以下を実行する。

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

構成を確認する。Raspberry Pi OS 13 (trixie) / armhf での動作を確認済み。

```bash
. /etc/os-release; echo "$PRETTY_NAME"   # Raspbian GNU/Linux 13 (trixie)
dpkg --print-architecture                # armhf
```

## 3. microSD への書き込みを減らす

microSD の寿命と書き込みストールを避けるための設定。

変更が必要なのは §3.1 のみで、§3.2 と §3.3 は trixie の既定で満たされているため確認だけを行う。

### 3.1 swap を zram 単独にする

**swap は zram のみを使い、microSD 上にファイルを置かない。**

trixie の既定は `zram+file`（ハイブリッド）で、zram のアイドルページを microSD 上の `/var/swap` へ定期的に書き戻す。`/etc/rpi/swap.conf` のドロップインで機構を変更する（`swap.conf(5)` / `rpi-swap-generator(8)`）。

```bash
sudo mkdir -p /etc/rpi/swap.conf.d
sudo tee /etc/rpi/swap.conf.d/50-zram-only.conf > /dev/null <<'EOF'
[Main]
Mechanism=zram
EOF
sudo reboot
```

- **設定変更後は再起動が必須。** `daemon-reload` ではユニットが再生成されるだけで、既存の swap ユニットは停止されない
- **`/var/swap` は自動的に削除される。** ファイルを使わない機構では既存ファイルが削除されストレージが解放される（`swap.conf(5)` の `[File]` セクション）
- zram 向けのカーネル最適化（`vm.page-cluster=0`）は `zram` 機構でも維持される
- **`zram-tools` はインストールしないこと。** trixie の `systemd-zram-generator` と二重に zram を管理することになる

検証:

```bash
swapon --show                       # /dev/zram0 のみ。他のデバイスやファイルが無いこと
cat /sys/block/zram0/backing_dev    # none
losetup -a                          # 出力なし
ls /var/swap                        # 存在しないこと
df -h /                             # ルートの空き容量が /var/swap のサイズ分だけ増えている
sysctl vm.page-cluster              # 0
```

### 3.2 ログの確認

trixie は既定で `Storage=volatile` を設定しており、journal は microSD に書かれない。

```bash
systemd-analyze cat-config systemd/journald.conf | grep -vE '^\s*#|^$'
```

`Storage=volatile` が含まれていればよい。

既定では `ForwardToSyslog=yes` も設定されている。rsyslog がインストールされていると `/var/log/syslog` へ書き込まれるため確認する。

```bash
dpkg -l rsyslog 2>/dev/null | tail -1
```

出力があれば停止する。trixie の Lite イメージには含まれないため、通常は出力がない。

```bash
sudo systemctl disable --now rsyslog
```

### 3.3 noatime の確認

Raspberry Pi OS の既定でルートパーティションは `noatime` でマウントされる。

```bash
findmnt -no SOURCE,FSTYPE,OPTIONS /
```

オプションに `noatime` が含まれていればよい。

## 4. モニターの確認

使用するパネルは **Freenove 5インチ タッチスクリーンモニター（FNK0078 シリーズ）**。800x480 IPS、5点静電容量タッチ、MIPI DSI 接続。

**設定作業は不要。** Pi 本体の `DISPLAY` コネクタに DSI リボンケーブルを接続するだけで、`config.txt` の既定値 `display_auto_detect=1` により自動認識される。

| 項目 | 期待値 |
|---|---|
| DRM コネクタ | `card0-DSI-1: connected`、モード `800x480` |
| 画面回転 | 不要（ネイティブが 800x480 の横向き） |
| タッチ | `10-0038 generic ft5x06` として自動認識。座標変換も不要 |
| バックライト | `/sys/class/backlight/10-0045/`（`type=raw`、`max_brightness=255`） |
| 追加の overlay | 不要（`dtoverlay=vc4-kms-v3d` のみで動作） |

### 4.1 認識と表示の確認

```bash
cat /sys/class/drm/card0-DSI-1/status    # connected
head -1 /sys/class/drm/card0-DSI-1/modes # 800x480
grep -A1 ft5x06 /proc/bus/input/devices  # タッチデバイス
ls /sys/class/backlight/                 # 10-0045
```

**sysfs の確認だけで済ませず、パネルに像が出ることを目視で確かめる。** DRM が `connected` を報告することと、実際にパネルへ表示されることは別である。

```bash
sudo chvt 1
echo "HELLO PANEL" | sudo tee /dev/tty1
```

パネルに `HELLO PANEL` が表示されること。

### 4.2 バックライト

Raspberry Pi OS の既定の udev ルールにより、`brightness` は `root:video` の `0664` で作成される。サービス実行ユーザーが `video` グループに属していればよい。

```bash
groups                       # video が含まれることを確認する
sudo usermod -aG video pi    # 含まれない場合のみ実行し、再ログインする
```

動作確認:

```bash
echo 64  > /sys/class/backlight/10-0045/brightness   # 暗く表示される
echo 0   > /sys/class/backlight/10-0045/brightness   # 消灯する
echo 255 > /sys/class/backlight/10-0045/brightness   # 戻す
```

`sudo` なしで書き込めること、`0` で完全に消灯することを確認する。

- **テスト後は必ず `255` に戻すこと。** `systemd-backlight@.service` が輝度を保存し次回起動時に復元するため、`0` のまま再起動すると画面が真っ暗な状態で立ち上がる
- 輝度の応答は非線形で、`30` 以下は消灯と区別がつかない。減光表示に使える範囲は 64〜255

## 5. 表示層のインストール

```bash
sudo apt install -y --no-install-recommends \
  xserver-xorg xinit x11-xserver-utils xinput \
  openbox unclutter \
  chromium \
  fonts-noto-cjk
```

X を systemd から起動するため、`/etc/X11/Xwrapper.config` を作成する。

```
allowed_users=anybody
needs_root_rights=yes
```

tty1 の getty と競合するため無効化する。

```bash
sudo systemctl disable getty@tty1.service
```

### 5.1 Xorg 設定

**Raspberry Pi 向けの Xorg 設定を置く。無いと画面が真っ暗になる。** Raspberry Pi OS のデスクトップ版はこれらをイメージに同梱しているが、Lite に手で X を入れた場合は存在しない。

```bash
sudo mkdir -p /etc/X11/xorg.conf.d

sudo tee /etc/X11/xorg.conf.d/99-v3d.conf > /dev/null <<'EOF'
Section "OutputClass"
  Identifier "vc4"
  MatchDriver "vc4"
  Driver "modesetting"
  Option "PrimaryGPU" "true"
EndSection
EOF

sudo tee /etc/X11/xorg.conf.d/20-noglamor.conf > /dev/null <<'EOF'
Section "Device"
        Identifier "kms"
        Driver "modesetting"
        Option "AccelMethod" "msdri3"
        Option "UseGammaLUT" "off"
EndSection
EOF
```

- **`UseGammaLUT` `off` が要点。** VC4 のガンマ LUT 処理が原因で、X が正常にモードセットしたと報告しながらパネルには何も出ない状態になる
- `AccelMethod` は `glamor` ではなく `msdri3` を指定する
- `/usr/share/X11/xorg.conf.d/` は apt の管理下のため、`/etc` 側に置いて優先させる

### 5.2 X の表示を単体で確認する

**Chromium を繋ぐ前に、X が DSI パネルに映ることを確認する。** ここを飛ばすと、後段で画面が出ないときに X とブラウザのどちらが原因か切り分けられない。

X を 30 秒だけ起動し、画面全体を赤く塗る。

```bash
sudo xinit /bin/sh -c 'xsetroot -solid red; xrandr; sleep 30' -- :0 vt1 -keeptty
```

- **画面が赤くなること**
- `xrandr` は `DSI-1 connected 800x480+0+0` と、`800x480` のモード行に `*` が付いていることを示す

**`sudo` が必要。** SSH セッションのユーザーは `/dev/tty1` の所有者ではないため、付けないと VT を開けない。このとき Xorg のログは `/root/.local/share/xorg/Xorg.0.log` に出る。

### 5.3 フォントの削減（任意）

`fonts-noto-cjk` は Sans と Serif の両方を導入する。本プロジェクトは Sans のみを使う。

```bash
sudo rm /usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc
sudo fc-cache -fv
```

---

## 6. アプリケーションの配置

アプリケーションは開発機から scp で転送する。

転送先を用意する。

```bash
# Pi 側
sudo mkdir -p /opt/wiim-display
sudo chown pi:pi /opt/wiim-display
```

### 6.1 転送する

送るパスを列挙する。実機に不要なものと、実機側で作るものを混入させないため。

```bash
# 開発機 (WSL2) 側
scp -r -C \
  ~/proj/wiim-display/src \
  ~/proj/wiim-display/static \
  ~/proj/wiim-display/tools \
  ~/proj/wiim-display/pyproject.toml \
  ~/proj/wiim-display/.env.example \
  pi@<Pi-IP>:/opt/wiim-display/
```

| scp のオプション | 意味 |
|---|---|
| `-r` | ディレクトリを再帰的に転送する |
| `-C` | 転送データを圧縮する |
| `-i <鍵ファイル>` | 秘密鍵を指定する（既定の鍵で繋がるなら不要） |
| `-P <ポート>` | SSH のポートを指定する。`ssh` の `-p` と異なり**大文字** |
| `-p` | 更新時刻とパーミッションを保持する |
| `-q` | 進捗表示を抑制する |

> **リポジトリのルートごと `scp -r` してはいけない。** 開発機の仮想環境（x86 バイナリ）まで転送され、さらに実機の `.env` が開発用の値で上書きされる。上記のように送るパスを明示すること。

ホスト名は avahi が動いていれば `pi@wiim-display.local` でも解決できる。

### 6.2 Python 環境

```bash
# Pi 側
cd /opt/wiim-display
sudo apt install -y python3-venv libopenjp2-7   # Pillow の実行時依存
python3 -m venv .venv
.venv/bin/pip install -e .
```

Raspberry Pi OS は `/etc/pip.conf` で piwheels を参照するため、venv 内でも Pillow はビルド済み wheel が入る。

### 6.3 設定

```bash
cp .env.example .env
```

`.env` を編集する。実機で変更が必要な項目は以下。

| 変数 | 実機での値 |
|---|---|
| `WIIM_HOST` | WiiM Pro の固定IPアドレス |
| `SERVER_HOST` | `127.0.0.1` |
| `BACKLIGHT_PATH` | `/sys/class/backlight/10-0045/brightness` |
| `ALLOW_POWER` | `1`（§7.3 の sudoers 設定が前提）|
| `DEV_MODE` / `WIIM_MOCK` | ともに `0` |

### 6.4 疎通確認

```bash
.venv/bin/python -m wiim_display.probe
```

WiiM の再生状態が表示されれば疎通できている。

## 7. systemd への登録

### 7.1 サーバ

`/etc/systemd/system/wiim-display.service`:

```ini
[Unit]
Description=WiiM display server
After=network.target

[Service]
User=pi
Group=pi
SupplementaryGroups=video
WorkingDirectory=/opt/wiim-display
ExecStart=/opt/wiim-display/.venv/bin/python -m wiim_display.server
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- `.env` は `config.py` が `WorkingDirectory` から読み込む。`EnvironmentFile` は使わない
- **`network-online.target` を待たない。** サーバは通信失敗時に前回値を保持して動作を継続するため、ネットワークの起動完了を待つ必要がない

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wiim-display.service
curl -s http://127.0.0.1:8080/healthz
```

### 7.2 キオスク

`/home/pi/.xinitrc`:

```sh
#!/bin/sh
xset s off -dpms s noblank
unclutter -idle 0 &
openbox &

exec chromium \
  --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --disable-features=Translate,MediaRouter --check-for-update-interval=31536000 \
  --renderer-process-limit=1 --disable-pinch --overscroll-history-navigation=0 \
  --password-store=basic --use-mock-keychain \
  --user-data-dir=/dev/shm/kiosk --disk-cache-dir=/dev/shm/kiosk-cache \
  --disk-cache-size=8388608 \
  http://127.0.0.1:8080
```

Chromium のポリシーを置く。`--user-data-dir` を tmpfs に置いており毎起動でプロファイルが消えるため、設定はポリシーファイルで与える。

```bash
sudo mkdir -p /etc/chromium/policies/managed
sudo tee /etc/chromium/policies/managed/kiosk.json > /dev/null <<'EOF'
{
  "TranslateEnabled": false
}
EOF
```

翻訳バーは `--disable-features=Translate` では抑止できない場合がある。適用状況は Chromium で `chrome://policy` を開いて確認する。

`/etc/systemd/system/wiim-kiosk.service`:

```ini
[Unit]
Description=WiiM display kiosk
After=wiim-display.service
Wants=wiim-display.service
Conflicts=getty@tty1.service

[Service]
User=pi
PAMName=login
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
StandardInput=tty
StandardOutput=journal
StandardError=journal
ExecStart=/usr/bin/xinit /home/pi/.xinitrc -- :0 vt1 -keeptty -nolisten tcp
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> **`StandardInput=tty` と `-keeptty` はどちらも必須。** `TTYPath=` は標準入出力が端末に接続されている場合にのみ効く（`systemd.exec(5)`）ため、`StandardInput=tty` が無いと `TTYPath` が無効になり Xorg が VT を掌握できない。

```bash
chmod +x /home/pi/.xinitrc
sudo systemctl daemon-reload
sudo systemctl enable --now wiim-kiosk.service
```

モニターに画面が表示されることを確認する。

### 7.3 電源操作の許可

画面左下の電源アイコンからシャットダウンと再起動を行えるようにする。サーバはセッションを持たないため、対象コマンドだけを sudoers で許可する。

```bash
sudo tee /etc/sudoers.d/wiim-power > /dev/null <<'EOF'
pi ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot
EOF
sudo chmod 440 /etc/sudoers.d/wiim-power
sudo visudo -c
```

パスワードなしで実行できることを確認する。

```bash
sudo -n systemctl --dry-run poweroff && echo ok
```

`.env` の `ALLOW_POWER` を `1` にしてサーバを再起動すると、画面左下に電源アイコンが出る。

```bash
sudo systemctl restart wiim-display
```

## 8. 受け入れ基準の計測

RAM 予算と描画性能は開発環境では判定できないため、以下を実機で計測する。

| 項目 | 基準 |
|---|---|
| 定常CPU（再生中・画面表示中） | サーバ < 1%、Chromium < 3%（1コア比） |
| 総使用RAM | < 700 MB。zram 使用量が単調増加しないこと |
| タッチ → 視覚フィードバック | < 100 ms |
| タッチ → WiiM に反映 | < 700 ms |
| 曲変更 → 画面反映 | < 6 秒 |
| 24時間連続稼働 | Chromium の RSS が単調増加しないこと |

```bash
free -m                                    # 総使用RAM < 700MB
ps -eo rss,comm --sort=-rss | head         # Chromium の RSS
systemd-cgtop -1 -n 1                      # 定常CPU
swapon --show                              # zram の使用量
vcgencmd measure_temp                      # 参考
```

24時間稼働させたうえで、Chromium の RSS と zram 使用量が単調増加していないことを確認する。基準を超える場合は `.env` の `ART_SIZE` を下げる、画面の装飾を減らす、の順に対処する。

## 9. 更新手順

### 9.1 サービス再起動の許可

更新タスクは ssh 越しに `systemctl restart` を実行する。**非対話の ssh では sudo がパスワードを要求できず失敗する**ため、対象の2コマンドだけを sudoers で許可する。

```bash
sudo tee /etc/sudoers.d/wiim-deploy > /dev/null <<'EOF'
pi ALL=(root) NOPASSWD: /usr/bin/systemctl restart wiim-display, /usr/bin/systemctl restart wiim-kiosk
EOF
sudo chmod 440 /etc/sudoers.d/wiim-deploy
sudo visudo -c
```

sudoers はコマンドラインを完全一致で照合する。`systemctl restart wiim-display wiim-kiosk` のように1回でまとめると別のコマンドとして扱われ許可されないため、タスク側は1ユニットずつ呼び出している。

### 9.2 更新

開発機の Taskfile から実行する。宛先は引数で指定する。

```bash
# 開発機 (WSL2) 側
task deploy -- pi@wiim-display.local          # 転送してサーバとキオスクを再起動する
task deploy:static -- pi@wiim-display.local   # static/ だけを転送してキオスクを再起動する
task deploy:deps -- pi@wiim-display.local     # pyproject.toml の依存を変更したときに実行する
task pi:logs -- pi@wiim-display.local         # 実機のログを追尾する
```

`static/` 配下のみの変更であれば `deploy:static` で足りる。サーバの再起動を伴わないため速く、画面デザインの調整ではこの経路だけを繰り返す。

`.env` は転送されない。実機側の設定を変更する場合は Pi 上で直接編集する。

---

## 10. トラブルシュート

### 10.1 画面が真っ暗

上から順に切り分ける。

**1. パネル自体が生きているか**

```bash
sudo systemctl stop wiim-kiosk
sudo chvt 1
echo "PANEL OK" | sudo tee /dev/tty1
```

表示されなければ DRM/パネル層の問題。§4.1 に戻る。

**2. X 単体で表示できるか**

```bash
sudo systemctl stop wiim-kiosk
sudo xinit /bin/sh -c 'xsetroot -solid red; sleep 30' -- :0 vt1 -keeptty
```

赤くならない場合は **§5.1 の `/etc/X11/xorg.conf.d/` の2ファイルを置いたか確認する。** 無いと X は「モードセット成功」とログに出しながらパネルに何も出さない。**Xorg のログに `(EE)` が無いことは、表示できている根拠にならない。**

**3. Chromium が描画しているか**

X 単体で赤が出るなら原因は Chromium 側。ページの背景色がほぼ黒のため、描画されていないのか中身が出ていないのかを切り分ける。

```bash
sudo cp /home/pi/.xinitrc /home/pi/.xinitrc.bak
sudo sed -i 's|http://127.0.0.1:8080|"data:text/html,<body style=background:red>"|' /home/pi/.xinitrc
sudo systemctl restart wiim-kiosk
```

- 赤くなる → Chromium は正常。ページ側の問題（§10.2）
- 黒いまま → `.xinitrc` の Chromium 行に `--disable-gpu` → `--use-gl=egl` → `--disable-features=VizDisplayCompositor` を順に足して試す

確認後は `sudo cp /home/pi/.xinitrc.bak /home/pi/.xinitrc` で戻す。

### 10.2 ページの中身が表示されない

```bash
curl -s http://127.0.0.1:8080/api/state
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/static/app.js
journalctl -u wiim-display -b --no-pager | tail -30
```

JS のエラーを見る場合は `.xinitrc` の Chromium 行に `--enable-logging=stderr --v=1` を足すと `journalctl -u wiim-kiosk` に出る。

### 10.3 Xorg が起動しない

`~/.local/share/xorg/Xorg.0.log` の `(EE)` 行を確認する。

| メッセージ | 対処 |
|---|---|
| `xf86OpenConsole: VT_ACTIVATE failed: Operation not permitted` | ユニットに `StandardInput=tty` があるか確認する。無いと `TTYPath=` が効かず VT を掌握できない（§7.2）|
| `xf86OpenConsole: Cannot open virtual console 1 (Permission denied)` | SSH から手で `xinit` を実行した場合に出る。`sudo` を付ける（§5.2）|
| `Server is already active for display 0` | `wiim-kiosk.service` が動作中。`sudo systemctl stop wiim-kiosk` してから実行する |

`Xwrapper.config` の作成と `getty@tty1` の無効化（§5）も確認する。

### 10.4 起動失敗をログで追う

`Storage=volatile` のため再起動をまたいでログが残らず、`journalctl -b -1` が使えない。調査中は一時的に永続化する。

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=50M\n' \
  | sudo tee /etc/systemd/journald.conf.d/50-debug-persistent.conf
sudo systemctl restart systemd-journald
```

調査が終わったらこのファイルを削除して `systemd-journald` を再起動する。

### 10.5 その他

| 症状 | 確認 |
|---|---|
| WiiM に接続できない | `curl -k "https://<WIIM_HOST>/httpapi.asp?command=getPlayerStatus"`。IPアドレスと `-k`（自己署名証明書）が必要な点を確認する |
| 曲名が文字化けする | `getPlayerStatus` の `Title` は16進エンコードされた UTF-8。デコード処理を確認する |
| 日本語が豆腐になる | `fc-list :lang=ja` でフォントの導入を確認する |
| パネルが認識されない | `cat /sys/class/drm/card0-DSI-1/status` と `modes`。`config.txt` の `display_auto_detect=1` を確認する |
| タッチが反応しない | `grep ft5x06 /proc/bus/input/devices` で認識を確認する。DSI ケーブルの挿し直しも試す |
| バックライトが消灯しない | `.env` の `BACKLIGHT_PATH` と、`video` グループへの所属を確認する（§4.2） |
| 起動直後から画面が真っ暗 | アイドル消灯中に電源断が起きると `systemd-backlight` が消灯状態を復元する。`echo 255 \| sudo tee /sys/class/backlight/10-0045/brightness` で復旧する |
| `Unit dphys-swapfile.service does not exist` | trixie に `dphys-swapfile` は存在しない。正常な結果であり対処不要 |
