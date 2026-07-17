# Local Power Automate MCP Server

A **self-hosted** [Model Context Protocol](https://modelcontextprotocol.io) (MCP)
server that lets an AI assistant (GitHub Copilot CLI, etc.) inspect and manage
your **Microsoft Power Automate** cloud flows — and the **Dataverse** records
behind them — directly from your own machine, using **your own identity**.

- ✅ Runs **locally** as a stdio subprocess of the MCP host (e.g. Copilot CLI).
- ✅ Authenticates with **your** `az login` session (Azure CLI credential),
  falling back to an interactive browser sign-in.
- ✅ **No third-party SaaS** — no flow data ever leaves your device. The process
  talks straight to `https://api.flow.microsoft.com` and your environment's
  Dataverse Web API over HTTPS.
- ✅ **Safe by default** — every write to Dataverse requires an explicit
  `confirm=True`; without it you get a dry-run preview and nothing changes.

It was built as a privacy-safe alternative to hosted offerings that route your
tenant's flow data through an external vendor's cloud.

---

## Table of contents

- [How it works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Verify it works](#verify-it-works)
- [Tool reference](#tool-reference) — what each of the 11 tools is for
- [Safety model](#safety-model)
- [Configuration (env vars)](#configuration-env-vars)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [License](#license)

---

## How it works

The server exposes a set of **tools** to your MCP host. When the assistant calls
a tool, the server:

1. Acquires a bearer token for the right API using your local Azure CLI login
   (tokens are cached per scope and refreshed automatically).
2. Calls one of two Microsoft APIs:
   - the **Power Automate REST API** (`https://api.flow.microsoft.com`) for
     listing environments, flows, runs, and turning flows on/off; or
   - the environment's **Dataverse Web API**
     (`https://<org>.crm.dynamics.com/api/data/v9.2`) for reading/updating
     environment variables and raw flow definitions.
3. Returns compact JSON (truncated if it would overflow the model's context).

Nothing runs at import time, so the server starts instantly and only prompts for
auth on the **first** tool call.

---

## Prerequisites

- **Python 3.10+** on your `PATH` (`python --version`).
- **Azure CLI** installed and signed in — [install](https://aka.ms/installazurecli),
  then run `az login` once.
- Python packages (installed in [Setup](#setup)): `mcp`, `azure-identity`, `requests`.
- An MCP host that launches stdio servers (e.g. **GitHub Copilot CLI**).

---

## Setup

### 1. Get the code

```bash
git clone https://github.com/prasadgd9022/power-automate-mcp.git
cd power-automate-mcp
```

### 2. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. Sign in to Azure

```bash
az login
```

The server requests a token for `https://service.flow.microsoft.com/` (Flow API)
and, for the Dataverse skills, an org-scoped token for your environment — both
minted from this same session.

### 4. Register the server with your MCP host

Add a `power-automate` entry to your MCP host's config. For **GitHub Copilot CLI**
that file is:

- Windows: `%USERPROFILE%\.copilot\mcp-config.json`
- macOS / Linux: `$HOME/.copilot/mcp-config.json`

```jsonc
{
  "mcpServers": {
    "power-automate": {
      "type": "stdio",
      "tools": ["*"],
      "command": "python",
      "args": ["<ABSOLUTE_PATH_TO>/power-automate-mcp/server.py", "--transport", "stdio"]
    }
  }
}
```

Replace `<ABSOLUTE_PATH_TO>` with the folder where you cloned the repo. On
Windows, escape backslashes in JSON (e.g.
`"C:\\Users\\you\\power-automate-mcp\\server.py"`). If the file already exists,
**merge** this `power-automate` key into the existing `mcpServers` object rather
than overwriting the file.

> There is also a `SETUP.md` written for an AI agent to perform this
> registration for you automatically.

### 5. Restart your MCP host

Restart the Copilot CLI so it picks up the new server.

---

## Verify it works

From the repo folder:

```bash
python probe.py
```

Expected output (auth prompt may appear on first run):

```
TOOLS: ['check_auth', 'list_environments', 'list_flows', 'get_flow', 'get_flow_runs', 'get_flow_run_details', 'set_flow_state', 'get_environment_variable', 'update_environment_variable', 'get_flow_definition', 'update_flow_definition']
CHECK_AUTH_OK: { ... "authenticated": true, "environmentCount": N ... }
```

If `TOOLS` prints but auth fails, the server is registered correctly and the
issue is just sign-in — run `az login` again.

---

## Tool reference

**11 tools.** 8 are read-only; 3 write. All environment arguments are optional —
omit them to use your default environment.

### Read-only tools

| Tool | What it's for | Key args |
| ---- | ------------- | -------- |
| `check_auth` | Confirm the server can authenticate and list the environments you can reach. Run this first. | – |
| `list_environments` | List every Power Platform environment visible to your account (name, display name, default flag, region). | – |
| `list_flows` | List cloud flows in an environment that you own or that are shared with you. | `environment`, `top` |
| `get_flow` | Get a flow's full definition from the Flow REST API (triggers, actions, connection references). | `flow_name`, `environment` |
| `get_flow_runs` | Get recent run history for a flow (status, start/end, error codes). Great for triage. | `flow_name`, `environment`, `top` |
| `get_flow_run_details` | Get full details of a single run, including the error payload. | `flow_name`, `run_name`, `environment` |
| `get_environment_variable` | Read an environment variable's definition, **default value**, and per-environment **current value** (from Dataverse). Use before updating one to see the value id. | `schema_name`, `environment` |
| `get_flow_definition` | Read a flow's underlying Dataverse `workflow` row, including the raw `clientdata` JSON that `update_flow_definition` edits. | `flow_id`, `environment` |

### Write tools

| Tool | What it's for | Key args |
| ---- | ------------- | -------- |
| `set_flow_state` | Enable (`start`) or disable (`stop`) a flow via the Flow REST API. | `flow_name`, `state`, `environment` |
| `update_environment_variable` | Update an environment variable's **current value only** (per-environment override) — the safe way to repoint a flow's function-app URL, connection string, etc. without editing the flow. The shared default is left untouched. | `schema_name`, `new_value`, `environment`, `confirm` |
| `update_flow_definition` | **Advanced.** Overwrite a flow's entire `clientdata` definition JSON in Dataverse. Use only when you must change the definition itself. | `flow_id`, `clientdata`, `environment`, `confirm` |

### Example prompts

Once registered, you can ask your assistant things like:

- "List my Power Automate environments."
- "Show the last 10 runs for flow `<flow-id>` and tell me why the failures failed."
- "Read the environment variable `contoso_ApiBaseUrl` in my dev environment."
- "Repoint `contoso_ApiBaseUrl` to `https://new-endpoint/...` — preview first,
  then apply." (dry-run, then `confirm=True`)
- "Disable flow `<flow-id>`."

---

## Safety model

The three write tools are designed to be hard to misuse:

- **`update_environment_variable` and `update_flow_definition` require `confirm=True`.**
  Called with `confirm=False` (the default) they return a **dry-run preview**
  (old value → new value, or a validity check) and change **nothing**.
- **`update_environment_variable` only touches the per-environment *current
  value*.** The shared *default value* — and therefore other environments such
  as Production — are left untouched. This makes it the preferred way to repoint
  a URL or connection string for a single environment.
- **`update_flow_definition` is the advanced escape hatch.** It fully overwrites
  the flow's `clientdata` (definition + connection references), so the string you
  pass must be complete and valid. Recommended flow:
  1. `get_flow_definition` and keep the returned `clientdata`,
  2. make your minimal edit to that JSON,
  3. call with `confirm=False` to preview / validate JSON,
  4. call with `confirm=True` to apply.
- **`set_flow_state`** simply starts/stops a flow (no dry-run — enabling/disabling
  is easily reversible).

---

## Configuration (env vars)

All optional — the defaults work for standard commercial Microsoft 365 tenants.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `PA_MCP_ACCESS_TOKEN` | – | Supply a raw bearer token (skips CLI/browser). Advanced/CI. |
| `PA_MCP_SCOPE` | `https://service.flow.microsoft.com/.default` | Token scope for the Flow API. |
| `PA_MCP_API_HOST` | `https://api.flow.microsoft.com` | Flow API host (change for sovereign clouds). |
| `PA_MCP_API_VERSION` | `2016-11-01` | Flow API version. |
| `PA_MCP_DATAVERSE_API_VERSION` | `v9.2` | Dataverse Web API version (write skills). |
| `PA_MCP_HTTP_TIMEOUT` | `60` | HTTP timeout in seconds. |
| `PA_MCP_MAX_RESPONSE_CHARS` | `60000` | Truncate oversized tool payloads. |

---

## Troubleshooting

- **`Could not acquire a token` / auth errors** — run `az login`, then retry.
  On Windows you can warm the cache with
  `az account get-access-token --scope https://service.flow.microsoft.com/.default`.
- **`list_flows` returns 0 flows** — the Flow REST API only lists flows you
  **own or are shared with**. Flows owned by a service account or another user
  won't appear; reach them directly by id with `get_flow` / `get_flow_definition`.
- **Dataverse tool says the environment has no linked instance** — the write
  skills require a Dataverse-backed environment (most standard environments are).
- **`403 Forbidden` from Dataverse** — your account lacks permission on that
  environment's Dataverse org; this is expected for environments you can't administer.

---

## Uninstall

Remove the `power-automate` block from your MCP host's config
(`~/.copilot/mcp-config.json` for Copilot CLI), restart the host, and delete this
folder.

---

## License

[MIT](LICENSE).
