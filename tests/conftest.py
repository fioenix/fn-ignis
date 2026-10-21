import os
from collections.abc import MutableMapping
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import pytest


# Pytest is an isolated verification process, never a production runtime. Quarantine credentials
# before importing ignis because its settings singleton is created during module import. This both
# prevents accidental real API/database calls and keeps assertion introspection from echoing an
# inherited shell credential into a local or public CI transcript.
PYTEST_CREDENTIAL_OVERRIDES = {
    "DATABASE_URL": "sqlite:///ignis.db",
    "YOUTUBE_API_KEY": "",
    "IGNIS_ENCRYPTION_KEY": "",
    "THREADS_APP_SECRET": "",
    "INSTAGRAM_APP_SECRET": "",
    "PLAYWRIGHT_PROXY_SERVER": "",
}
PYTEST_CREDENTIAL_REMOVALS = {
    "IGNIS_ENV_FILE",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "DOCKER_AUTH_CONFIG",
    "DOCKER_REGISTRY_PASSWORD",
    "PGPASSWORD",
}


def quarantine_ambient_credentials(environment: MutableMapping[str, str]) -> None:
    """Replace host credentials with inert test values without retaining plaintext copies."""
    environment.update(PYTEST_CREDENTIAL_OVERRIDES)
    for name in PYTEST_CREDENTIAL_REMOVALS:
        environment.pop(name, None)


quarantine_ambient_credentials(os.environ)


def select_worker_postgres(environment: MutableMapping[str, str]) -> None:
    """Point each pytest-xdist worker at its own PostgreSQL server.

    Databases are per test, but roles are per server: the RLS and runtime-owner contracts create
    and drop `anon`, `authenticated` and `ignis_test_runtime_owner`, and some assert a server has
    none of them. Two workers on one server would break each other, so a parallel run that reaches
    PostgreSQL needs one server per worker, listed comma-separated in
    IGNIS_TEST_POSTGRES_DSN_POOL. A serial run is unaffected.
    """
    worker = environment.get("PYTEST_XDIST_WORKER", "")
    if not worker.startswith("gw"):
        return
    pool = [dsn.strip() for dsn in environment.get("IGNIS_TEST_POSTGRES_DSN_POOL", "").split(",") if dsn.strip()]
    if not pool:
        if environment.get("IGNIS_TEST_POSTGRES_DSN", "").strip():
            raise pytest.UsageError(
                "A parallel run cannot share one PostgreSQL server between workers; set"
                " IGNIS_TEST_POSTGRES_DSN_POOL to one server per worker, or run serially."
            )
        return
    workers = int(environment.get("PYTEST_XDIST_WORKER_COUNT", "1"))
    if workers > len(pool):
        raise pytest.UsageError(
            f"{workers} workers but {len(pool)} PostgreSQL servers in IGNIS_TEST_POSTGRES_DSN_POOL;"
            " each worker needs its own."
        )
    environment["IGNIS_TEST_POSTGRES_DSN"] = pool[int(worker[2:])]


select_worker_postgres(os.environ)


# Test files whose tests share no module or session fixture and run long enough that holding the
# whole file on one worker leaves the others idle: on main's CI of 21/10/2026 the RLS file alone
# kept one worker busy 100 s after the other three had finished.
SPREAD_ACROSS_WORKERS = frozenset({
    "tests/integration/test_postgres_rls_coverage.py",
    "tests/unit/test_caller_youtube_pilot_cli.py",
})


def pytest_collection_modifyitems(config, items):
    """Under --dist loadgroup, keep each file on one worker except SPREAD_ACROSS_WORKERS.

    A test with no xdist_group mark is scheduled on its own, so marking every other test with its
    file reproduces --dist loadfile for them and spreads only the listed files' tests.
    """
    if getattr(config.option, "dist", "no") != "loadgroup":
        return
    for item in items:
        path = item.nodeid.split("::", 1)[0]
        if path not in SPREAD_ACROSS_WORKERS:
            item.add_marker(pytest.mark.xdist_group(path))

from ignis.domain.entities import TrendSignal, TopicCluster  # noqa: E402
from ignis.domain.value_objects import PlatformType, GeoCode  # noqa: E402


CHECKOUT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def never_use_the_checkout_as_caller_root(monkeypatch):
    """Fail a test that would place caller storage in this checkout's own .fnignis/.

    The caller root is the folder the server started in, and pytest runs from the checkout. A test
    that forgets to bind a temporary root must fail here instead of writing the owner's real store.
    The tool call is refused before storage opens, and the test fails at teardown even when the MCP
    server turns the refusal into an error result the test never inspects. A stdio server process
    is not covered; those tests start the server in a temporary folder.
    """
    from fastmcp.exceptions import ToolError
    from ignis.infrastructure.caller_storage import CallerStorageMiddleware
    resolved = []
    for name in ("_checked_startup_root", "_checked_configured_root"):
        original = getattr(CallerStorageMiddleware, name)

        def guarded(self, ctx, _original=original):
            path = _original(self, ctx)
            if Path(path).resolve() == CHECKOUT_ROOT:
                resolved.append(path)
                raise ToolError("CHECKOUT_CALLER_ROOT_GUARD")
            return path
        monkeypatch.setattr(CallerStorageMiddleware, name, guarded)
    yield
    if resolved:
        pytest.fail("A test resolved the checkout as its caller root; "
                    "bind a temporary root with tests.caller_roots.bind_caller_root")


@pytest.fixture
def sample_trend_signal():
    return TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title="AI Agent Trends 2026",
        metric_value=50000.0,
        growth_velocity=12.5,
        source_url="https://trends.google.com/sample",
        geo_code=GeoCode.VN,
        metadata={"traffic": "50K+", "news": "AI agent adoption surges"},
        captured_at=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_youtube_signal():
    return TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Top Emerging Tech in Vietnam 2026",
        metric_value=1200000.0,
        growth_velocity=25.0,
        source_url="https://youtube.com/watch?v=sample123",
        geo_code=GeoCode.VN,
        metadata={"channel_title": "TechVN", "likes": 45000, "comments": 3200},
        captured_at=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_topic_cluster():
    return TopicCluster(
        id=uuid4(),
        canonical_name="Generative AI & Autonomous Agents",
        summary_text="Sự bùng nổ của các giải pháp AI tự hành và FastMCP",
        category="technology",
        cross_platform_score=88.5,
        first_seen_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc)
    )
