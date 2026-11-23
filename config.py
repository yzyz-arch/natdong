"""Konfigurasi bot — semua dari environment."""
import os
from pathlib import Path


def _int_list(raw: str) -> list[int]:
    out = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                pass
    return out


BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path.home() / ".railway-nat-bot"))).expanduser()

# build context yang di-upload ke Railway
CONTEXT_DIR = Path(
    os.environ.get("CONTEXT_DIR", str(Path(__file__).resolve().parent.parent / "railway-nat"))
).expanduser()

# admin bisa pakai bot tanpa quota & bisa lihat semua instance
ADMIN_IDS = _int_list(os.environ.get("ADMIN_IDS", ""))
# kalau kosong = bot publik; kalau diisi = whitelist
ALLOWED_IDS = _int_list(os.environ.get("ALLOWED_IDS", ""))

MAX_INSTANCES = int(os.environ.get("MAX_INSTANCES", "3"))
# password tetap buat semua instance (kosongkan = generate random 24 char)
SSH_PASSWORD = os.environ.get("SSH_PASSWORD", "Ariel123")
SSH_USER = os.environ.get("SSH_USER", "dev")
SSH_PORT = os.environ.get("SSH_PORT", "22")

# dipakai buat obfuscate token di sqlite (bukan enkripsi kuat)
BOT_SECRET = os.environ.get("BOT_SECRET", "railway-nat-bot")

# credit yang nempel di tiap output pembuatan VPS
CREDIT = os.environ.get("CREDIT", "by @yazinul96")

RAILWAY_BIN = os.environ.get("RAILWAY_BIN", "railway")
CMD_TIMEOUT = int(os.environ.get("CMD_TIMEOUT", "180"))

REGIONS = {
    "sg": "asia-southeast1-eqsg3a",
    "us": "us-east4-eqdc4a",
    "eu": "europe-west4-drams3a",
}
DEFAULT_REGION = os.environ.get("DEFAULT_REGION", "sg")


def region_id(alias: str) -> str:
    return REGIONS.get((alias or DEFAULT_REGION).lower(), REGIONS[DEFAULT_REGION])


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_allowed(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    return not ALLOWED_IDS or user_id in ALLOWED_IDS
