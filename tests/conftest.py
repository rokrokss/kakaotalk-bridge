import pytest

from ops import launcher


@pytest.fixture(autouse=True)
def private_launcher(tmp_path_factory, monkeypatch):
    """Tests never write the person's kakaotalk-bridge command or shell profile."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(launcher, "SYSTEM_BIN", home / "system-bin")
    return home
