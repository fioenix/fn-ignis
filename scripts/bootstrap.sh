#!/usr/bin/env bash
# ==============================================================================
# fn-ignis 🔥 Zero-Touch Agent Bootstrap & Auto-Provisioning Script
# Designed for AI Agents (Claude Code, Cursor, Windsurf, Antigravity, OpenClaw, Hermes, Devin)
# ==============================================================================
set -euo pipefail

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "🔥 [fn-ignis] Initializing Zero-Touch Autonomous Bootstrap..."

# 1. Detect Python Executable (>= 3.11 required)
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PY_VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 11 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "❌ Error: Python 3.11 or higher is required but not found in PATH."
    exit 1
fi

echo "🐍 Detected compatible Python: $PYTHON_CMD ($PY_VER)"

# 2. Manage Virtual Environment (.venv) & Package Installation
if command -v uv >/dev/null 2>&1; then
    echo "⚡ Using fast 'uv' package manager..."
    if [ ! -d ".venv" ]; then
        uv venv --python "$PYTHON_CMD"
    fi
    # Source venv
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    elif [ -f ".venv/Scripts/activate" ]; then
        source .venv/Scripts/activate
    fi
    uv pip install -e .
else
    echo "📦 'uv' not detected; falling back to standard venv & pip..."
    if [ ! -d ".venv" ]; then
        "$PYTHON_CMD" -m venv .venv
    fi
    # Source venv
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    elif [ -f ".venv/Scripts/activate" ]; then
        source .venv/Scripts/activate
    fi
    python -m pip install --upgrade pip
    python -m pip install -e .
fi

# 3. Run Universal Auto-Provisioner (Multi-Client MCP + Database Bootstrap)
python -m ignis.interfaces.cli.setup_bundle "$@"

echo "✅ [fn-ignis] Zero-Touch Setup completed successfully."
