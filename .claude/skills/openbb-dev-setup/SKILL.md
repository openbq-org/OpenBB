---
name: openbb-dev-setup
description: Set up / verify OpenBB monorepo dev environment (platform, cli, desktop). Use when user asks to run, build, or check errors in this repo.
---

# OpenBB dev setup

Repo layout: `openbb_platform/` (Python, poetry), `cli/` (Python, poetry), `desktop/` (Tauri: React+Vite frontend, Rust backend).

## Known environment gotchas (this machine)

- System Python was 3.14 — too new, poetry/openbb deps target `>=3.10,<4` but many provider packages lag behind on 3.14 support. Install Python 3.11 separately (pyenv-win or python.org), do NOT rely on system 3.14 alone.
- `poetry` not installed by default: `pip install poetry`.
- `uv` not present — fine, project uses poetry not uv.
- Node 24 / npm 11 / rustc+cargo 1.97 were already present and sufficient for `desktop/`.

## Check for errors fast

```bash
git status --short
git diff --stat
```
If only `desktop/src-tauri/Cargo.toml` and `desktop/src/routeTree.gen.ts` show modified with no content diff (`git diff --ignore-all-space --numstat` empty) — it's just CRLF/LF line-ending churn from git autocrlf on Windows, not a real change. Safe to ignore or `git checkout -- <file>`.

## Install / run

Platform + CLI (needs Python 3.10/3.11, poetry):
```bash
cd openbb_platform
poetry install
python dev_install.py
```

Desktop app:
```bash
cd desktop
npm install
npm run tauri dev
```

Quick python import check:
```bash
python -c "import openbb; print(openbb.__version__)"
```
`ModuleNotFoundError: No module named 'openbb'` means dev_install.py hasn't been run yet in the active venv.
