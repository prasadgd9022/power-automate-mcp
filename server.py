"""
Local Power Automate MCP server.

A self-hosted Model Context Protocol server that talks DIRECTLY to the
Microsoft Power Automate (ProcessSimple) REST API from your own machine,
using YOUR identity. No third-party SaaS is involved and no flow data ever
leaves your device -- the process runs locally and calls
https://api.flow.microsoft.com over HTTPS with a token minted from your
local Azure CLI login (or an interactive browser sign-in as a fallback).

Auth precedence (first that works wins):
  1. PA_MCP_ACCESS_TOKEN   -- a raw bearer token you supply (advanced/CI).
  2. Azure CLI             -- reuses your `az login` session (recommended).
  3. Interactive browser   -- opens a browser to sign you in (fallback).

Transport: stdio (launched by the Copilot CLI as a local subprocess).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from typing import Any, Optional

import requests
from azure.identity import AzureCliCredential, InteractiveBrowserCredential
from mcp.server.fastmcp import FastMCP

logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Configuration (override via environment variables for sovereign clouds etc.)
# ---------------------------------------------------------------------------
API_HOST = os.environ.get("PA_MCP_API_HOST", "https://api.flow.microsoft.com").rstrip("/")
API_SCOPE = os.environ.get("PA_MCP_SCOPE", "https://service.flow.microsoft.com/.default")
API_VERSION = os.environ.get("PA_MCP_API_VERSION", "2016-11-01")
HTTP_TIMEOUT = int(os.environ.get("PA_MCP_HTTP_TIMEOUT", "60"))

# Cap the size of any single tool payload so we don't blow up the LLM context.
MAX_RESPONSE_CHARS = int(os.environ.get("PA_MCP_MAX_RESPONSE_CHARS", "60000"))

mcp = FastMCP("power-automate")

# ---------------------------------------------------------------------------
# Token handling -- lazy, cached, thread-safe. Nothing happens at import time
# so the server starts instantly and only prompts for auth on the first call.
# ---------------------------------------------------------------------------
_TOKEN_LOCK = threading.Lock()
# Cache is keyed by token scope so the Flow API and each Dataverse org can hold
# their own independently-refreshed bearer token: scope -> (token, expires_at).
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_CREDENTIAL: Any = None


def _get_credential() -> Any:
    global _CREDENTIAL
    if _CREDENTIAL is None:
        # AzureCliCredential first (reuses `az login`), interactive as fallback.
        _CREDENTIAL = AzureCliCredential()
    return _CREDENTIAL


def _acquire_token(scope: str = API_SCOPE) -> str:
    """Return a valid bearer token for `scope`, refreshing ~2 min before expiry.

    Defaults to the Flow API scope. The Dataverse write skills pass an
    org-specific scope (``https://<org>.crm.dynamics.com/.default``) so a single
    `az login` session can mint tokens for both Flow and Dataverse."""
    global _CREDENTIAL

    # The raw-token override only makes sense for the default Flow scope.
    if scope == API_SCOPE:
        env_token = os.environ.get("PA_MCP_ACCESS_TOKEN")
        if env_token:
            return env_token

    with _TOKEN_LOCK:
        now = time.time()
        cached = _TOKEN_CACHE.get(scope)
        if cached and now < (cached[1] - 120):
            return cached[0]

        try:
            token = _get_credential().get_token(scope)
        except Exception as cli_err:  # noqa: BLE001 -- fall back to interactive
            try:
                cred = InteractiveBrowserCredential()
                token = cred.get_token(scope)
                _CREDENTIAL = cred
            except Exception as ui_err:  # noqa: BLE001
                raise RuntimeError(
                    "Could not acquire a token. Run `az login` first. "
                    f"Azure CLI error: {cli_err}. Interactive error: {ui_err}"
                ) from ui_err

        _TOKEN_CACHE[scope] = (token.token, float(token.expires_on))
        return token.token


def _request(method: str, path: str, params: Optional[dict] = None,
             json_body: Optional[dict] = None) -> Any:
    """Call the Flow REST API and return parsed JSON (or a status dict)."""
    url = f"{API_HOST}{path}"
    q = {"api-version": API_VERSION}
    if params:
        q.update({k: v for k, v in params.items() if v is not None})
    headers = {
        "Authorization": f"Bearer {_acquire_token()}",
        "Accept": "application/json",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    resp = requests.request(method, url, headers=headers, params=q,
                            json=json_body, timeout=HTTP_TIMEOUT)

    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json()
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(
            f"Flow API {method} {path} failed ({resp.status_code}): "
            f"{json.dumps(detail)[:1500]}"
        )

    if not resp.content:
        return {"status": "ok", "http_status": resp.status_code}
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"raw": resp.text[:MAX_RESPONSE_CHARS]}


def _dump(obj: Any) -> str:
    """Serialize to JSON, truncating if it would overflow the context budget."""
    text = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    if len(text) > MAX_RESPONSE_CHARS:
        text = (text[:MAX_RESPONSE_CHARS]
                + f"\n... [truncated at {MAX_RESPONSE_CHARS} chars]")
    return text


def _resolve_environment(environment: Optional[str]) -> str:
    """Return the given environment name, or auto-pick the default one."""
    if environment:
        return environment
    data = _request("GET", "/providers/Microsoft.ProcessSimple/environments")
    for env in data.get("value", []):
        if env.get("properties", {}).get("isDefault"):
            return env["name"]
    values = data.get("value", [])
    if values:
        return values[0]["name"]
    raise RuntimeError("No Power Automate environments are visible to your account.")


def _flow_summary(flow: dict) -> dict:
    props = flow.get("properties", {})
    return {
        "name": flow.get("name"),
        "displayName": props.get("displayName"),
        "state": props.get("state"),
        "createdTime": props.get("createdTime"),
        "lastModifiedTime": props.get("lastModifiedTime"),
    }


# ---------------------------------------------------------------------------
# Dataverse (Web API) support -- backs the *write* skills (env-variable and flow
# definition updates). The Flow REST API cannot edit these; they live in the
# environment's Dataverse instance, so we resolve the org URL for the target
# environment and call its Web API with an org-scoped token.
# ---------------------------------------------------------------------------
DATAVERSE_API_VERSION = os.environ.get("PA_MCP_DATAVERSE_API_VERSION", "v9.2")


def _resolve_org_url(environment: Optional[str]) -> tuple[str, str]:
    """Return ``(environment_name, dataverse_org_url)`` for the given/default env.

    The org URL is read from the environment's ``linkedEnvironmentMetadata`` and
    is the base for all Dataverse Web API calls (e.g.
    ``https://orgxxxx.crm.dynamics.com``)."""
    env = _resolve_environment(environment)
    data = _request(
        "GET", f"/providers/Microsoft.ProcessSimple/environments/{env}"
    )
    meta = data.get("properties", {}).get("linkedEnvironmentMetadata", {})
    org = meta.get("instanceUrl") or meta.get("instanceApiUrl")
    if not org:
        raise RuntimeError(
            f"Environment '{env}' has no linked Dataverse instance; the "
            "Dataverse write skills require a Dataverse-backed environment."
        )
    return env, org.rstrip("/")


def _dv_request(org_url: str, method: str, path: str,
                params: Optional[dict] = None,
                json_body: Optional[dict] = None,
                extra_headers: Optional[dict] = None) -> Any:
    """Call the Dataverse Web API for `org_url` and return parsed JSON/status."""
    token = _acquire_token(f"{org_url}/.default")
    url = f"{org_url}/api/data/{DATAVERSE_API_VERSION}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    resp = requests.request(method, url, headers=headers, params=params,
                            json=json_body, timeout=HTTP_TIMEOUT)

    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json()
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(
            f"Dataverse {method} {path} failed ({resp.status_code}): "
            f"{json.dumps(detail)[:1500]}"
        )

    if not resp.content:
        return {"status": "ok", "http_status": resp.status_code}
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"raw": resp.text[:MAX_RESPONSE_CHARS]}


