import stat
import sys
from unittest.mock import Mock

import pytest

from ops import cli, setup_output


def test_quiet_commands_log_both_streams_without_logging_captured_links(
    tmp_path, monkeypatch, capfd
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with setup_output.SetupOutput() as output, output.step("[1/1] 실행 환경 준비"):
        setup_output.run(
            [
                sys.executable,
                "-c",
                "import sys; print('build output'); print('warning', file=sys.stderr)",
            ]
        )
        assert (
            setup_output.run(
                [sys.executable, "-c", "print('https://bridge.test/#passkey-setup=secret')"],
                capture=True,
            )
            == "https://bridge.test/#passkey-setup=secret"
        )
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
    assert "완료" in screen.out
    assert stat.S_IMODE(output.path.stat().st_mode) == 0o600
    # Output routing is scoped to setup, even after the log has been closed.
    setup_output.run([sys.executable, "-c", "print('normal command output')"])
    assert "normal command output" in capfd.readouterr().out


def test_failure_keeps_diagnostics_and_does_not_report_completion(tmp_path, monkeypatch, capfd):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with (
        pytest.raises(RuntimeError, match="exit 7"),
        setup_output.SetupOutput() as output,
        output.step("[1/1] 서비스 빌드"),
    ):
        setup_output.run(
            [
                sys.executable,
                "-c",
                "import sys; print('build failed', file=sys.stderr); sys.exit(7)",
            ]
        )
    screen = capfd.readouterr()
    assert "완료" not in screen.out
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
    setup_output.SetupOutput()._heartbeat(stopped, "서비스 시작", 100)
    assert capsys.readouterr().out == "서비스 시작 중… 1분 15초 경과\n"
    assert all(call.args == (30,) for call in stopped.wait.call_args_list)


def test_cli_commands_use_korean_progress_without_corrupting_captured_output(
    tmp_path, monkeypatch, capfd
):
    from argparse import Namespace

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with setup_output.operation(Namespace(command="setup-connection", local=False)):
        cli.run(
            [
                sys.executable,
                "-c",
                "import sys; print('build detail'); print('warning', file=sys.stderr)",
            ]
        )
        result = cli.run([sys.executable, "-c", "print('{\"ready\":true}')"], capture=True)
    screen = capfd.readouterr()
    assert "AI 연결 설정 중…" in screen.out and "AI 연결 설정 완료" in screen.out
    assert "build detail" not in screen.out and "warning" not in screen.err
    assert result == '{"ready":true}'
    log = next((tmp_path / ".bridge/logs").iterdir()).read_text()
    assert "build detail" in log and "warning" in log


def test_provider_guidance_keeps_links_live_and_out_of_logs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with setup_output.SetupOutput() as output:
        setup_output.provider_line("Provider diagnostics in English\n")
        setup_output.provider_line(
            "To authenticate, visit https://login.tailscale.com/a/synthetic\n"
        )
    screen = capsys.readouterr().out
    assert "Tailscale 로그인·승인 페이지를 여세요:" in screen
    assert "https://login.tailscale.com/a/synthetic" in screen
    assert "To authenticate" not in screen and "Provider diagnostics" not in screen
    log = output.path.read_text()
    assert "Provider diagnostics in English" in log and "login.tailscale.com" not in log


def test_error_guidance_is_korean_and_does_not_pollute_stdout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    setup_output.report_error(RuntimeError("Internal failure in English"))
    screen = capsys.readouterr()
    assert not screen.out
    assert "작업을 완료하지 못했습니다" in screen.err
    assert "Internal failure" not in screen.err
    log = next((tmp_path / ".bridge/logs").iterdir())
    assert "Internal failure in English" in log.read_text()
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "command,options",
    [
        ("mcp", {}),
        ("tunnel", {"tunnel_command": "status"}),
        ("passkey-login", {"link_only": True}),
        ("setup-agent", {"agent_command": "job"}),
    ],
)
def test_protocol_commands_are_not_wrapped(tmp_path, monkeypatch, capsys, command, options):
    from argparse import Namespace

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with setup_output.operation(Namespace(command=command, local=False, **options)):
        print('{"protocol":"unchanged"}')
    assert capsys.readouterr().out == '{"protocol":"unchanged"}\n'
    assert not list(tmp_path.iterdir())


