"""Railway public GraphQL API — jalur ini yang jalan buat workspace token (rlwy_wksp_…).

CLI `railway` nolak token workspace karena manggil `me` di awal (Unauthorized),
padahal GraphQL-nya nerima. Jadi provisioning inti lewat sini, CLI cuma buat
tcp-proxy / logs / delete yang terbukti jalan pakai -p -e -s.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

API = "https://backboard.railway.com/graphql/v2"
UA = "railway-cli/5.75.0"


class ApiError(RuntimeError):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def gql(token: str, query: str, variables: dict | None = None, timeout: int = 60) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="replace")[:300]
        raise ApiError(f"HTTP {exc.code}: {text}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"network: {exc.reason}") from exc

    if payload.get("errors"):
        first = payload["errors"][0]
        code = (first.get("extensions") or {}).get("code", "")
        raise ApiError(first.get("message", "graphql error"), code)
    return payload.get("data") or {}


# --- project ---------------------------------------------------------------
def project_create(token: str, name: str) -> str:
    data = gql(token, 'mutation($in: ProjectCreateInput!) { projectCreate(input: $in) { id } }',
               {"in": {"name": name}})
    return data["projectCreate"]["id"]


def project_delete(token: str, project_id: str) -> bool:
    data = gql(token, 'mutation($id: String!) { projectDelete(id: $id) }', {"id": project_id})
    return bool(data.get("projectDelete"))


def environment_id(token: str, project_id: str, prefer: str = "production") -> str:
    data = gql(token, 'query($id: String!) { project(id: $id) { environments'
                     ' { edges { node { id name } } } } }', {"id": project_id})
    nodes = [e["node"] for e in data["project"]["environments"]["edges"]]
    if not nodes:
        raise ApiError("project nggak punya environment")
    for n in nodes:
        if n["name"] == prefer:
            return n["id"]
    return nodes[0]["id"]


# --- service ---------------------------------------------------------------
def service_create(token: str, project_id: str, env_id: str, name: str,
                   image: str, variables: dict[str, str]) -> str:
    data = gql(
        token,
        'mutation($in: ServiceCreateInput!) { serviceCreate(input: $in) { id name } }',
        {"in": {
            "projectId": project_id,
            "environmentId": env_id,
            "name": name,
            "source": {"image": image},
            "variables": variables,
        }},
    )
    return data["serviceCreate"]["id"]


def variable_upsert(token: str, project_id: str, env_id: str, service_id: str,
                    name: str, value: str, skip_deploys: bool = False) -> bool:
    gql(token, 'mutation($in: VariableUpsertInput!) { variableUpsert(input: $in) }', {"in": {
        "projectId": project_id,
        "environmentId": env_id,
        "serviceId": service_id,
        "name": name,
        "value": value,
        "skipDeploys": skip_deploys,
    }})
    return True


def deployment_status(token: str, project_id: str, env_id: str, service_id: str) -> dict:
    data = gql(token, '''query($p:String!,$e:String!,$s:String!) {
        deployments(input:{projectId:$p, environmentId:$e, serviceId:$s}, first:1) {
          edges { node { id status createdAt } } } }''',
               {"p": project_id, "e": env_id, "s": service_id})
    edges = data["deployments"]["edges"]
    return edges[0]["node"] if edges else {}


def service_instance_update(token: str, env_id: str, service_id: str, patch: dict) -> bool:
    gql(token, 'mutation($in: ServiceInstanceUpdateInput!, $s: String!, $e: String!) {'
              ' serviceInstanceUpdate(input: $in, serviceId: $s, environmentId: $e) }',
        {"in": patch, "s": service_id, "e": env_id})
    return True


def service_redeploy(token: str, env_id: str, service_id: str) -> bool:
    gql(token, 'mutation($s: String!, $e: String!) {'
              ' serviceInstanceRedeploy(serviceId: $s, environmentId: $e) }',
        {"s": service_id, "e": env_id})
    return True


def service_domain_create(token: str, env_id: str, service_id: str, target_port: int) -> dict:
    data = gql(token, 'mutation($in: ServiceDomainCreateInput!) {'
                     ' serviceDomainCreate(input: $in) { id domain targetPort } }',
               {"in": {"environmentId": env_id, "serviceId": service_id,
                       "targetPort": target_port}})
    return data["serviceDomainCreate"]


def validate_token(token: str) -> str:
    """Tes token tanpa `me` — query `me` ditolak buat workspace token."""
    data = gql(token, "{ projects { edges { node { name } } } }")
    n = len(data.get("projects", {}).get("edges", []))
    return f"token valid ({n} project kebaca)"
