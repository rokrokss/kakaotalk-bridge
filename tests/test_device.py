from unittest.mock import patch

from device import cli


def test_probe_does_not_open_apps_or_read_chats():
    calls = []

    def fake_adb(*args, **kwargs):
        calls.append(args)
        if args == ("get-state",):
            return "device"
        if args[-1] == "sys.boot_completed":
            return "1"
        if args[:3] == ("shell", "pm", "path"):
            return "package:/installed.apk"
        return "14"

    with patch.object(cli, "connect"), patch.object(cli, "adb", side_effect=fake_adb):
        state = cli.sample()
    assert state["state"] == "android_ready"
    assert all("am" not in c and "input" not in c and "uiautomator" not in c for c in calls)


def test_disconnected_device_report_is_not_healthy():
    with patch.object(cli, "connect"), patch.object(cli, "adb", side_effect=RuntimeError):
        assert cli.sample()["state"] == "offline"
