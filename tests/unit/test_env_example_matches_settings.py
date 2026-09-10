"""env.example is the path most people copy, so its values must be the shipped defaults."""

import re
from pathlib import Path

import pytest

from ignis.config import Settings
from ignis.interfaces.cli.scheduler import resolve_ingress_interval

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / "env.example"

# Settings a copied env.example must not silently move off their default. Credentials and
# connection strings are excluded: those are placeholders and are meant to be edited.
PINNED_TO_DEFAULT = [
    "SYNC_INTERVAL_MINUTES",
    "SCHEDULER_INTERVAL_SECONDS",
    "DISCOVERY_INTERVAL_HOURS",
    "DEFAULT_GEO",
    "META_INSIGHTS_CACHE_TTL_SECONDS",
]


def parse_env_example():
    values = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


@pytest.fixture(scope="module")
def env_example():
    return parse_env_example()


@pytest.mark.parametrize("name", PINNED_TO_DEFAULT)
def test_example_value_matches_the_settings_default(name, env_example):
    assert name in env_example, f"{name} is missing from env.example"
    expected = Settings.model_fields[name].default
    assert type(expected)(env_example[name]) == expected


# Read by docker-compose.prod.yml to build the container's DATABASE_URL, never by Settings.
COMPOSE_ONLY = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT"}


def test_every_example_key_is_a_real_setting(env_example):
    unknown = sorted(set(env_example) - set(Settings.model_fields) - COMPOSE_ONLY)
    assert not unknown, f"env.example documents settings that do not exist: {unknown}"


def test_compose_only_keys_are_still_consumed_by_compose(env_example):
    compose = (ENV_EXAMPLE.parent / "docker-compose.prod.yml").read_text(encoding="utf-8")
    for name in COMPOSE_ONLY:
        assert name in env_example, f"{name} is exempted but missing from env.example"
        assert f"${{{name}" in compose, f"{name} is exempted but no longer used by compose"


def test_copied_example_keeps_the_quota_safe_ingress_interval(env_example):
    # SYNC_INTERVAL_MINUTES overrides SCHEDULER_INTERVAL_SECONDS whenever it is above 0, so
    # the two lines have to be read together to know what a copied file actually schedules.
    resolved = resolve_ingress_interval(
        sync_minutes=int(env_example["SYNC_INTERVAL_MINUTES"]),
        scheduler_seconds=int(env_example["SCHEDULER_INTERVAL_SECONDS"]),
    )
    assert resolved == Settings.model_fields["SCHEDULER_INTERVAL_SECONDS"].default
