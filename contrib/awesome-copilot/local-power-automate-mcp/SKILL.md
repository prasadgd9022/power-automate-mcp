---
name: local-power-automate-mcp
description: >-
  Foundation skill for driving Microsoft Power Automate from an AI agent through
  a self-hosted, privacy-first local MCP server that authenticates with the
  user's own Azure CLI (`az login`) identity — no third-party SaaS, no API keys,
  and no tenant flow data leaving the machine. Covers stdio registration for
  GitHub Copilot CLI, VS Code, and Claude; the `az login` auth model and token
  scopes; the 11 read/write tools (Flow REST + Dataverse Web API); the
  confirm-guarded write-safety pattern; sovereign/government-cloud configuration;
  and oversized-response handling. Load this when the user needs Power Automate
  automation but cannot route tenant data through a hosted vendor. Reference
  implementation: https://github.com/prasadgd9022/power-automate-mcp (MIT).
---

# Local Power Automate MCP — Privacy-First Foundation

This skill is the **self-hosted counterpart** to hosted Power Automate MCP
offerings. It connects an agent to a **local stdio MCP server** that talks
directly to Microsoft's own APIs using the operator's **existing Azure identity**,
so tenant flow data never transits a third-party cloud.

> **When to prefer this over a hosted MCP:** regulated tenants, data-residency
> or data-sovereignty requirements, air-gapped/BYO-identity policies, or anyone
> who simply does not want an external vendor brokering their Power Platform
> traffic. If a hosted MCP is acceptable, the `flowstudio-power-automate-*`
> skills cover that path.

> **Requires:**
> - Python 3.10+ on `PATH`
> - Azure CLI installed and signed in (`az login`)
> - The reference server (`server.py`) cloned locally —
>   `git clone https://github.com/prasadgd9022/power-automate-mcp`
> - Python packages: `mcp`, `azure-identity`, `requests`

---

## Why This Is Different (Trust & Data-Flow Model)

| Dimension | Hosted MCP (e.g. FlowStudio) | This local server |
|---|---|---|
| Where it runs | Vendor cloud, remote HTTP endpoint | **Your machine**, stdio subprocess of the host |
| Auth | Portal-issued JWT via `x-api-key` header | **Your `az login` session** (Azure CLI credential) |
| Identity used | Service/API-key identity | **The signed-in user's own identity + RBAC** |
| Data path | Tenant data traverses the vendor's cloud | **Direct** to `api.flow.microsoft.com` + Dataverse over HTTPS |
| Subscription | Paid tiers | **None** — open source (MIT) |
| Write safety | (host-defined) | **`confirm=True` dry-run guard** on Dataverse writes |

**Design rule:** nothing runs at import time. The server starts instantly and
only acquires a token on the **first** tool call — so registration succeeds even
before `az login`, and an auth failure is always a sign-in issue, never a setup
issue.

---

## Auth Model — `az login`, Not API Keys

The server uses `azure-identity` to mint bearer tokens from the local Azure CLI
session (falling back to interactive browser sign-in). There is **no key to
paste** and no secret in any config file.

```bash
az login
# Windows only — warm the cache to avoid a first-call timeout:
az account get-access-token --scope https://service.flow.microsoft.com/.default
```

Two token audiences are used, both from the same session:

| API | Scope | Used by |
|---|---|---|
| Power Automate REST | `https://service.flow.microsoft.com/.default` | environments, flows, runs, on/off |
| Dataverse Web API | `https://<org>.crm.dynamics.com/.default` (org-scoped) | env vars, raw flow definitions |

> **Auth troubleshooting:** `Could not acquire a token` → run `az login` again.
> A `403 Forbidden` from Dataverse is **not** a bug — it means the signed-in
> user lacks RBAC on that environment's Dataverse org (expected for environments
> you cannot administer). Because auth is the user's own identity, every tool
> call is bounded by that user's real Power Platform permissions.

---

## Registering the Server (stdio)

The launch command is identical everywhere:

```
python <ABSOLUTE_PATH>/power-automate-mcp/server.py --transport stdio
```

On **Windows, escape backslashes in JSON** (`C:\\Users\\you\\...\\server.py`).
Always **merge** the `power-automate` entry into any existing config rather than
overwriting the file.

### GitHub Copilot CLI — `~/.copilot/mcp-config.json`
```jsonc
{
  "mcpServers": {
    "power-automate": {
      "type": "stdio",
      "tools": ["*"],
      "command": "python",
      "args": ["<ABSOLUTE_PATH>/power-automate-mcp/server.py", "--transport", "stdio"]
    }
  }
}
```

### VS Code (Copilot Chat, Agent mode) — `.vscode/mcp.json`
Note the key is **`servers`**, not `mcpServers`:
```jsonc
{
  "servers": {
    "power-automate": {
      "type": "stdio",
      "command": "python",
      "args": ["<ABSOLUTE_PATH>/power-automate-mcp/server.py", "--transport", "stdio"]
    }
  }
}
```

### Claude Desktop — `claude_desktop_config.json`
(`%APPDATA%\Claude\...` on Windows; `~/Library/Application Support/Claude/...` on macOS)
```jsonc
{
  "mcpServers": {
    "power-automate": {
      "command": "python",
      "args": ["<ABSOLUTE_PATH>/power-automate-mcp/server.py", "--transport", "stdio"]
    }
  }
}
```

