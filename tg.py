"""Client Telegram Bot API minimal (stdlib only, long polling)."""
from __future__ import annotations

import html
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from config import BOT_TOKEN

# sandbox/ISP kadang nyangkut di IPv6 (SYN-SENT nggak pernah selesai) — paksa IPv4
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first(host, port, family=0, type=0, proto=0, flags=0):
    try:
        infos = _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
        if infos:
            return infos
    except socket.gaierror:
        pass
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _ipv4_first

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_LEN = 4000


class TgError(RuntimeError):
    pass


def api(method: str, http_timeout: int = 30, **params):
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        f"{BASE}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise TgError(f"{method}: HTTP {exc.code} {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise TgError(f"{method}: {exc.reason}") from exc
    if not payload.get("ok"):
        raise TgError(f"{method}: {payload.get('description')}")
    return payload.get("result")


def esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def chunk(text: str, size: int = MAX_LEN) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > size:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return parts


def send(chat_id: int, text: str, reply_to: int | None = None) -> list[dict]:
    sent = []
    for part in chunk(text):
        params = {"chat_id": chat_id, "text": part, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        sent.append(api("sendMessage", **params))
    return sent


def edit(chat_id: int, message_id: int, text: str) -> None:
    try:
        api("editMessageText", chat_id=chat_id, message_id=message_id,
            text=text[:MAX_LEN], parse_mode="HTML", disable_web_page_preview=True)
    except TgError:
        pass


def delete(chat_id: int, message_id: int) -> None:
    try:
        api("deleteMessage", chat_id=chat_id, message_id=message_id)
    except TgError:
        pass


def get_updates(offset: int, timeout: int = 30) -> list[dict]:
    try:
        return api("getUpdates", http_timeout=timeout + 10, offset=offset,
                   timeout=timeout, allowed_updates=["message"])
    except TgError:
        return []


def me() -> dict:
    return api("getMe")


def poll_forever(handler, offset: int = 0) -> None:
    while True:
        updates = get_updates(offset)
        if not updates:
            time.sleep(1)
            continue
        for upd in updates:
            offset = max(offset, upd["update_id"] + 1)
            msg = upd.get("message")
            if not msg or "text" not in msg:
                continue
            try:
                handler(msg)
            except Exception as exc:  # jangan sampai loop mati
                try:
                    send(msg["chat"]["id"], f"<b>error</b>\n<code>{esc(exc)}</code>")
                except Exception:
                    pass


def parse_command(text: str) -> tuple[str, list[str]]:
    text = text.strip()
    if not text.startswith("/"):
        return "", []
    head, _, rest = text.partition(" ")
    cmd = head[1:].split("@")[0].lower()
    return cmd, rest.split()
