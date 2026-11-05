#!/bin/bash
# OpenBB Trading Desk - macOS / Linux launcher (double-click on macOS).
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "Installation de uv (gestionnaire Python)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh || { echo "[ERR] installation de uv échouée"; read -r -p "Entrée pour fermer"; exit 1; }
  export PATH="$HOME/.local/bin:$PATH"
fi
uv run --no-project --python 3.12 desk.py "$@"
code=$?
if [ -z "$1" ] || [ $code -ne 0 ]; then read -r -p "Entrée pour fermer"; fi
exit $code