### Claude Code (CLI) — one command
```bash
claude mcp add power-automate -- python <ABSOLUTE_PATH>/power-automate-mcp/server.py --transport stdio
```

**Restart the host** after editing config (Claude Desktop must be fully quit,
not just closed). Verify with `/mcp` (Copilot/Claude CLI) or **MCP: List
Servers** (VS Code).

---

## Verify the Connection

```bash
python probe.py
```

Expected:

```text
TOOLS: ['check_auth', 'list_environments', 'list_flows', 'get_flow', 'get_flow_runs', 'get_flow_run_details', 'set_flow_state', 'get_environment_variable', 'update_environment_variable', 'get_flow_definition', 'update_flow_definition']
CHECK_AUTH_OK: { ... "authenticated": true, "environmentCount": N ... }
```

If `TOOLS` prints but auth fails, the server is registered correctly — run
`az login` and retry. Inside an agent, the equivalent first call is
`check_auth`; always run it before anything else.

---

## Tool Map (11 tools — 8 read, 3 write)

All `environment` args are optional (omit → default environment).

### Read-only
| Tool | Purpose |
|---|---|
| `check_auth` | Confirm auth + list reachable environments. **Run first.** |
| `list_environments` | Every Power Platform environment visible to the account. |
| `list_flows` | Cloud flows you **own or are shared with** in an environment. |
| `get_flow` | Full flow definition from the Flow REST API (triggers/actions/connections). |
| `get_flow_runs` | Recent run history (status, times, error codes) — triage entry point. |
| `get_flow_run_details` | Full detail of one run, including the error payload. |
| `get_environment_variable` | Definition + **default value** + per-environment **current value** (Dataverse). |
| `get_flow_definition` | Raw Dataverse `workflow` row incl. the `clientdata` JSON. |

### Write (mutating)
| Tool | Purpose | Guard |
|---|---|---|
| `set_flow_state` | Enable (`start`) / disable (`stop`) a flow. | none (easily reversible) |
| `update_environment_variable` | Update a variable's **current value only** (per-environment override; shared default untouched). | **`confirm=True`** |
| `update_flow_definition` | **Advanced** — overwrite a flow's entire `clientdata` JSON. | **`confirm=True`** |

---

## Write-Safety Pattern (Non-Obvious — Read Before Mutating)

The two Dataverse writes are **guarded**. Called with the default
`confirm=False` they perform a **dry-run**: they return an old→new preview (or a
JSON-validity check) and change **nothing**. Only `confirm=True` applies.

Recommended edit loop for `update_flow_definition`:

1. `get_flow_definition` → keep the returned `clientdata`.
2. Make your **minimal** edit to that JSON.
3. Call with `confirm=False` → preview / validate the JSON round-trips.
4. Call with `confirm=True` → apply.

Prefer `update_environment_variable` over editing a flow whenever you only need
to **repoint a URL / connection string**: it touches only the *current value*
for the target environment, leaving the shared *default* — and therefore
Production and every other environment — untouched. This is the safest way to
rewire an endpoint per-environment.

---

## Sovereign / Government Cloud & Other Config

All optional (defaults suit commercial M365). Set as environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PA_MCP_API_HOST` | `https://api.flow.microsoft.com` | Flow API host — **change for sovereign clouds** (GCC High, DoD, China). |
| `PA_MCP_SCOPE` | `https://service.flow.microsoft.com/.default` | Flow API token scope. |
| `PA_MCP_API_VERSION` | `2016-11-01` | Flow REST API version. |
| `PA_MCP_DATAVERSE_API_VERSION` | `v9.2` | Dataverse Web API version. |
| `PA_MCP_ACCESS_TOKEN` | – | Raw bearer token (skips CLI/browser) — CI/advanced only. |
| `PA_MCP_HTTP_TIMEOUT` | `60` | HTTP timeout (s). |
| `PA_MCP_MAX_RESPONSE_CHARS` | `60000` | Truncate oversized tool payloads. |

---

## Handling Oversized Responses

`get_flow` / `get_flow_definition` on deeply nested flows, and `list_flows` on
large tenants, can overflow context. The server truncates any payload larger
than `PA_MCP_MAX_RESPONSE_CHARS`.

1. **Extract, don't echo.** Pull the one field you need (a single action, one
   run's error) and discard the rest before reasoning.
2. **Summarize for the user.** Echo `name + state + trigger` for flow lists and
   `actionName + status + code` for run errors — not raw JSON, unless asked.
3. **Reach unlistable flows by id.** `list_flows` only returns flows you own or
   are shared with; for service-account-owned flows, go direct with `get_flow` /
   `get_flow_definition` using the flow id.

---

## Example Prompts

- "List my Power Automate environments." → `check_auth` / `list_environments`
- "Show the last 10 runs for flow `<id>` and explain the failures." → `get_flow_runs` → `get_flow_run_details`
- "Read `contoso_ApiBaseUrl` in my dev environment." → `get_environment_variable`
- "Repoint `contoso_ApiBaseUrl` to `https://new/...` — preview first, then apply." → `update_environment_variable` (confirm=False → confirm=True)
- "Disable flow `<id>`." → `set_flow_state` (stop)

---

## Reference

- Server + full docs (MIT): https://github.com/prasadgd9022/power-automate-mcp
- `SETUP.md` in that repo is written for an agent to perform registration automatically.
- Model Context Protocol: https://modelcontextprotocol.io
