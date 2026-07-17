# PUBLISH — push this to GitHub as `prasadgd9022/power-automate-mcp`

This package is **sanitized and ready to publish**. Run the steps below on the
machine that is (or will be) signed in to GitHub as **prasadgd9022**.

> The files here already contain **no personal paths, no secrets, and no live
> project/client references** — safe to make public.

---

## Prerequisites on the target machine

- [Git](https://git-scm.com/downloads) installed (`git --version`).
- [GitHub CLI](https://cli.github.com/) installed (`gh --version`) — optional but
  makes repo creation one command.

## Step 1 — Sign in to GitHub as prasadgd9022

```bash
gh auth login
# choose: GitHub.com → HTTPS → authenticate via browser/device code
gh auth status        # confirm it shows the prasadgd9022 account
```

If you prefer not to use `gh`, create the empty repo manually at
https://github.com/new (name: `power-automate-mcp`, **Public**, no README/license
— this package already provides them), then use the "without gh" commands in Step 4.

## Step 2 — Unzip and enter the folder

```bash
# after extracting power-automate-mcp-publish.zip
cd power-automate-mcp-publish
```

## Step 3 — Set the commit identity (so it's attributed to prasadgd9022)

```bash
git init
git config user.name  "prasadgd9022"
git config user.email "prasadgd9022@users.noreply.github.com"
```

> Using the GitHub `noreply` email keeps your real email out of the public commit
> history. You can find your exact noreply address in GitHub → Settings → Emails.

## Step 4 — Commit and push

**With GitHub CLI (recommended):**

```bash
git add .
git commit -m "Initial public release: local Power Automate MCP server (11 tools)"
gh repo create prasadgd9022/power-automate-mcp \
  --public --source . --remote origin --push \
  --description "Privacy-safe local MCP server for Power Automate + Dataverse"
```

**Without GitHub CLI** (after creating the empty public repo on github.com):

```bash
git add .
git commit -m "Initial public release: local Power Automate MCP server (11 tools)"
git branch -M main
git remote add origin https://github.com/prasadgd9022/power-automate-mcp.git
git push -u origin main
```

## Step 5 — Verify

- Open https://github.com/prasadgd9022/power-automate-mcp and confirm the README
  renders and the repo is **Public**.
- (Optional) In a fresh clone: `pip install -r requirements.txt` then
  `python probe.py` → should list all **11 tools**.

## Step 6 — (Optional) tag a release

```bash
git tag v1.0.0
git push origin v1.0.0
```

---

## What's in this package

| File | Purpose |
| ---- | ------- |
| `server.py` | The MCP server (11 tools: 8 read, 3 write). |
| `README.md` | Full setup guide + tool reference + safety model. |
| `SETUP.md` | Agent-oriented auto-setup instructions. |
| `requirements.txt` | Python dependencies (`mcp`, `azure-identity`, `requests`). |
| `probe.py` | Self-test that lists tools and runs `check_auth`. |
| `LICENSE` | MIT license. |
| `.gitignore` | Excludes caches, venvs, and secrets. |
| `PUBLISH.md` | This file — delete it after publishing if you like. |

## Notes

- **License** is MIT with copyright "prasadgd9022" — change the name/year in
  `LICENSE` if desired.
- If you'd rather not publish `PUBLISH.md` itself, delete it before `git add`.
