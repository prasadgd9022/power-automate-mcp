# Proposed contribution to `github/awesome-copilot`

This folder holds a **ready-to-submit skill** for the
[github/awesome-copilot](https://github.com/github/awesome-copilot) collection.
It is **not** part of the MCP server runtime — it is documentation intended to be
contributed upstream.

## What it is

`local-power-automate-mcp/SKILL.md` — a foundation skill describing how to drive
Power Automate from an AI agent using **this** self-hosted, privacy-first MCP
server (`az login` identity, local stdio, no third-party SaaS).

## Why it's a non-duplicative contribution

awesome-copilot already ships the `flowstudio-power-automate-*` skill family, but
those are built entirely around a **paid, hosted** MCP (remote HTTP endpoint,
`x-api-key` JWT, tenant data routed through the vendor cloud). This skill fills
the gap they don't cover:

- **Self-hosted / local stdio** server instead of a remote SaaS endpoint.
- **`az login` (Azure CLI) identity** auth instead of portal-issued API keys.
- **Privacy / data-residency model** — nothing leaves the machine.
- **`confirm=True` dry-run** write-safety pattern for Dataverse writes.
- **Per-environment env-var** nuance (current value vs shared default).
- **Sovereign / government-cloud** configuration via `PA_MCP_*` env vars.

## How to submit it upstream

1. Fork and clone `github/awesome-copilot`.
2. Scaffold the skill folder:
   ```bash
   npm run skill:create -- --name local-power-automate-mcp \
     --description "Self-hosted, privacy-first Power Automate MCP (az login, local stdio)"
   ```
3. Replace the generated `skills/local-power-automate-mcp/SKILL.md` with the file
   in this folder.
4. Validate and regenerate the README tables:
   ```bash
   npm run skill:validate
   npm run build
   ```
5. Open a pull request.

See the awesome-copilot `CONTRIBUTING.md` (**Adding Skills**) for full details.
Because this server is open source (MIT) and not a paid service, the paid-service
submission path does not apply.
