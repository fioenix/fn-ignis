"""ensure_environment_file must not touch a configured key, nor claim it did."""

import re

from cryptography.fernet import Fernet

from ignis.config import Settings
from ignis.interfaces.cli.setup_bundle import ensure_environment_file


def read_key(project_root):
    text = (project_root / ".env").read_text(encoding="utf-8")
    match = re.search(r"^IGNIS_ENCRYPTION_KEY=(.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def test_created_file_has_no_recurring_collection_settings(tmp_path):
    ensure_environment_file(tmp_path)

    text = (tmp_path / ".env").read_text(encoding="utf-8")
    for setting in ("SCHEDULER_INTERVAL_SECONDS", "SYNC_INTERVAL_MINUTES", "DISCOVERY_INTERVAL_HOURS"):
        assert setting not in text


def test_created_file_carries_the_shared_youtube_quota_defaults(tmp_path):
    ensure_environment_file(tmp_path)

    text = (tmp_path / ".env").read_text(encoding="utf-8")
    for setting in (
        "YOUTUBE_SEARCH_DAILY_LIMIT",
        "YOUTUBE_SCHEDULED_SEARCH_DAILY_LIMIT",
        "YOUTUBE_OTHER_DAILY_UNIT_LIMIT",
    ):
        expected = Settings.model_fields[setting].default
        assert f"{setting}={expected}" in text


def test_created_file_carries_a_usable_fernet_key(tmp_path):
    ensure_environment_file(tmp_path)

    Fernet(read_key(tmp_path).encode())  # raises if the key is not a valid Fernet key


def test_configured_key_is_reported_as_untouched(tmp_path):
    key = Fernet.generate_key().decode()
    # A trailing newline is what almost every editor leaves behind. The old implementation
    # compared the rejoined lines -- which drop it -- against the original text, saw a
    # difference, and reported that it had generated a key on a run that generated nothing.
    (tmp_path / ".env").write_text(f"DEFAULT_GEO=VN\nIGNIS_ENCRYPTION_KEY={key}\n", encoding="utf-8")

    changed, message = ensure_environment_file(tmp_path)

    assert read_key(tmp_path) == key
    assert changed is False
    assert "generated" not in message.lower()


def test_configured_key_is_left_alone_without_a_trailing_newline(tmp_path):
    key = Fernet.generate_key().decode()
    (tmp_path / ".env").write_text(f"DEFAULT_GEO=VN\nIGNIS_ENCRYPTION_KEY={key}", encoding="utf-8")

    changed, message = ensure_environment_file(tmp_path)

    assert read_key(tmp_path) == key
    assert changed is False
    assert "generated" not in message.lower()


def test_configured_key_survives_repeated_runs(tmp_path):
    key = Fernet.generate_key().decode()
    (tmp_path / ".env").write_text(f"IGNIS_ENCRYPTION_KEY={key}\n", encoding="utf-8")

    for _ in range(3):
        ensure_environment_file(tmp_path)

    assert read_key(tmp_path) == key


def test_empty_key_is_filled_in_and_reported(tmp_path):
    (tmp_path / ".env").write_text("DEFAULT_GEO=VN\nIGNIS_ENCRYPTION_KEY=\n", encoding="utf-8")

    changed, message = ensure_environment_file(tmp_path)

    assert changed is True
    assert "empty" in message.lower()
    Fernet(read_key(tmp_path).encode())
    assert "DEFAULT_GEO=VN" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_missing_key_is_appended_without_dropping_other_settings(tmp_path):
    (tmp_path / ".env").write_text("DEFAULT_GEO=VN\nYOUTUBE_API_KEY=abc\n", encoding="utf-8")

    changed, _ = ensure_environment_file(tmp_path)

    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert changed is True
    assert "DEFAULT_GEO=VN" in text and "YOUTUBE_API_KEY=abc" in text
    Fernet(read_key(tmp_path).encode())
