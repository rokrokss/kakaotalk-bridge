import pytest

from device import cli


def test_bridge_uid_uses_exact_owner_user_package(monkeypatch):
    def adb(*args):
        assert args == ("shell", "pm", "list", "packages", "--user", "0", "-U", cli.PKG)
        return "package:dev.kakaocollector.bridge.extra uid:10001\npackage:dev.kakaocollector.bridge uid:10088"

    monkeypatch.setattr(cli, "adb", adb)
    assert cli.bridge_uid() == "10088"


@pytest.mark.parametrize(
    "listing",
    [
        "",
        "package:dev.kakaocollector.bridge.extra uid:10088",
        "package:dev.kakaocollector.bridge uid:0",
        "package:dev.kakaocollector.bridge uid:110088",
        "package:dev.kakaocollector.bridge uid:10088\npackage:dev.kakaocollector.bridge uid:10089",
    ],
)
def test_bridge_uid_rejects_missing_ambiguous_or_wrong_user(monkeypatch, listing):
    monkeypatch.setattr(cli, "adb", lambda *args: listing)
    with pytest.raises(RuntimeError, match="keyboard_app_unavailable"):
        cli.bridge_uid()
