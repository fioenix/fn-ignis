"""env.example is the path most people copy, so its values must be the shipped defaults."""

import json
import re
from pathlib import Path

import pytest
import yaml

from ignis.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / "env.example"

# Settings a copied env.example must not silently move off their default. Credentials and
# connection strings are excluded: those are placeholders and are meant to be edited.
PINNED_TO_DEFAULT = [
    "DEFAULT_GEO",
    "META_INSIGHTS_CACHE_TTL_SECONDS",
    "YOUTUBE_SEARCH_DAILY_LIMIT",
    "YOUTUBE_SCHEDULED_SEARCH_DAILY_LIMIT",
    "YOUTUBE_OTHER_DAILY_UNIT_LIMIT",
]


def test_settings_expose_youtube_quota_policy_defaults():
    loaded = Settings(_env_file=None)

    assert loaded.YOUTUBE_SEARCH_DAILY_LIMIT == 100
    assert loaded.YOUTUBE_SCHEDULED_SEARCH_DAILY_LIMIT == 70
    assert loaded.YOUTUBE_OTHER_DAILY_UNIT_LIMIT == 10_000


def test_public_launchers_expose_all_youtube_quota_overrides():
    expected_env = {
        "YOUTUBE_SEARCH_DAILY_LIMIT",
        "YOUTUBE_SCHEDULED_SEARCH_DAILY_LIMIT",
        "YOUTUBE_OTHER_DAILY_UNIT_LIMIT",
    }
    repo = Path(__file__).resolve().parents[2]
    openclaw = json.loads((repo / "openclaw.json").read_text(encoding="utf-8"))
    assert expected_env <= set(openclaw["transport"]["env"])

    smithery = yaml.safe_load((repo / "smithery.yaml").read_text(encoding="utf-8"))
    properties = set(smithery["startCommand"]["configSchema"]["properties"])
    assert {
        "youtubeSearchDailyLimit",
        "youtubeScheduledSearchDailyLimit",
        "youtubeOtherDailyUnitLimit",
    } <= properties


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


def test_copied_example_exposes_no_recurring_collection_cadence(env_example):
    assert not {
        "SYNC_INTERVAL_MINUTES",
        "SCHEDULER_INTERVAL_SECONDS",
        "DISCOVERY_INTERVAL_HOURS",
    } & set(env_example)
