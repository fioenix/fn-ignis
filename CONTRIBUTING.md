# Contributing to fn-ignis 🚀

Thank you for your interest in contributing to `fn-ignis`!

## Code of Conduct

All contributors are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md).

## Development Setup

`fn-ignis` uses [`uv`](https://github.com/astral-sh/uv) for fast and deterministic Python package management.

### 1. Clone & Setup Virtual Environment
```bash
git clone https://github.com/fioenix/fn-ignis.git
cd fn-ignis

uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev,browser,ai]"
```

### 2. Configure Environment
```bash
cp env.example .env
# Edit .env with your local PostgreSQL/TimescaleDB and API credentials
```

### 3. Run Test Suite
```bash
uv run pytest
```

## 🌿 GitFlow Branching Model

`fnIgnis` follows the standard **GitFlow** branching workflow:

| Branch | Purpose | Base Branch | Merge Target |
|---|---|---|---|
| **`main`** | Stable, production-ready releases (tagged e.g. `v0.1.0`) | — | — |
| **`develop`** | Active integration branch for tested features | `main` | `main` (via release) |
| **`feature/*`** | New features, tools, or connector improvements | `develop` | `develop` |
| **`release/*`** | Release preparation, bump versions, docs stabilization | `develop` | `main` & `develop` |
| **`hotfix/*`** | Urgent production bug fixes | `main` | `main` & `develop` |

### Feature Workflow Example:
```bash
# 1. Start from latest develop
git checkout develop
git pull origin develop
git checkout -b feature/add-threads-voice-analysis

# 2. Implement, test, and commit
uv run pytest
git commit -m "feat(threads): add comment sentiment extractor"

# 3. Push and open Pull Request against develop
git push -u origin feature/add-threads-voice-analysis
```

## Pull Request & Review Standards

1. All PRs must target **`develop`** (except hotfixes which target `main`).
2. Automated GitHub Actions CI test suite must pass 100% on Python 3.12.
3. Commit messages must be atomic and start with standard verbs: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.