def test_provider_command_preserves_approval_and_reports_failure(tmp_path, monkeypatch, capfd):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with (
        pytest.raises(RuntimeError, match="exit 7"),
        setup_output.SetupOutput() as output,
    ):
        setup_output.provider_command(
            [
                sys.executable,
                "-c",
                (
                    "import sys; print('Provider detail'); "
                    "print('Visit https://login.tailscale.com/a/synthetic'); sys.exit(7)"
                ),
            ]
        )
    screen = capfd.readouterr()
    assert "Tailscale 연결 설정 중…" in screen.out
    assert "https://login.tailscale.com/a/synthetic" in screen.out
    assert "Provider detail" not in screen.out and not screen.err
    log = output.path.read_text()
    assert "Provider detail" in log and "exit 7" in log
    assert "login.tailscale.com" not in log


def test_argument_guidance_keeps_internal_parse_errors_in_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    parser = cli.KoreanArgumentParser(prog="bridge")
    parser.add_argument("--count", type=int)
    help_text = parser.format_help()
    assert "사용법:" in help_text and "옵션:" in help_text
    assert "사용법을 표시하고 종료" in help_text
    with pytest.raises(SystemExit) as stopped:
        parser.parse_args(["--count", "invalid"])
    assert stopped.value.code == 2
    screen = capsys.readouterr()
    assert not screen.out and "--help로 확인" in screen.err
    assert "invalid int value" not in screen.err
    assert "invalid int value" in next((tmp_path / ".bridge/logs").iterdir()).read_text()


def child_script(*lines, code=0):
    body = "; ".join(f"print({line!r}, flush=True)" for line in lines)
    return [sys.executable, "-c", f"import sys; {body}; sys.exit({code})"]


def test_child_progress_is_shown_and_tool_output_stays_in_one_log(tmp_path, monkeypatch, capfd):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    mark = setup_output.MARK
    with setup_output.SetupOutput() as output, output.step("[2/4] 개인 Bridge 시작"):
        cli.run(
            child_script(
                "docker pull detail",
                mark + '{"progress": "이미지 내려받는 중…"}',
                "Pulling layer 3/9",
                mark + '{"notice": "백업 위치: backups/a.kcs"}',
            )
        )
    screen = capfd.readouterr().out
    assert "  · 이미지 내려받는 중…" in screen and "백업 위치: backups/a.kcs" in screen
    assert "docker pull detail" not in screen and "Pulling layer" not in screen
    log = output.path.read_text()
    assert "docker pull detail" in log and "Pulling layer 3/9" in log
    assert mark not in log


def test_innermost_child_error_reaches_the_screen_in_korean(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    mark = setup_output.MARK
    nested = child_script(
        "Traceback (most recent call last): internal detail",
        mark + '{"error": "8443 포트가 이미 사용 중입니다. 다른 포트를 지정하세요."}',
        mark + '{"error": "' + setup_output.GENERIC + '"}',
        code=1,
    )
    with (
        pytest.raises(setup_output.BridgeError, match="8443 포트가 이미 사용 중") as raised,
        setup_output.SetupOutput() as output,
        output.step("서비스 시작"),
    ):
        cli.run(nested)
    setup_output.report_error(raised.value)
    assert "internal detail" in output.path.read_text()


def test_child_mode_reports_through_marked_lines(monkeypatch, capsys):
    monkeypatch.setenv(setup_output.CHILD, "1")
    setup_output.progress("가상 머신 시작 중…")
    setup_output.report_error(setup_output.BridgeError("Lima를 먼저 설치하세요."))
    setup_output.report_error(KeyError("private detail"))
    screen = capsys.readouterr()
    lines = screen.out.splitlines()
    assert lines[0] == setup_output.MARK + '{"progress": "가상 머신 시작 중…"}'
    assert lines[1] == setup_output.MARK + '{"error": "Lima를 먼저 설치하세요."}'
    assert lines[2] == setup_output.MARK + '{"error": "' + setup_output.GENERIC + '"}'
    assert "KeyError" in screen.err and "private detail" in screen.err


def test_children_inherit_progress_or_raw_output_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.delenv(setup_output.CHILD, raising=False)
    monkeypatch.delenv(setup_output.RAW, raising=False)
    assert setup_output.bridge_command("start")[-1:] == ["start"]
    assert "--progress" not in setup_output.bridge_command("start")
    with setup_output.SetupOutput():
        assert setup_output.bridge_command("start")[-2:] == ["--progress", "start"]
    with setup_output.SetupOutput(verbose=True):
        assert setup_output.bridge_command("start")[-2:] == ["--raw-output", "start"]


def test_unexpected_errors_never_print_a_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["bridge", "doctor"])
    monkeypatch.setattr(cli, "execute", Mock(side_effect=KeyError("missing setting")))
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 1
    screen = capsys.readouterr()
    assert "Traceback" not in screen.err and "missing setting" not in screen.err
    assert setup_output.GENERIC in screen.err
    log = next((tmp_path / ".bridge/logs").iterdir()).read_text()
    assert "KeyError" in log and "Traceback" in log
