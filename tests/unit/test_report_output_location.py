"""Runtime outputs belong to a checkout or user directory, never installed libraries."""
import pytest

from ignis.interfaces.mcp import server


@pytest.mark.parametrize("layout", ["venv/lib/python3.13/site-packages", "lib/python3.13/site-packages"])
def test_installed_server_exports_to_isolated_user_directory(tmp_path, monkeypatch, layout):
    module = tmp_path / layout / "ignis/interfaces/mcp/server.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    home = tmp_path / "user-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(server, "__file__", str(module))

    output = server._get_secure_reports_dir()

    assert output == home / ".ignis/reports"
    assert output.is_dir()
    assert not (module.parents[4] / "reports").exists()


def test_source_checkout_keeps_existing_reports_location(tmp_path, monkeypatch):
    module = tmp_path / "checkout/src/ignis/interfaces/mcp/server.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "user-home"))
    monkeypatch.setattr(server, "__file__", str(module))

    output = server._get_secure_reports_dir()

    assert output == tmp_path / "checkout/reports"
    assert output.is_dir()
    assert not (output / ".write_test").exists()
