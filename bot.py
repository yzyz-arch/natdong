"""Telegram bot: bikin NAT VPS di Railway on demand."""
import sys
import time

import config
import provision
import railway_api as api
import railway_cli as rw
import store
import tg

LAST_NEW: dict[int, float] = {}
NEW_COOLDOWN = 30  # detik

HELP = """<b>railway-nat-bot</b>

Bikin VPS NAT di Railway lewat chat. Container Debian + sshd, diakses via TCP proxy.

<b>Setup</b>
<code>/settoken &lt;account-token&gt;</code> — token Railway (Account Settings → Tokens). Pesan lo gue hapus setelah disimpan.
<code>/deltoken</code> — hapus token dari storage bot

<b>Instance</b>
<code>/new [sg|us|eu]</code> — bikin VPS baru: Ubuntu 26.04 LTS, login <code>root</code>, port 22
<code>/list</code> — daftar VPS lo
<code>/info &lt;id&gt;</code> — detail + perintah SSH
<code>/logs &lt;id&gt;</code> — 60 baris log terakhir
<code>/del &lt;id&gt;</code> — hapus project Railway-nya

<b>Catatan</b>
- Token harus scope <i>account</i> atau <i>workspace</i> (rlwy_acct_ / rlwy_wksp_). Project token nggak bisa
- Deploy dari <code>ubuntu:26.04</code>, bukan build Dockerfile — siap ~1 menit
- <code>openssh-server</code> di-bootstrap saat container start, jadi ~30 detik lebih lama
- Workspace dibatasi 1 project / 30 detik, jadi /new ada jeda
- sshd di container port 2222, diakses lewat TCP proxy Railway
"""


def credit_line() -> str:
    return f"\n\n<i>{tg.esc(config.CREDIT)}</i>"


def success_text(res) -> str:
    return (
        f"<b>VPS siap</b> · <code>{tg.esc(res['id'])}</code> · {tg.esc(res['flavor'])}\n"
        f"<code>ssh {tg.esc(res['user'])}@{res['domain']} -p {res['port']}</code>\n"
        f"password: <code>{tg.esc(res['password'])}</code>\n"
        f"project: <code>{tg.esc(res['project'])}</code> · {tg.esc(res['region'])}\n\n"
        "Build kadang masih jalan ~1 menit setelah ini. Kalau SSH ditolak, coba lagi."
        + credit_line()
    )


def fmt_instance(inst) -> str:
    status = inst["status"]
    tone = {"active": "aktif", "creating": "proses", "failed": "gagal"}.get(status, status)
    return (
        f"<b>{tg.esc(inst['id'])}</b> · {tg.esc(tone)}\n"
        f"<code>{tg.esc(provision.ssh_command(inst))}</code>\n"
        f"password: <code>{tg.esc(inst['password'])}</code>\n"
        f"project: <code>{tg.esc(inst['project_name'])}</code> · {tg.esc(inst['region'])}"
    )


def require_token(user_id: int, chat_id: int) -> str | None:
    token = store.get_token(user_id)
    if not token:
        tg.send(chat_id, "Belum ada token. Kirim <code>/settoken &lt;token&gt;</code> dulu.")
    return token


def cmd_start(msg):
    uid = msg["from"]["id"]
    if not config.is_allowed(uid):
        tg.send(msg["chat"]["id"], "Bot ini private. Minta akses ke admin.")
        return
    tg.send(msg["chat"]["id"], HELP)


def cmd_settoken(msg):
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    _, args = tg.parse_command(msg["text"])
    tg.delete(chat, msg["message_id"])  # jangan biarin token nangkring di chat
    if not args:
        tg.send(chat, "Format: <code>/settoken &lt;token&gt;</code>")
        return
    token = args[0].strip()
    if len(token) < 20:
        tg.send(chat, "Token keliatan kepotong. Cek lagi.")
        return
    try:
        info = api.validate_token(token)   # workspace token nggak bisa query `me`
    except api.ApiError as exc:
        tg.send(chat, f"Token ditolak Railway: <code>{tg.esc(exc)}</code>")
        return
    store.set_token(uid, token)
    tg.send(chat, f"Token disimpan — {tg.esc(info)}. Lanjut <code>/new</code>.")


def cmd_deltoken(msg):
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    tg.delete(chat, msg["message_id"])
    store.del_token(uid)
    tg.send(chat, "Token dihapus dari storage bot.")