def _get_env_var_definition(org_url: str, schema_name: str) -> dict:
    """Fetch an environment-variable definition + its current value record."""
    safe = schema_name.replace("'", "''")
    data = _dv_request(
        org_url, "GET", "/environmentvariabledefinitions",
        params={
            "$filter": f"schemaname eq '{safe}'",
            "$select": "environmentvariabledefinitionid,schemaname,displayname,"
                       "defaultvalue,type",
            "$expand": "environmentvariabledefinition_environmentvariablevalue("
                       "$select=environmentvariablevalueid,value,schemaname)",
        },
    )
    defs = data.get("value", [])
    if not defs:
        raise RuntimeError(
            f"No environment variable with schemaname '{schema_name}' found."
        )
    return defs[0]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
def check_auth() -> str:
    """Verify authentication works and show the environments you can access.

    Use this first to confirm the server can reach Power Automate with your
    identity (runs `az login` under the hood via Azure CLI credential)."""
    data = _request("GET", "/providers/Microsoft.ProcessSimple/environments")
    envs = [
        {
            "name": e.get("name"),
            "displayName": e.get("properties", {}).get("displayName"),
            "isDefault": e.get("properties", {}).get("isDefault", False),
        }
        for e in data.get("value", [])
    ]
    return _dump({"authenticated": True, "environmentCount": len(envs),
                  "environments": envs})


