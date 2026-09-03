#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Run universal zero-touch bootstrap
"$DIR/scripts/bootstrap.sh" "$@"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if [ -f "docker-compose.yml" ]; then
        echo "🚀 [fn-ignis] Optional Docker daemon detected. Starting worker background container if needed..."
        docker compose up -d --build || true
    fi
fi

echo "✅ Setup complete. AI Agents and MCP clients are ready to interact with fn-ignis."
