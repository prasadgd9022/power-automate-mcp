# SETUP.md — Instructions for the Copilot agent

> **Audience: the Copilot CLI agent setting this up on the user's machine.**
> Follow these steps in order. Detect the OS and adapt paths/commands. Do **not** hard-code the
> original author's paths — always resolve paths relative to *this* folder on *this* machine.
> Report the result of each step and stop to ask the user only if a step genuinely fails.

## Step 0 — Locate the package
- Determine the **absolute path of the folder containing this `SETUP.md`** (it also contains
  `server.py`, `probe.py`, `requirements.txt`). Call it `PKG_DIR`.
- Compute `SERVER_PATH = <PKG_DIR>/server.py`.

## Step 1 — Verify Python 3.10+
- Run `python --version` (fall back to `py -3 --version`, then `python3 --version`).
- If none reports **3.10 or newer**, tell the user to install Python from
  https://www.python.org/downloads/ (Windows: tick "Add python.exe to PATH"), then stop.
- Remember which interpreter command worked; call it `PY`. Use it consistently below and in the
  MCP config (`command`).

## Step 2 — Install dependencies
- Run: `<PY> -m pip install -r "<PKG_DIR>/requirements.txt"`
- If pip is missing, run `<PY> -m ensurepip --upgrade` first, then retry.

## Step 3 — Ensure Azure CLI + sign-in
- Run `az version`. If missing, tell the user to install it from https://aka.ms/installazurecli
  and stop.
- Run `az account show`. If it errors (not logged in), run `az login`.
- **Windows only, to avoid a first-call timeout:** warm the token cache with
  `az account get-access-token --scope https://service.flow.microsoft.com/.default`.

## Step 4 — Register the MCP server in Copilot config
- Config file path:
  - Windows: `%USERPROFILE%\.copilot\mcp-config.json`
  - macOS/Linux: `$HOME/.copilot/mcp-config.json`
- If the file **does not exist**, create it with this content (use the real `SERVER_PATH` and the
  `PY` command; on Windows escape backslashes in JSON as `\\`):
  ```json
  {
    "mcpServers": {
      "power-automate": {
        "type": "stdio",
        "tools": ["*"],
        "command": "python",
        "args": ["<SERVER_PATH>", "--transport", "stdio"]
      }
    }
  }
  ```
- If the file **already exists**, parse it as JSON and **merge**: add/replace only the
  `power-automate` key inside the existing `mcpServers` object. Preserve all other servers and
  settings. Make a timestamped backup (e.g. `mcp-config.json.bak-<yyyyMMddHHmmss>`) before
  writing.
- Set `command` to the interpreter from Step 1 (`python`, `py`, or `python3`). If `py` was used,
  set `command` to `py` and prepend `"-3"` to `args`.

## Step 5 — Verify the server works
- Run: `<PY> "<PKG_DIR>/probe.py"`
- Success looks like:
  ```
  TOOLS: ['check_auth', 'list_environments', 'list_flows', 'get_flow', 'get_flow_runs', 'get_flow_run_details', 'set_flow_state', 'get_environment_variable', 'update_environment_variable', 'get_flow_definition', 'update_flow_definition']
  CHECK_AUTH_OK: { ... "authenticated": true, "environmentCount": N ... }
  ```
- If `CHECK_AUTH_ERROR` mentions tokens/credentials, revisit Step 3 (`az login`).
- If `TOOLS` prints but auth fails, the server is registered correctly; auth is a sign-in issue,
  not a setup issue.

## Step 6 — Final
- Tell the user to **restart the Copilot CLI** so it loads the new server.
- Confirm they can now ask Copilot things like *"list my Power Automate environments"* or
  *"show recent runs for flow &lt;id&gt;"*.

---

### Expected tool list (for validation)
`check_auth`, `list_environments`, `list_flows`, `get_flow`, `get_flow_runs`,
`get_flow_run_details`, `set_flow_state`, `get_environment_variable`,
`update_environment_variable`, `get_flow_definition`, `update_flow_definition`.

### Notes
- The server is lazy: it only acquires an Azure token on the **first** tool call, so
  registration succeeds even before `az login`.
- **Read-only tools:** `check_auth`, `list_environments`, `list_flows`, `get_flow`,
  `get_flow_runs`, `get_flow_run_details`, `get_environment_variable`, `get_flow_definition`.
- **Write tools:** `set_flow_state` (enable/disable a flow) and the two Dataverse skills
  `update_environment_variable` and `update_flow_definition`. The two Dataverse writes are
  **guarded by `confirm=True`** — called with `confirm=False` (the default) they only return a
  dry-run preview and change nothing. `update_environment_variable` edits only the
  per-environment *current value*, leaving the shared default (and other environments) untouched.
- The Dataverse write skills call the environment's Dataverse Web API
  (`https://<org>.crm.dynamics.com`), using an org-scoped token from the same `az login` session.
