"""Selftest tanpa Telegram & tanpa token Railway.

Jalan: python3 selftest.py
Dites: store (token + kolom id Railway), parsing output tcp-proxy asli,
pipeline create/destroy dengan API & CLI di-mock, redaction.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="natbot-test-")
os.environ["DATA_DIR"] = TMP
os.environ["BOT_SECRET"] = "test-secret"
os.environ["BOT_TOKEN"] = "123:fake"

sys.path.insert(0, str(Path(__file__).resolve().parent))

import provision  # noqa: E402
import railway_api as api  # noqa: E402
import railway_cli as rw  # noqa: E402
import store  # noqa: E402

fails = []


def check(label, cond, extra=""):
    if cond:
        print(f"  ok   {label}")
    else:
        fails.append(label)
        print(f"  FAIL {label} {extra}")


def test_store():
    print("store")
    store.init()
    check("db file dibuat", (Path(TMP) / "bot.db").exists())
    check("mode db 600", oct(os.stat(Path(TMP) / "bot.db").st_mode)[-3:] == "600")

    store.set_token(42, "railway-account-token-abc")
    raw = (Path(TMP) / "bot.db").read_bytes()
    check("token nggak plaintext", b"railway-account-token-abc" not in raw)
    check("token decrypt balik", store.get_token(42) == "railway-account-token-abc")

    iid = store.add_instance(42, "nat-test01", "asia-southeast1-eqsg3a", "pw123", "dev")
    check("quota count", store.count_instances(42) == 1)
    store.set_railway_ids(iid, "pid-1", "eid-1", "sid-1")
    store.finish_instance(iid, "acela.proxy.rlwy.net", 27936)
    inst = store.get_instance(iid)
    check("kolom id Railway kesimpan",
          (inst["project_id"], inst["env_id"], inst["service_id"]) == ("pid-1", "eid-1", "sid-1"))
    check("status active", inst["status"] == "active")
    check("ssh command",
          provision.ssh_command(inst) == "ssh dev@acela.proxy.rlwy.net -p 27936")
    store.del_token(42)
    check("token kehapus", store.get_token(42) is None)


def test_endpoint_real():
    print("endpoint_from (bentuk output asli railway)")
    real = json.loads('''{"proxies":[{"id":"d7914d56","domain":"acela.proxy.rlwy.net",
        "proxyPort":27936,"applicationPort":2222,"endpoint":"acela.proxy.rlwy.net:27936"}]}''')
    check("parse list proxies", rw.endpoint_from(real) == ("acela.proxy.rlwy.net", 27936))
    create_shape = {"applicationPort": 2222, "staged": False, "committed": True,
                    "proxy": {"domain": "maglev.proxy.rlwy.net", "port": 10719,
                              "endpoint": "maglev.proxy.rlwy.net:10719"}}
    check("parse bentuk tcp-proxy create (bukan applicationPort)",
          rw.endpoint_from(create_shape) == ("maglev.proxy.rlwy.net", 10719))
    nested = {"tcpProxy": {"domain": "shuttle.proxy.rlwy.net", "proxyPort": 15140}}
    check("parse nested", rw.endpoint_from(nested) == ("shuttle.proxy.rlwy.net", 15140))
    check("applicationPort doang -> None", rw.endpoint_from({"applicationPort": 2222}) is None)
    check("payload kosong -> None", rw.endpoint_from({"a": 1}) is None)


def test_redact():
    print("redact")
    check("token disensor", "secret" not in rw._redact("auth secret failed", "secret"))


def test_pipeline_ok():
    print("pipeline create (mock)")
    calls = []
    api.project_create = lambda t, n: calls.append(("project", n)) or "pid-x"
    api.environment_id = lambda t, pid: calls.append(("env", pid)) or "eid-x"
    api.service_create = lambda t, p, e, n, img, v: (
        calls.append(("service", n, img, "ROOT_PASSWORD" in v)) or "sid-x")
    api.deployment_status = lambda t, p, e, s: {"status": "SUCCESS"}
    api.service_instance_update = lambda t, e, s, patch: calls.append(("update", patch.get("region"))) or True
    api.service_redeploy = lambda t, e, s: calls.append(("redeploy",)) or True
    rw.tcp_create = lambda t, port, p, e, s: (
        calls.append(("tcp", port, p, e, s)) or
        {"proxies": [{"domain": "acela.proxy.rlwy.net", "proxyPort": 27936}]})
    rw.scale = lambda *a: calls.append(("scale", a[1])) or ""

    res = provision.create("tok", 7, "asia-southeast1-eqsg3a", lambda s: None)
    order = [c[0] for c in calls if c[0] in ("project", "service", "tcp")]
    check("project -> service -> tcp urut", order == ["project", "service", "tcp"], str(calls))
    tcp_call = [c for c in calls if c[0] == "tcp"][0]
    check("port tcp 22 (sshd container)", tcp_call[1] == 22)
    check("hasil punya endpoint", res["domain"] == "acela.proxy.rlwy.net" and res["port"] == 27936)
    check("password ikut config (Ariel123)", res["password"] == "Ariel123")
    check("default flavor ubuntu + user root", res["flavor"] == "ubuntu" and res["user"] == "root")
    inst = store.get_instance(res["id"])
    check("db active + flavor ubuntu + id Railway",
          inst["status"] == "active" and inst["flavor"] == "ubuntu"
          and inst["service_id"] == "sid-x")


def test_pipeline_ubuntu():
    print("pipeline ubuntu 26.04 + root (mock)")
    calls = []
    api.project_create = lambda t, n: "pid-u"
    api.environment_id = lambda t, p: "eid-u"
    api.service_create = lambda t, p, e, n, img, v: (
        calls.append(("service", img, v)) or "sid-u")
    api.deployment_status = lambda t, p, e, s: {"status": "SUCCESS"}
    api.service_instance_update = lambda t, e, s, patch: (
        calls.append(("update", patch)) or True)
    api.service_redeploy = lambda t, e, s: calls.append(("redeploy",)) or True
    rw.tcp_create = lambda t, port, p, e, s: (
        calls.append(("tcp", port)) or {"proxy": {"domain": "yamanote.proxy.rlwy.net", "port": 17905}})

    res = provision.create("tok", 21, "asia-southeast1-eqsg3a", lambda s: None, flavor="ubuntu")
    svc = [c for c in calls if c[0] == "service"][0]
    patch = [c for c in calls if c[0] == "update"][0][1]
    check("image ubuntu:26.04", svc[1] == "ubuntu:26.04", svc[1])
    check("password masuk ROOT_PASSWORD", "ROOT_PASSWORD" in svc[2])
    check("startCommand bootstrap sshd",
          "PermitRootLogin yes" in patch.get("startCommand", "")
          and "sshd -D -e" in patch.get("startCommand", ""))
    check("region ikut di-update", patch.get("region") == "asia-southeast1-eqsg3a")
    check("redeploy dipanggil", ("redeploy",) in calls)
    check("tcp proxy port 22", [c for c in calls if c[0] == "tcp"][0][1] == 22)
    check("user root", res["user"] == "root" and res["flavor"] == "ubuntu")
    inst = store.get_instance(res["id"])
    check("db nyimpen flavor ubuntu", inst["flavor"] == "ubuntu" and inst["ssh_user"] == "root")


def test_pipeline_rate_limit():
    print("pipeline create (rate limit)")
    def boom(t, n):
        raise api.ApiError("You are creating projects too quickly.", "BAD_USER_INPUT")
    api.project_create = boom
    before = store.count_instances(9)
    try:
        provision.create("tok", 9, "sg", lambda s: None)
        check("harus raise", False)
    except api.ApiError as exc:
        check("pesan rate limit jelas", "30 detik" in str(exc), str(exc))
    check("quota nggak ketahan instance gagal", store.count_instances(9) == before)
    check("instance gagal tetap kelihatan di /list",
          [r["status"] for r in store.list_instances(9)] == ["failed"])


def test_destroy():
    print("destroy")
    deleted = []
    api.project_delete = lambda t, pid: deleted.append(pid) or True
    iid = store.add_instance(11, "nat-del", "sg", "pw", "dev")
    store.set_railway_ids(iid, "pid-del", "eid-del", "sid-del")
    provision.destroy("tok", iid)
    check("project dihapus lewat API", deleted == ["pid-del"])
    check("db bersih", store.get_instance(iid) is None)


def main():
    test_store()
    test_endpoint_real()
    test_redact()
    test_pipeline_ok()
    test_pipeline_ubuntu()
    test_pipeline_rate_limit()
    test_destroy()
    print()
    if fails:
        print(f"GAGAL: {len(fails)} cek — {', '.join(fails)}")
        return 1
    print("SEMUA CEK LULUS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
