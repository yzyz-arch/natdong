"""Wrapper Railway CLI — satu subprocess per aksi, token lewat env."""
import json
import os
import re
import subprocess
from pathlib import Path

from config import CMD_TIMEOUT, RAILWAY_BIN


class RailwayError(RuntimeError):
    def __init__(self, message: str, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def _redact(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "***")
    return text


def run(token: str, args: list[str], cwd: Path | None = None,
        timeout: int = CMD_TIMEOUT) -> str:
    env = {k: v for k, v in os.environ.items()
           if k not in ("RAILWAY_TOKEN", "RAILWAY_API_TOKEN")}
    env["RAILWAY_API_TOKEN"] = token          # account token: butuh bikin project
    env["CI"] = "true"
    env["NO_COLOR"] = "1"

    try:
        proc = subprocess.run(
            [RAILWAY_BIN, *args],
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RailwayError(f"timeout {timeout}s: railway {' '.join(args)}",
                           "", _redact(str(exc), token)) from exc
    except FileNotFoundError as exc:
        raise RailwayError(f"binary '{RAILWAY_BIN}' nggak ketemu di PATH") from exc

    out = _redact(proc.stdout or "", token)
    err = _redact(proc.stderr or "", token)
    if proc.returncode != 0:
        tail = (err or out).strip().splitlines()[-6:]
        raise RailwayError(f"railway {' '.join(args[:2])} gagal", out, "\n".join(tail))
    return out


def run_json(token: str, args: list[str], cwd: Path | None = None) -> object:
    raw = run(token, args, cwd=cwd).strip()
    if not raw:
        return {}
    start = min((raw.find(c) for c in "{[" if raw.find(c) >= 0), default=-1)
    if start < 0:
        raise RailwayError("output bukan JSON", raw)
    try:
        return json.loads(raw[start:])
    except json.JSONDecodeError as exc:
        raise RailwayError("JSON nggak bisa di-parse", raw[:400]) from exc


# --- auth ------------------------------------------------------------------
def whoami(token: str) -> str:
    return run(token, ["whoami"]).strip().splitlines()[0]


# --- provisioning ----------------------------------------------------------
def init_project(token: str, cwd: Path, name: str) -> str:
    return run(token, ["init", "--name", name, "--json"], cwd=cwd)


def set_shared_vars(token: str, cwd: Path, pairs: dict[str, str]) -> str:
    args = ["variable", "set", *[f"{k}={v}" for k, v in pairs.items()], "--skip-deploys"]
    return run(token, args, cwd=cwd, timeout=120)


def up(token: str, cwd: Path, service: str | None = None) -> str:
    args = ["up", ".", "-d", "-y", "--no-gitignore"]
    if service:
        args += ["-s", service]
    return run(token, args, cwd=cwd, timeout=600)


def _scope(project: str, env: str, service: str) -> list[str]:
    return ["-p", project, "-e", env, "-s", service]


def tcp_create(token: str, port: int, project: str, env: str, service: str) -> object:
    args = ["tcp-proxy", "create", "--port", str(port), "--json", *_scope(project, env, service)]
    return run_json(token, args)


def tcp_list(token: str, project: str, env: str, service: str) -> object:
    return run_json(token, ["tcp-proxy", "list", "--json", *_scope(project, env, service)])


def service_status(token: str, project: str, env: str, service: str) -> object:
    return run_json(token, ["service", "status", "--json", *_scope(project, env, service)])


def logs(token: str, project: str, env: str, service: str, lines: int = 60) -> str:
    return run(token, ["logs", "--lines", str(lines), *_scope(project, env, service)],
               timeout=90)


def scale(token: str, region: str, project: str, env: str, service: str) -> str:
    return run(token, ["scale", f"{region}=1", *_scope(project, env, service)],
               timeout=120)


def delete_project(token: str, project: str) -> str:
    return run(token, ["delete", "-p", project, "-y", "--json"], timeout=120)


# --- parsing helpers -------------------------------------------------------
HOST_RE = re.compile(r"([a-z0-9][a-z0-9\-.]*\.(?:proxy\.)?rlwy\.net)(?::(\d+))?", re.I)


def walk(obj, keys: tuple[str, ...]):
    """Cari value pertama dari key mana pun, rekursif."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return obj[k]
        for v in obj.values():
            found = walk(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = walk(v, keys)
            if found is not None:
                return found
    return None


def _all_dicts(obj, depth: int = 0) -> list[dict]:
    if depth > 4:
        return []
    out: list[dict] = []
    if isinstance(obj, dict):
        out.append(obj)
        for v in obj.values():
            out += _all_dicts(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            out += _all_dicts(v, depth + 1)
    return out


def endpoint_from(payload, fallback_text: str = "") -> tuple[str, int] | None:
    """Ambil host:port proxy. Prioritas: string `endpoint` (paling nggak ambigu),
    lalu dict proxy/proxies, baru pasangan domain+proxyPort.

    Catatan: `applicationPort` (2222) BUKAN port publik — pernah kepakai salah.
    """
    blob = ""
    try:
        blob = json.dumps(payload)
    except (TypeError, ValueError):
        blob = str(payload)
    for text in (blob, fallback_text or ""):
        m = HOST_RE.search(text)
        if m and m.group(2):
            return m.group(1), int(m.group(2))

    candidates: list[dict] = []
    for key in ("proxies", "proxy"):
        found = walk(payload, (key,))
        if isinstance(found, list):
            candidates += [c for c in found if isinstance(c, dict)]
        elif isinstance(found, dict):
            candidates.append(found)
    candidates += _all_dicts(payload)

    for c in candidates:
        domain = c.get("domain") or c.get("proxyDomain") or c.get("host")
        port = c.get("proxyPort") or c.get("port")
        if isinstance(domain, str) and domain and port:
            try:
                return domain.split(":")[0], int(port)
            except (TypeError, ValueError):
                continue
    return None
