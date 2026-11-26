# natdong — VPS NAT Railway via Telegram

Bot Telegram buat provisioning VPS NAT di Railway: tiap `/new` bikin project,
service Ubuntu 26.04 LTS dengan login `root`, lalu buka TCP proxy dan balikin
perintah SSH-nya.

```
ssh root@<domain> -p <proxyPort>
```

Repo ini sengaja kecil dan tanpa dependency Python (stdlib saja), jadi bisa
diaktifkan lagi kapan aja di mesin mana pun.

## Syarat

- Python 3.10+
- `railway` CLI ≥ 5.75 di `PATH` ([install](https://docs.railway.com/cli))
- bot Telegram dari [@BotFather](https://t.me/BotFather)
- token Railway scope **account** (`rlwy_acct_…`) atau **workspace** (`rlwy_wksp_…`)

## Aktivasi ulang (dari nol)

```bash
git clone https://github.com/yzyz-arch/natdong.git
cd natdong

cp env.example /root/.config/railway-nat-bot.env   # atau path lain
nano /root/.config/railway-nat-bot.env             # isi BOT_TOKEN, ADMIN_IDS, BOT_SECRET
chmod 600 /root/.config/railway-nat-bot.env

# start.sh baca env dari path ini (lihat variabel ENV_FILE di dalamnya)
./start.sh
tail -f /root/.railway-nat-bot/bot.log
```

Atau jalan langsung tanpa daemon:

```bash
set -a; . ./env.example; set +a
python3 bot.py
```

Cek dulu tanpa Telegram/Railway:

```bash
python3 selftest.py     # harus "SEMUA CEK LULUS"
```

Di Telegram: `/settoken <railway-token>` → `/new sg` → dapat kredensial SSH.

## Kenapa backend-nya hybrid

CLI `railway` **nolak workspace token** (`rlwy_wksp_…`) karena di awal manggil
`me` → `Unauthorized`. GraphQL API-nya sendiri nerima token yang sama.

| Operasi | Jalur |
|---|---|
| project / service / environment / variable / startCommand / region | GraphQL `backboard.railway.com/graphql/v2` |
| TCP proxy, logs, scale, delete fallback | `railway` CLI dengan `-p -e -s` (tanpa `link`) |
| deploy | `serviceCreate` dengan `source.image` → nggak butuh docker lokal / `railway up` |

## Flavor

Cuma satu: **Ubuntu 26.04 LTS, login `root`, sshd port 22**.

- image `ubuntu:26.04`
- password dari variable `ROOT_PASSWORD` (default dari `SSH_PASSWORD` di env)
- `openssh-server` di-install saat container start lewat `startCommand`
- TCP proxy → app port 22

`startCommand` **wajib** bentuk shell (`bash -c '...'`). Kalau ditulis
`apt-get … && …` langsung, Railway exec sebagai satu nama binary dan container
langsung `CRASHED`.

## File

| File | Fungsi |
|---|---|
| `bot.py` | dispatcher + handler `/start /settoken /deltoken /new /list /info /logs /del` |
| `tg.py` | Telegram Bot API client (long polling, prefer IPv4) |
| `railway_api.py` | GraphQL client: project/service/variable/deployment/startCommand/region |
| `railway_cli.py` | wrapper CLI: tcp-proxy, logs, scale; parser endpoint + redaction token |
| `provision.py` | pipeline create/destroy satu instance |
| `store.py` | sqlite: token user (obfuscated), instance, migrasi kolom |
| `config.py` | env config |
| `selftest.py` | test tanpa Telegram & tanpa token |
| `start.sh` / `stop.sh` | daemon pakai pidfile + supervisor (bot crash → auto-restart 5s) |
| `railway-nat-bot.service` | unit systemd |

## Environment

| Var | Default | Keterangan |
|---|---|---|
| `BOT_TOKEN` | — | wajib, dari @BotFather |
| `ADMIN_IDS` | kosong | bypass quota, bisa akses instance user lain |
| `ALLOWED_IDS` | kosong | kalau diisi → whitelist user, kosong = publik |
| `DATA_DIR` | `~/.railway-nat-bot` | sqlite + log + pidfile |
| `MAX_INSTANCES` | `3` | quota per user (instance `failed` nggak dihitung) |
| `SSH_PASSWORD` | `Ariel123` | password tetap semua instance (kosongkan = random 24 char) |
| `CREDIT` | `by @yazinul96` | footer di pesan `/new`, `/list`, `/info` |
| `DEFAULT_REGION` | `sg` | `sg` / `us` / `eu` |
| `BOT_SECRET` | `railway-nat-bot` | salt obfuscation token di sqlite |
| `CMD_TIMEOUT` | `180` | timeout per command CLI |

## Ketahanan

- `tg.api()` nangkep `URLError`, `TimeoutError`, dan `OSError` → jadi `TgError`.
  Tanpa ini, satu read timeout bisa membunuh seluruh proses (kejadian nyata).
- `get_updates()` nggak pernah raise; error di-log maksimal sekali per menit.
- `poll_forever()` punya try/except di level loop + backoff, jadi nggak mati
  gara-gara handler error.
- `start.sh` bungkus bot pakai supervisor loop: exit code apa pun → hidup lagi
  5 detik kemudian. `stop.sh` membunuh satu process group (supervisor + bot).

## Batasan yang ketemu di lapangan

- **Rate limit workspace**: 1 project / 30 detik. Bot nangkep error ini.
- **Token workspace nggak bisa `railway whoami`/`link`** → validasi token lewat
  query `projects`, bukan `me`.
- **`railway up` gagal** dengan workspace token (`Indexing... prefix not found`),
  karena upload butuh project ter-link. Makanya deploy pakai image, bukan Dockerfile lokal.
- SSH lewat TCP proxy pakai port non-443. Di jaringan yang cuma ngebolehin
  outbound 443, koneksi SSH bakal timeout — itu batasan jaringan, bukan bug bot.
- Railway nggak kasih IP publik dedicated. Domain `*.proxy.rlwy.net` resolve ke
  edge IP bersama, routing terjadi by port.

## Keamanan

- Token Railway disimpan di `$DATA_DIR/bot.db`, mode `600`, di-XOR pakai
  keystream SHA-256 dari `BOT_SECRET` — **obfuscation**, bukan enkripsi kuat.
- Token nggak pernah dikirim balik ke chat; pesan `/settoken` dihapus.
- Default `root` + password di port publik itu sasaran brute force. Untuk
  produksi: pakai public key + `PermitRootLogin prohibit-password`, tambah
  `fail2ban`, atau matikan flavor password.
- Jangan pernah commit `bot.db`, env file, atau token ke repo ini.

## Lisensi

MIT.
