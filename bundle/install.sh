#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "🔥 [fn-ignis] Verifying environment and configuring Bundle..."
if [ ! -d ".venv" ]; then
    uv venv
fi
source .venv/bin/activate
uv pip install -e .
uv run python -m ignis.interfaces.cli.setup_bundle


echo "🚀 [fn-ignis] Rebuilding and restarting Docker Background Worker..."
docker compose up -d --build

echo "✅ Complete! Please restart Claude Desktop to load all updated tools and prompts."
