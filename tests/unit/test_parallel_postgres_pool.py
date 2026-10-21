"""Each pytest-xdist worker reaches its own PostgreSQL server, or the run refuses to start."""

import runpy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
POOL = "postgresql://a@h:5432/p,postgresql://b@h:5433/p, postgresql://c@h:5434/p ,postgresql://d@h:5435/p"


@pytest.fixture(scope="module")
def select():
    return runpy.run_path(str(REPO_ROOT / "tests" / "conftest.py"))["select_worker_postgres"]


def test_a_serial_run_keeps_its_dsn(select):
    environment = {"IGNIS_TEST_POSTGRES_DSN": "postgresql://serial@h/p", "IGNIS_TEST_POSTGRES_DSN_POOL": POOL}
    select(environment)
    assert environment["IGNIS_TEST_POSTGRES_DSN"] == "postgresql://serial@h/p"


@pytest.mark.parametrize("worker,expected", [
    ("gw0", "postgresql://a@h:5432/p"),
    ("gw2", "postgresql://c@h:5434/p"),
    ("gw3", "postgresql://d@h:5435/p"),
])
def test_each_worker_gets_its_own_server(select, worker, expected):
    environment = {
        "PYTEST_XDIST_WORKER": worker,
        "PYTEST_XDIST_WORKER_COUNT": "4",
        "IGNIS_TEST_POSTGRES_DSN": "postgresql://a@h:5432/p",
        "IGNIS_TEST_POSTGRES_DSN_POOL": POOL,
    }
    select(environment)
    assert environment["IGNIS_TEST_POSTGRES_DSN"] == expected


def test_more_workers_than_servers_is_refused(select):
    environment = {
        "PYTEST_XDIST_WORKER": "gw0",
        "PYTEST_XDIST_WORKER_COUNT": "5",
        "IGNIS_TEST_POSTGRES_DSN_POOL": POOL,
    }
    with pytest.raises(pytest.UsageError, match="5 workers but 4"):
        select(environment)


def test_a_parallel_run_never_shares_the_single_server(select):
    environment = {
        "PYTEST_XDIST_WORKER": "gw1",
        "PYTEST_XDIST_WORKER_COUNT": "2",
        "IGNIS_TEST_POSTGRES_DSN": "postgresql://serial@h/p",
    }
    with pytest.raises(pytest.UsageError, match="IGNIS_TEST_POSTGRES_DSN_POOL"):
        select(environment)


def test_a_parallel_run_without_postgres_is_left_alone(select):
    environment = {"PYTEST_XDIST_WORKER": "gw1", "PYTEST_XDIST_WORKER_COUNT": "2"}
    select(environment)
    assert "IGNIS_TEST_POSTGRES_DSN" not in environment


class _Item:
    def __init__(self, nodeid):
        self.nodeid = nodeid
        self.marks = []

    def add_marker(self, mark):
        self.marks.append(mark)


@pytest.fixture(scope="module")
def root_conftest():
    return runpy.run_path(str(REPO_ROOT / "tests" / "conftest.py"))


def _config(dist):
    from types import SimpleNamespace
    return SimpleNamespace(option=SimpleNamespace(dist=dist))


def test_loadgroup_keeps_files_together_except_the_spread_ones(root_conftest):
    spread = sorted(root_conftest["SPREAD_ACROSS_WORKERS"])[0]
    kept, split = _Item("tests/unit/test_x.py::test_a"), _Item(f"{spread}::test_b")
    root_conftest["pytest_collection_modifyitems"](_config("loadgroup"), [kept, split])
    assert [(m.name, m.args) for m in kept.marks] == [("xdist_group", ("tests/unit/test_x.py",))]
    assert split.marks == []


@pytest.mark.parametrize("dist", ["no", "loadfile", "load"])
def test_other_modes_add_no_group(root_conftest, dist):
    item = _Item("tests/unit/test_x.py::test_a")
    root_conftest["pytest_collection_modifyitems"](_config(dist), [item])
    assert item.marks == []


def test_every_spread_file_exists(root_conftest):
    missing = [path for path in root_conftest["SPREAD_ACROSS_WORKERS"] if not (REPO_ROOT / path).is_file()]
    assert not missing, f"SPREAD_ACROSS_WORKERS names files that are gone: {missing}"