@mcp.tool()
def list_environments() -> str:
    """List all Power Platform environments visible to your account."""
    data = _request("GET", "/providers/Microsoft.ProcessSimple/environments")
    envs = [
        {
            "name": e.get("name"),
            "displayName": e.get("properties", {}).get("displayName"),
            "isDefault": e.get("properties", {}).get("isDefault", False),
            "location": e.get("location"),
        }
        for e in data.get("value", [])
    ]
    return _dump(envs)


@mcp.tool()
def list_flows(environment: Optional[str] = None, top: int = 50) -> str:
    """List cloud flows in an environment (defaults to your default env).

    Args:
        environment: Environment name (GUID-like). Omit to use the default.
        top: Max number of flows to return (default 50)."""
    env = _resolve_environment(environment)
    data = _request(
        "GET",
        f"/providers/Microsoft.ProcessSimple/environments/{env}/flows",
        params={"$top": top},
    )
    flows = [_flow_summary(f) for f in data.get("value", [])]
    return _dump({"environment": env, "count": len(flows), "flows": flows})


@mcp.tool()
def get_flow(flow_name: str, environment: Optional[str] = None) -> str:
    """Get the full definition of a flow (triggers, actions, connections).

    Args:
        flow_name: The flow's name/id (the GUID-like `name`, not display name).
        environment: Environment name. Omit to use the default."""
    env = _resolve_environment(environment)
    data = _request(
        "GET",
        f"/providers/Microsoft.ProcessSimple/environments/{env}/flows/{flow_name}",
    )
    return _dump(data)


@mcp.tool()
def get_flow_runs(flow_name: str, environment: Optional[str] = None,
                  top: int = 20) -> str:
    """Get recent run history for a flow (status, start/end times).

    Args:
        flow_name: The flow's name/id.
        environment: Environment name. Omit to use the default.
        top: Max number of runs to return (default 20)."""
    env = _resolve_environment(environment)
    data = _request(
        "GET",
        f"/providers/Microsoft.ProcessSimple/environments/{env}/flows/{flow_name}/runs",
        params={"$top": top},
    )
    runs = [
        {
            "name": r.get("name"),
            "status": r.get("properties", {}).get("status"),
            "startTime": r.get("properties", {}).get("startTime"),
            "endTime": r.get("properties", {}).get("endTime"),
            "code": r.get("properties", {}).get("code"),
            "error": r.get("properties", {}).get("error"),
        }
        for r in data.get("value", [])
    ]
    return _dump({"environment": env, "flow": flow_name,
                  "count": len(runs), "runs": runs})


@mcp.tool()
def get_flow_run_details(flow_name: str, run_name: str,
                         environment: Optional[str] = None) -> str:
    """Get full details of a single flow run, including error information.

    Args:
        flow_name: The flow's name/id.
        run_name: The run's name/id (from get_flow_runs).
        environment: Environment name. Omit to use the default."""
    env = _resolve_environment(environment)
    data = _request(
        "GET",
        f"/providers/Microsoft.ProcessSimple/environments/{env}/flows/"
        f"{flow_name}/runs/{run_name}",
    )
    return _dump(data)


