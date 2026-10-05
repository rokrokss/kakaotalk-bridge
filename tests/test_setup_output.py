import stat
import sys
from unittest.mock import Mock

import pytest

from ops import cli, setup_output


def test_quiet_commands_log_both_streams_without_logging_captured_links(
    tmp_path, monkeypatch, capfd
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with setup_output.SetupOutput() as output, output.step("[1/1] Preparing the environment"):
        setup_output.run(
            [sys.executable, "-c", "import sys; print('build output'); print('warning', file=sys.stderr)"]
        )
        assert setup_output.run(
            [sys.executable, "-c", "print('https://bridge.test/#passkey-setup=secret')"],
            capture=True,
        ) == "https://bridge.test/#passkey-setup=secret"
        setup_output.run(
            [sys.executable, "-c", "print('Approve in your browser')"], interactive=True
        )
    screen = capfd.readouterr()
    log = output.path.read_text()
    assert "build output" in log and "warning" in log
    assert "build output" not in screen.out and "warning" not in screen.err
    assert "Approve in your browser" in screen.out
    assert "Approve in your browser" not in log
    assert "passkey-setup" not in log
    assert "— done." in screen.out
    assert stat.S_IMODE(output.path.stat().st_mode) == 0o600
    # Output routing is scoped to setup, even after the log has been closed.
    setup_output.run([sys.executable, "-c", "print('normal command output')"])
    assert "normal command output" in capfd.readouterr().out


def test_failure_keeps_diagnostics_and_does_not_report_completion(tmp_path, monkeypatch, capfd):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with (
        pytest.raises(RuntimeError, match="exit 7"),
        setup_output.SetupOutput() as output,
        output.step("[1/1] Building services"),
    ):
        setup_output.run(
            [sys.executable, "-c", "import sys; print('build failed', file=sys.stderr); sys.exit(7)"]
        )
    screen = capfd.readouterr()
    assert "done" not in screen.out
    assert "build failed" not in screen.err
    assert "build failed" in output.path.read_text()
    setup_output.run([sys.executable, "-c", "print('normal after failure')"])
    assert "normal after failure" in capfd.readouterr().out


def test_verbose_streams_details_without_creating_a_log(tmp_path, monkeypatch, capfd):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with setup_output.SetupOutput(verbose=True):
        setup_output.run(
            [sys.executable, "-c", "import sys; print('detail'); print('warning', file=sys.stderr)"]
        )
    screen = capfd.readouterr()
    assert "detail" in screen.out and "warning" in screen.err
    assert not list(tmp_path.iterdir())


def test_heartbeat_reports_elapsed_time_until_stopped(monkeypatch, capsys):
    stopped = Mock()
    stopped.wait.side_effect = [False, True]
    monkeypatch.setattr(setup_output.time, "monotonic", lambda: 175)
    setup_output.SetupOutput()._heartbeat(stopped, "Starting services", 100)
    assert capsys.readouterr().out == "Starting services… still working (1m 15s elapsed).\n"
    assert all(call.args == (30,) for call in stopped.wait.call_args_list)
