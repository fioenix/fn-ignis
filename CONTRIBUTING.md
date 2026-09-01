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
cp .env.example .env
# Edit .env with your local PostgreSQL/TimescaleDB and API credentials
```

### 3. Run Test Suite
```bash
uv run pytest
```

## Contribution Guidelines

1. **Language Standard**: All source code, docstrings, comments, commit messages, and documentation must be in **100% English**.
2. **Deterministic Architecture**: Adhere to Domain-Driven Design (DDD) and Clean Architecture principles. Business logic resides in `application/use_cases`, platform connectors in `infrastructure/connectors`, and entities in `domain/`.
3. **Security First**: Never hardcode API keys, database credentials, or real session cookies.
4. **Testing**: Every new connector or use case must include comprehensive unit and integration tests.

## Pull Request Process

1. Fork the repository and create your feature branch: `git checkout -b feature/my-new-feature`.
2. Ensure all tests pass: `uv run pytest`.
3. Commit your changes with concise, conventional commit messages (`Add`, `Fix`, `Refactor`, `Update`).
4. Push to your branch and open a Pull Request.
