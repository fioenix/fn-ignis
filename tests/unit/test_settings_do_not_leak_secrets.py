"""A failing test prints repr(settings) into the CI log, so that repr must carry no secrets.

On a public repository those logs are world-readable. Before secrets were typed SecretStr, one
assertion failure inside any function holding a Settings reference put the database password,
the Fernet key and the YouTube API key into a log anyone could open.
"""

import re

import pytest
from pydantic import SecretStr

from ignis.config import Settings, reveal_secret

# Every setting whose value is credential material. THREADS_APP_ID / INSTAGRAM_APP_ID are OAuth
# client_ids, which are public by design, and the redirect URIs and API versions are not secrets.
SECRET_SETTINGS = [
    "DATABASE_URL",
    "YOUTUBE_API_KEY",
    "IGNIS_ENCRYPTION_KEY",
    "THREADS_APP_SECRET",
    "INSTAGRAM_APP_SECRET",
    "PLAYWRIGHT_PROXY_SERVER",
]

SENTINELS = {name: f"sentinel-value-for-{name.lower()}" for name in SECRET_SETTINGS}


@pytest.fixture
def loaded(tmp_path):
    """A Settings built from a .env holding a distinct sentinel per secret."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{name}={value}" for name, value in SENTINELS.items()) + "\n",
        encoding="utf-8",
    )
    return Settings(_env_file=str(env_file))


@pytest.mark.parametrize("name", SECRET_SETTINGS)
def test_setting_is_declared_as_a_secret(name):
    assert Settings.model_fields[name].annotation is SecretStr, (
        f"{name} holds credential material and must be typed SecretStr"
    )


def test_repr_of_settings_carries_no_secret_value(loaded):
    text = repr(loaded)
    leaked = sorted(name for name, value in SENTINELS.items() if value in text)
    assert not leaked, f"repr(settings) leaked: {leaked}"


def test_str_of_settings_carries_no_secret_value(loaded):
    text = str(loaded)
    leaked = sorted(name for name, value in SENTINELS.items() if value in text)
    assert not leaked, f"str(settings) leaked: {leaked}"


def test_model_dump_carries_no_secret_value(loaded):
    text = repr(loaded.model_dump())
    leaked = sorted(name for name, value in SENTINELS.items() if value in text)
    assert not leaked, f"model_dump() leaked: {leaked}"


def test_validation_error_message_carries_no_secret_value(tmp_path):
    """A bad value in one field must not print the other fields' values in the error."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{name}={value}" for name, value in SENTINELS.items())
        + "\nDB_MAX_POOL_SIZE=not-an-integer\n",
        encoding="utf-8",
    )

    with pytest.raises(Exception) as caught:
        Settings(_env_file=str(env_file))

    text = str(caught.value)
    leaked = sorted(name for name, value in SENTINELS.items() if value in text)
    assert not leaked, f"validation error leaked: {leaked}"


@pytest.mark.parametrize("name", SECRET_SETTINGS)
def test_the_value_is_still_reachable_at_the_point_of_use(name, loaded):
    # Masking is worthless if it also hides the value from the code that needs it.
    assert reveal_secret(getattr(loaded, name)) == SENTINELS[name]


def test_reveal_secret_passes_plain_strings_through():
    # Tests monkeypatch these settings with plain strings; that has to keep working.
    assert reveal_secret("plain") == "plain"
    assert reveal_secret("") == ""
    assert reveal_secret(None) == ""


def test_no_source_file_reads_a_secret_setting_without_unwrapping_it():
    """Guard the consumer chain: a new raw read would silently compare against a SecretStr."""
    from pathlib import Path

    source_root = Path(__file__).resolve().parents[2] / "src"
    pattern = re.compile(
        r"(?<!reveal_secret\()settings\.(" + "|".join(SECRET_SETTINGS) + r")\b"
    )
    offenders = []
    for path in source_root.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(source_root)}:{number}")
    assert not offenders, (
        "read these through reveal_secret(): " + ", ".join(offenders)
    )