@mcp.tool()
def set_flow_state(flow_name: str, state: str,
                   environment: Optional[str] = None) -> str:
    """Enable (start) or disable (stop) a flow.

    Args:
        flow_name: The flow's name/id.
        state: "start" to enable, or "stop" to disable.
        environment: Environment name. Omit to use the default."""
    action = state.strip().lower()
    if action in ("start", "enable", "on"):
        verb = "start"
    elif action in ("stop", "disable", "off"):
        verb = "stop"
    else:
        raise ValueError("state must be 'start'/'enable' or 'stop'/'disable'.")
    env = _resolve_environment(environment)
    _request(
        "POST",
        f"/providers/Microsoft.ProcessSimple/environments/{env}/flows/{flow_name}/{verb}",
    )
    return _dump({"environment": env, "flow": flow_name,
                  "action": verb, "result": "ok"})


# ---------------------------------------------------------------------------
# Dataverse write skills
# ---------------------------------------------------------------------------
# These edit records that live in the environment's Dataverse instance (not the
# Flow REST API): environment-variable *current values* and flow *definitions*.
# Every one requires an explicit `confirm=True` so a definition is never mutated
# by accident, and each has a read-only companion (get_*) for safe inspection.

@mcp.tool()
def get_environment_variable(schema_name: str,
                             environment: Optional[str] = None) -> str:
    """Read an environment variable's definition, default and current value.

    Environment variables are the safe indirection layer flows use for things
    like function-app URLs. The *current value* (per-environment override) wins
    over the *default value* (shared across environments). Use this before
    `update_environment_variable` to see the value id you will change.

    Args:
        schema_name: The variable's schema name (e.g.
            "contoso_ApiBaseUrl").
        environment: Environment name. Omit to use the default."""
    env, org = _resolve_org_url(environment)
    d = _get_env_var_definition(org, schema_name)
    values = d.get("environmentvariabledefinition_environmentvariablevalue", [])
    cur = values[0] if values else None
    return _dump({
        "environment": env,
        "orgUrl": org,
        "definitionId": d.get("environmentvariabledefinitionid"),
        "schemaName": d.get("schemaname"),
        "displayName": d.get("displayname"),
        "defaultValue": d.get("defaultvalue"),
        "currentValueId": cur.get("environmentvariablevalueid") if cur else None,
        "currentValue": cur.get("value") if cur else None,
        "hasCurrentValueOverride": cur is not None,
    })


@mcp.tool()
def update_environment_variable(schema_name: str, new_value: str,
                                environment: Optional[str] = None,
                                confirm: bool = False) -> str:
    """Update an environment variable's CURRENT value (per-environment override).

    This changes ONLY the current value record for the target environment; the
    shared default value is left untouched, so other environments (e.g. Prod)
    are unaffected. If no current value record exists yet, one is created. This
    is the safe way to repoint a flow's function-app URL, connection string,
    etc. without editing the flow definition.

    Args:
        schema_name: The variable's schema name.
        new_value: The new current value to set.
        environment: Environment name. Omit to use the default.
        confirm: Must be True to actually write. If False, returns a dry-run
            preview of the change without modifying anything."""
    env, org = _resolve_org_url(environment)
    d = _get_env_var_definition(org, schema_name)
    def_id = d.get("environmentvariabledefinitionid")
    values = d.get("environmentvariabledefinition_environmentvariablevalue", [])
    cur = values[0] if values else None
    old_value = cur.get("value") if cur else None
    value_id = cur.get("environmentvariablevalueid") if cur else None

    if not confirm:
        return _dump({
            "dryRun": True, "environment": env, "orgUrl": org,
            "schemaName": schema_name, "definitionId": def_id,
            "currentValueId": value_id, "oldValue": old_value,
            "newValue": new_value,
            "action": "update" if cur else "create",
            "note": "Set confirm=True to apply this change.",
        })

    if cur:
        _dv_request(org, "PATCH",
                    f"/environmentvariablevalues({value_id})",
                    json_body={"value": new_value})
        action = "updated"
    else:
        created = _dv_request(
            org, "POST", "/environmentvariablevalues",
            json_body={
                "value": new_value,
                "EnvironmentVariableDefinitionId@odata.bind":
                    f"/environmentvariabledefinitions({def_id})",
            },
            extra_headers={"Prefer": "return=representation"},
        )
        value_id = created.get("environmentvariablevalueid", value_id)
        action = "created"

    return _dump({
        "environment": env, "orgUrl": org, "schemaName": schema_name,
        "definitionId": def_id, "currentValueId": value_id,
        "oldValue": old_value, "newValue": new_value,
        "action": action, "result": "ok",
    })