def cmd_new(msg):
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    token = require_token(uid, chat)
    if not token:
        return
    _, raw_args = tg.parse_command(msg["text"])
    args = [a.lower() for a in raw_args]
    alias = next((a for a in args if a in config.REGIONS), config.DEFAULT_REGION)
    flavor = next((a for a in args if a in provision.FLAVORS), provision.DEFAULT_FLAVOR)

    if not config.is_admin(uid) and store.count_instances(uid) >= config.MAX_INSTANCES:
        tg.send(chat, f"Kuota penuh ({config.MAX_INSTANCES} instance). Hapus dulu pakai /del.")
        return
    now = time.time()
    if now - LAST_NEW.get(uid, 0) < NEW_COOLDOWN:
        tg.send(chat, f"Sabar {int(NEW_COOLDOWN - (now - LAST_NEW[uid]))}s lagi.")
        return
    LAST_NEW[uid] = now

    status = tg.send(chat, f"Mulai provisioning ({tg.esc(flavor)})…")[0]
    mid = status["message_id"]

    def notify(step: str) -> None:
        tg.edit(chat, mid, f"<b>provisioning</b>\n{tg.esc(step)}")

    try:
        res = provision.create(token, uid, config.region_id(alias), notify, flavor=flavor)
    except (rw.RailwayError, api.ApiError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        tg.edit(chat, mid, f"<b>gagal</b>\n<code>{tg.esc(detail)}</code>")
        return
    except Exception as exc:
        tg.edit(chat, mid, f"<b>gagal</b>\n<code>{tg.esc(exc)}</code>")
        return

    tg.edit(chat, mid, success_text(res))


def cmd_list(msg):
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    rows = store.list_instances(uid)
    if not rows:
        tg.send(chat, "Belum ada instance. <code>/new</code> buat mulai.")
        return
    body = "\n\n".join(fmt_instance(r) for r in rows)
    tg.send(chat, f"<b>{len(rows)} instance</b>\n\n{body}{credit_line()}")


def _owned(msg) -> tuple[str, object] | tuple[None, None]:
    chat = msg["chat"]["id"]
    _, args = tg.parse_command(msg["text"])
    if not args:
        tg.send(chat, "Butuh id instance. Cek <code>/list</code>.")
        return None, None
    inst = store.get_instance(args[0].strip())
    if not inst or (inst["user_id"] != msg["from"]["id"] and not config.is_admin(msg["from"]["id"])):
        tg.send(chat, "Instance itu nggak ada di akun lo.")
        return None, None
    return args[0].strip(), inst


def cmd_info(msg):
    _, inst = _owned(msg)
    if inst:
        tg.send(msg["chat"]["id"], fmt_instance(inst) + credit_line())


def cmd_logs(msg):
    chat = msg["chat"]["id"]
    iid, inst = _owned(msg)
    if not inst:
        return
    token = require_token(msg["from"]["id"], chat)
    if not token:
        return
    if not (inst["project_id"] and inst["env_id"] and inst["service_id"]):
        tg.send(chat, "Instance ini belum punya id Railway lengkap, log nggak kebaca.")
        return
    try:
        out = rw.logs(token, inst["project_id"], inst["env_id"], inst["service_id"])
    except rw.RailwayError as exc:
        tg.send(chat, f"<code>{tg.esc(exc.stderr or exc)}</code>")
        return
    tg.send(chat, f"<b>log {tg.esc(iid)}</b>\n<pre>{tg.esc(out[-3500:])}</pre>")


def cmd_del(msg):
    chat = msg["chat"]["id"]
    iid, inst = _owned(msg)
    if not inst:
        return
    token = require_token(msg["from"]["id"], chat)
    if not token:
        return
    try:
        provision.destroy(token, iid)
    except (rw.RailwayError, api.ApiError) as exc:
        tg.send(chat, f"Gagal hapus: <code>{tg.esc(exc.stderr or exc)}</code>")
        return
    tg.send(chat, f"Instance <code>{tg.esc(iid)}</code> dihapus.")


HANDLERS = {
    "start": cmd_start,
    "help": cmd_start,
    "settoken": cmd_settoken,
    "deltoken": cmd_deltoken,
    "new": cmd_new,
    "list": cmd_list,
    "info": cmd_info,
    "logs": cmd_logs,
    "del": cmd_del,
}


def handle(msg: dict) -> None:
    cmd, _ = tg.parse_command(msg.get("text", ""))
    handler = HANDLERS.get(cmd)
    if not handler:
        return
    if not config.is_allowed(msg["from"]["id"]):
        tg.send(msg["chat"]["id"], "Bot ini private.")
        return
    handler(msg)


def main() -> int:
    if not config.BOT_TOKEN:
        print("BOT_TOKEN kosong", file=sys.stderr)
        return 1
    store.init()
    try:
        info = tg.me()
    except tg.TgError as exc:
        print(f"getMe gagal: {exc}", file=sys.stderr)
        return 1
    print(f"bot @{info.get('username')} jalan. backend=graphql+cli", flush=True)
    tg.poll_forever(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
