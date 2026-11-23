"""Pipeline provisioning satu instance NAT VPS — backend GraphQL API + CLI hybrid.

Satu flavor: `ubuntu` — image ubuntu:26.04, login `root`, sshd port 22.
sshd di-bootstrap lewat startCommand (apt-get install openssh-server saat container start).
"""
from __future__ import annotations

import secrets
import string
import time

import railway_api as api
import railway_cli as rw
import store
from config import SSH_PASSWORD as FIXED_PASSWORD

DEPLOY_TIMEOUT = 300
FAILED_STATES = {"FAILED", "CRASHED", "REMOVED", "SKIPPED"}

UBUNTU_BOOT = (
    "bash -c 'export DEBIAN_FRONTEND=noninteractive; "
    "apt-get update -qq && apt-get install -y -qq --no-install-recommends "
    "openssh-server sudo procps nano >/dev/null; "
    "mkdir -p /run/sshd; echo \"root:$ROOT_PASSWORD\" | chpasswd; "
    "sed -i -e \"s/^#*PermitRootLogin.*/PermitRootLogin yes/\" "
    "-e \"s/^#*PasswordAuthentication.*/PasswordAuthentication yes/\" /etc/ssh/sshd_config; "
    "exec /usr/sbin/sshd -D -e'"
)

FLAVORS: dict[str, dict] = {
    "ubuntu": {
        "label": "Ubuntu 26.04 LTS (root, port 22)",
        "image": "ubuntu:26.04",
        "app_port": 22,
        "user": "root",
        "password_var": "ROOT_PASSWORD",
        "base_vars": {"DEBIAN_FRONTEND": "noninteractive"},
        "start_command": UBUNTU_BOOT,
    },
}
DEFAULT_FLAVOR = "ubuntu"


def gen_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def wait_deployment(token: str, pid: str, eid: str, sid: str,
                    notify=None, timeout: int = DEPLOY_TIMEOUT) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            node = api.deployment_status(token, pid, eid, sid)
        except api.ApiError:
            node = {}
        status = (node or {}).get("status", "")
        if status and status != last:
            last = status
            if notify:
                notify(f"deployment: {status}")
        if status == "SUCCESS":
            return status
        if status in FAILED_STATES:
            raise api.ApiError(f"deployment {status}")
        time.sleep(6)
    return last or "TIMEOUT"


def create(token: str, user_id: int, region: str, notify, flavor: str = DEFAULT_FLAVOR) -> dict:
    """Bikin instance baru. notify(str) dipanggil tiap progress."""
    f = FLAVORS.get(flavor) or FLAVORS[DEFAULT_FLAVOR]
    password = FIXED_PASSWORD or gen_password()
    project_name = f"nat-{store.new_id()}"
    iid = store.add_instance(user_id, project_name, region, password, f["user"], flavor)
    try:
        notify("1/5 bikin project")
        try:
            pid = api.project_create(token, project_name)
        except api.ApiError as exc:
            if "too quickly" in str(exc).lower():
                raise api.ApiError("rate limit workspace: 1 project / 30 detik, coba lagi") from exc
            raise
        eid = api.environment_id(token, pid)

        notify(f"2/5 bikin service ({flavor})")
        variables = dict(f["base_vars"])
        variables[f["password_var"]] = password
        sid = api.service_create(token, pid, eid, "sshd", f["image"], variables)
        store.set_railway_ids(iid, pid, eid, sid)

        patch: dict = {"region": region}
        if f["start_command"]:
            patch["startCommand"] = f["start_command"]
        try:
            api.service_instance_update(token, eid, sid, patch)
            if f["start_command"]:
                api.service_redeploy(token, eid, sid)
        except api.ApiError as exc:
            notify(f"peringatan: {exc}")

        notify("3/5 nunggu deployment")
        wait_deployment(token, pid, eid, sid, notify=notify)

        notify("4/5 buka TCP proxy")
        payload = rw.tcp_create(token, f["app_port"], pid, eid, sid)
        endpoint = rw.endpoint_from(payload)
        if not endpoint:
            endpoint = rw.endpoint_from(rw.tcp_list(token, pid, eid, sid))
        if not endpoint:
            raise api.ApiError("TCP proxy belum kebentuk, cek dashboard Railway")

        domain, port = endpoint
        store.finish_instance(iid, domain, int(port))
        notify("5/5 beres")
        return {"id": iid, "domain": domain, "port": int(port), "password": password,
                "project": project_name, "region": region, "project_id": pid,
                "flavor": flavor, "user": f["user"]}
    except Exception:
        store.fail_instance(iid)
        raise


def destroy(token: str, iid: str) -> None:
    inst = store.get_instance(iid)
    if not inst:
        raise rw.RailwayError(f"instance {iid} nggak ada di db")
    pid = inst["project_id"]
    if pid:
        api.project_delete(token, pid)
    else:
        rw.delete_project(token, inst["project_name"])
    store.delete_instance(iid)


def ssh_command(inst) -> str:
    domain = inst["domain"] or "<pending>"
    port = inst["proxy_port"] or "?"
    return f"ssh {inst['ssh_user']}@{domain} -p {port}"