@mcp.tool()
def get_flow_definition(flow_id: str, environment: Optional[str] = None) -> str:
    """Read a flow's Dataverse record, including its raw `clientdata` definition.

    Unlike `get_flow` (Flow REST API), this reads the underlying Dataverse
    `workflow` row that `update_flow_definition` edits. The `clientdata` field
    is the JSON (definition + connectionReferences) you would modify. Use this
    to capture the exact current definition before making a targeted change.

    Args:
        flow_id: The flow's id (GUID, same as the Flow REST `name`).
        environment: Environment name. Omit to use the default."""
    env, org = _resolve_org_url(environment)
    wf = _dv_request(
        org, "GET",
        f"/workflows({flow_id})",
        params={"$select": "workflowid,name,category,type,statecode,"
                           "statuscode,clientdata,modifiedon"},
    )
    return _dump({
        "environment": env, "orgUrl": org,
        "flowId": wf.get("workflowid"), "name": wf.get("name"),
        "category": wf.get("category"), "statecode": wf.get("statecode"),
        "statuscode": wf.get("statuscode"),
        "modifiedOn": wf.get("modifiedon"),
        "clientdata": wf.get("clientdata"),
    })


@mcp.tool()
def update_flow_definition(flow_id: str, clientdata: str,
                           environment: Optional[str] = None,
                           confirm: bool = False) -> str:
    """Overwrite a flow's `clientdata` definition in Dataverse (ADVANCED).

    This is a low-level, higher-risk operation: it replaces the flow's entire
    definition JSON. The `clientdata` you pass MUST be complete and valid --
    including the `properties.definition` and `properties.connectionReferences`
    -- because it fully overwrites the existing value. Prefer
    `update_environment_variable` when a flow reads its target from an
    environment variable; only reach for this when you must change the
    definition itself (add/remove/edit an action).

    Recommended workflow:
      1. Call `get_flow_definition` and keep the returned `clientdata`.
      2. Make your minimal edit to that JSON string.
      3. Call this with confirm=False to preview, then confirm=True to apply.

    Args:
        flow_id: The flow's id (GUID).
        clientdata: The complete new definition JSON (as a string).
        environment: Environment name. Omit to use the default.
        confirm: Must be True to write. If False, returns a dry-run preview and
            validates that `clientdata` is well-formed JSON."""
    try:
        parsed = json.loads(clientdata)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"clientdata is not valid JSON: {e}. Pass the complete definition "
            "string, e.g. the value returned by get_flow_definition."
        ) from e

    env, org = _resolve_org_url(environment)

    if not confirm:
        has_def = "definition" in json.dumps(parsed)
        return _dump({
            "dryRun": True, "environment": env, "orgUrl": org,
            "flowId": flow_id, "clientdataChars": len(clientdata),
            "clientdataIsValidJson": True,
            "containsDefinition": has_def,
            "note": "Set confirm=True to overwrite the flow definition.",
        })

    _dv_request(org, "PATCH", f"/workflows({flow_id})",
                json_body={"clientdata": clientdata})
    return _dump({
        "environment": env, "orgUrl": org, "flowId": flow_id,
        "clientdataChars": len(clientdata),
        "action": "updated", "result": "ok",
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local Power Automate MCP server")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio"], help="Transport (stdio only).")
    parser.parse_args()
    mcp.run(transport="stdio")
