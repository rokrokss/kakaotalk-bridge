"""The kakaotalk-bridge launcher on PATH. It runs one installation's bridge entry point."""

import os
import shlex
import sys
import tempfile
from pathlib import Path

from ops import cli

NAME = "kakaotalk-bridge"
HEADER = "# KakaoTalk Bridge command. Written by kakaotalk-bridge up for the installation below."
PROFILE_LINE = 'export PATH="$HOME/.local/bin:$PATH"'
# Linux installs are managed as root, and the command serves every account.
SYSTEM_BIN = Path("/usr/local/bin")


def path():
    # Mac setup runs as the person; ~/.local/bin is where uv and pipx put user commands.
    if sys.platform == "darwin":
        return Path.home() / ".local/bin" / NAME
    return SYSTEM_BIN / NAME


def home_line():
    return "home=" + shlex.quote(str(cli.ROOT))


def script():
    # The setup Python is tried first; a later Python works too if it was removed.
    return f"""#!/bin/sh
{HEADER}
{home_line()}
python={shlex.quote(sys.executable)}
if [ ! -x "$python" ]; then
  python=
  for candidate in python3.14 python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(not ((3, 12) <= sys.version_info < (3, 15)))' 2>/dev/null; then
      python=$candidate
      break
    fi
  done
fi
if [ -z "$python" ]; then
  echo 'KakaoTalk Bridge에 필요한 Python 3.12 이상을 찾지 못했습니다. 설치 명령을 다시 실행하세요.' >&2
  exit 1
fi
exec "$python" "$home/bridge" "$@"
"""


def serves_this():
    try:
        return home_line() in path().read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return False


def install():
    """Point kakaotalk-bridge at this installation unless it already serves another one."""
    try:
        _install()
    except OSError as error:
        # A convenience; setup continues and ./bridge in the installation still works.
        cli.notice(f"{NAME} 명령을 만들지 못했습니다({error}). {cli.ROOT / 'bridge'}로 실행하세요.")


def _install():
    target = path()
    try:
        existing = target.read_text()
    except (FileNotFoundError, NotADirectoryError):
        existing = None
    except (OSError, UnicodeDecodeError):
        existing = ""
    if existing is not None and home_line() not in existing.splitlines():
        cli.notice(
            f"{target}이(가) 다른 설치를 가리키고 있어 그대로 두었습니다. "
            f"이 설치는 {cli.ROOT / 'bridge'}로 실행하세요."
        )
        return
    wanted = script()
    if existing != wanted:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix="." + NAME + "-")
        with os.fdopen(descriptor, "w") as stream:
            stream.write(wanted)
        os.chmod(temporary, 0o755)
        os.replace(temporary, target)
    if sys.platform == "darwin":
        add_to_path(target.parent)


def add_to_path(folder):
    if str(folder) in os.environ.get("PATH", "").split(os.pathsep):
        return
    profile = {"zsh": ".zprofile", "bash": ".bash_profile"}.get(
        Path(os.environ.get("SHELL", "")).name
    )
    if not profile:
        cli.notice(f"{folder}을(를) PATH에 추가하면 어디서든 {NAME} 명령을 쓸 수 있습니다.")
        return
    profile = Path.home() / profile
    text = profile.read_text() if profile.is_file() else ""
    if PROFILE_LINE not in text.splitlines():
        with profile.open("a") as stream:
            if text and not text.endswith("\n"):
                stream.write("\n")
            stream.write(f"# KakaoTalk Bridge\n{PROFILE_LINE}\n")
        cli.notice(f"{profile}에 {folder}을(를) PATH로 추가했습니다.")
    cli.notice(f"새 터미널부터 {NAME} 명령을 쓸 수 있습니다. 지금 터미널에서는 {folder / NAME}을(를) 실행하세요.")


def client_command():
    """What AI apps run for stdio MCP. They lack the shell PATH, so the path is absolute."""
    if serves_this():
        return [str(path())]
    return [sys.executable, str(cli.ROOT / "bridge")]


def remove():
    if serves_this():
        path().unlink()
