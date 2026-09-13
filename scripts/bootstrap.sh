#!/usr/bin/env bash
# ==============================================================================
# fn-ignis 🔥 Zero-Touch Agent Bootstrap & Auto-Provisioning Script
# Designed for AI Agents (Claude Desktop, Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, Pi Agent)
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
#
# The reproducible path is `uv sync --locked`, which installs the exact solution recorded in the
# committed uv.lock and refuses to run when that lock disagrees with pyproject.toml. The previous
# `uv pip install -e .` re-resolved from the dependency ranges instead, so two people bootstrapping
# the same commit on different days could get different versions and the lock proved nothing.
#
# `--locked` rather than `--frozen`: --frozen uses the lock without checking it, so a stale lock
# passes silently, which is the failure this is meant to catch.
#
# `--inexact` leaves packages the lock does not mention in place. On a fresh checkout there are
# none, so the result is exactly the locked set. On a checkout that already has a developer
# environment, it means a setup script does not silently uninstall the test tooling -- a pruning
# sync of the runtime-only set removes pytest and ruff, and the documented `.venv/bin/pytest tests/`
# gate stops working. Contributors add the test extras with:
#     uv sync --locked --inexact --extra dev --extra browser
activate_venv() {
    if [ -f ".venv/bin/activate" ]; then
        # shellcheck disable=SC1091
        source .venv/bin/activate
    elif [ -f ".venv/Scripts/activate" ]; then
        # shellcheck disable=SC1091
        source .venv/Scripts/activate
    fi
}

if command -v uv >/dev/null 2>&1; then
    echo "⚡ Using 'uv' with the committed lock (reproducible)..."
    if [ ! -d ".venv" ]; then
        uv venv --python "$PYTHON_CMD"
    fi
    activate_venv
    if ! uv sync --locked --inexact; then
        echo ""
        echo "❌ Error: could not install the locked environment."
        echo "   If uv reported that the lockfile is out of date, pyproject.toml and uv.lock have"
        echo "   diverged. Do not hand-edit uv.lock. Regenerate and commit it with the reason:"
        echo ""
        echo "       uv lock"
        echo ""
        echo "   Any other failure is a genuine install error; the message above says which."
        exit 1
    fi
    echo "🔒 Installed the exact solution recorded in uv.lock."
else
    echo "📦 'uv' not detected; falling back to standard venv & pip."
    echo "⚠️  This fallback is NOT reproducible: pip resolves from the dependency ranges in"
    echo "   pyproject.toml and ignores uv.lock, so the versions it picks depend on the day it runs."
    echo "   Install uv (https://docs.astral.sh/uv/) to get the locked environment."
    if [ ! -d ".venv" ]; then
        "$PYTHON_CMD" -m venv .venv
    fi
    activate_venv
    python -m pip install --upgrade pip
    if ! python -m pip install -e .; then
        echo ""
        echo "❌ Error: pip could not install fn-ignis from this checkout."
        echo "   Re-read the pip output above for the failing dependency, then retry. Installing uv"
        echo "   and rerunning this script is usually faster and gives the reproducible path."
        exit 1
    fi
    echo "⚠️  Best-effort install complete (non-frozen)."
fi

# 3. Run Universal Auto-Provisioner (Multi-Client MCP + Database Bootstrap)
python -m ignis.interfaces.cli.setup_bundle "$@"

echo "✅ [fn-ignis] Zero-Touch Setup completed successfully."
