#!/usr/bin/env bash
# Install or upgrade a release, then open setup. Source checkouts keep their own code.
set -euo pipefail
umask 077

case "$(uname -s)" in
  Darwin) bridge_default_home="$HOME/Library/Application Support/KakaoTalk Bridge" ;;
  Linux) bridge_default_home="${XDG_DATA_HOME:-$HOME/.local/share}/kakaotalk-bridge" ;;
  *) echo 'Windows에서는 install.ps1을 사용하세요. 이 설치 프로그램은 macOS/Linux용입니다.' >&2; exit 1 ;;
esac
bridge_install_home="${BRIDGE_HOME:-$bridge_default_home}"
bridge_version="${BRIDGE_VERSION:-latest}"
if [[ ! "$bridge_version" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo 'BRIDGE_VERSION에 릴리스 태그 또는 커밋 ID를 지정하세요.' >&2; exit 1
fi
if ! command -v curl >/dev/null; then
  echo '설치 프로그램 다운로드에 curl이 필요합니다. curl을 설치하고 다시 실행하세요.' >&2
  exit 1
fi

bridge_source=0
bridge_verbose=0
bridge_bootstrap_log=''
for bridge_argument in "$@"; do
  if [[ "$bridge_argument" == '--verbose' ]]; then bridge_verbose=1; fi
  if [[ "$bridge_argument" == '--source' ]]; then bridge_source=1; fi
done

# Keep dependency/download chatter out of the progress display. Logs are private
# and retained on failure; the Python setup creates its own log after launch.
bridge_run() {
  if [[ "$bridge_verbose" == 1 ]]; then
    "$@"
  else
    if [[ -z "$bridge_bootstrap_log" ]]; then
      bridge_bootstrap_log="$(mktemp "${TMPDIR:-/tmp}/kakaotalk-bridge-setup.XXXXXX")"
      echo "설치 진단 로그: $bridge_bootstrap_log"
    fi
    if "$@" >>"$bridge_bootstrap_log" 2>&1; then
      return 0
    else
      bridge_status=$?
      echo "설치 준비에 실패했습니다. 진단 로그: $bridge_bootstrap_log" >&2
      return "$bridge_status"
    fi
  fi
}

# This launcher lives in the downloaded installer so already-published releases
# can upgrade too. Exec the new CLI after upgrade instead of reusing old imports.
bridge_launch() {
  local bridge_entry='
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
version, arguments = sys.argv[2], sys.argv[3:]
command = [sys.executable, str(root / "bridge")]
marker = ".bridge/mac.json" if sys.platform == "darwin" else ".bridge/installed"
installed = (root / marker).is_file()
progress = root / ".bridge/onboarding.json"
if progress.is_file():
    try:
        record = json.loads(progress.read_text())
        installed = installed and isinstance(record, dict) and record.get("state") == "ready"
    except (ValueError, OSError):
        installed = False
elif sys.platform == "darwin":
    # mac.json is written before the VM finishes its first installation.
    installed = False

if (root / marker).is_file() and (root / "release.json").is_file() and not (root / ".git").exists():
    sys.path.insert(0, str(root))
    from ops.cli import KoreanArgumentParser
    from ops.onboarding import add_arguments

    parser = KoreanArgumentParser(prog="bridge up")
    add_arguments(parser)
    options = parser.parse_args(arguments)
    if (installed or sys.platform == "darwin") and not (
        options.plan or options.source or options.manifest
    ):
        try:
            # Validate all setup options before changing the installed version.
            subprocess.run([*command, "up", "--plan", *arguments],
                           stdout=subprocess.DEVNULL, check=True)
            if sys.platform == "darwin":
                from ops.onboarding import prepare_mac
                from ops.setup_output import SetupOutput

                # Dependency installers write to the private log, not the terminal.
                with SetupOutput():
                    prepare_mac(options)
                config = json.loads((root / marker).read_text())
                instances = subprocess.run(
                    ["limactl", "list", "--format", "{{.Name}}"],
                    capture_output=True, text=True, check=True,
                ).stdout.splitlines()
                if config["vm"] not in instances:
                    # Published versions of up can create a default Lima VM when
                    # mac.json outlives the guest. Their install command already
                    # uses our template and saved ports, so repair before up.
                    print("기존 VM이 없어 Bridge 템플릿으로 다시 준비합니다.", flush=True)
                    subprocess.run(
                        [*command, "install", "--manifest", str(root / "release.json")],
                        check=True,
                    )
                    installed = False
            if installed:
                print("릴리스 업데이트 확인 중…", flush=True)
                subprocess.run([*command, "upgrade", "--version", version], check=True)
        except subprocess.CalledProcessError as error:
            sys.exit(error.returncode)
        except Exception as error:
            from ops.setup_output import report_error

            report_error(error)
            sys.exit(1)

os.execv(sys.executable, [*command, "up", *arguments])
'
  # Never let a child consume the rest of a curl-piped installer. Use the terminal
  # for sudo/interactive prompts when available, otherwise provide EOF.
  # Linux installs are managed as root, so elevate once for the whole run.
  local bridge_elevate=''
  if [[ "$(uname -s)" == Linux && "$(id -u)" != 0 ]]; then bridge_elevate=sudo; fi
  if [[ ! -t 0 && -r /dev/tty ]] && ( : </dev/tty ) 2>/dev/null; then
    exec $bridge_elevate "$bridge_python" -c "$bridge_entry" "$1" "$bridge_version" "${@:2}" </dev/tty
  elif [[ -t 0 ]]; then
    exec $bridge_elevate "$bridge_python" -c "$bridge_entry" "$1" "$bridge_version" "${@:2}"
  else
    exec $bridge_elevate "$bridge_python" -c "$bridge_entry" "$1" "$bridge_version" "${@:2}" </dev/null
  fi
}

bridge_python=''
for bridge_candidate in python3.14 python3.13 python3.12 python3; do
  if command -v "$bridge_candidate" >/dev/null && "$bridge_candidate" -c 'import sys; sys.exit(not ((3,12) <= sys.version_info < (3,15)))' 2>/dev/null; then
    bridge_python="$(command -v "$bridge_candidate")"; break
  fi
done
if [[ -z "$bridge_python" ]]; then
  echo '설치 실행 환경 준비 중…'
  bridge_uv="$(command -v uv || true)"
  if [[ -z "$bridge_uv" && -x "$HOME/.local/bin/uv" ]]; then bridge_uv="$HOME/.local/bin/uv"; fi
  if [[ -z "$bridge_uv" ]]; then
    bridge_tmp="$(mktemp -d)"
    trap 'rm -rf "$bridge_tmp"' EXIT
    bridge_run curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://astral.sh/uv/install.sh -o "$bridge_tmp/uv-install.sh"
    UV_NO_MODIFY_PATH=1 bridge_run sh "$bridge_tmp/uv-install.sh"
    bridge_uv="$HOME/.local/bin/uv"
    rm -rf "$bridge_tmp"
    trap - EXIT
  fi
  bridge_run "$bridge_uv" python install 3.12
  bridge_python="$("$bridge_uv" python find --managed-python 3.12)"
  echo '설치 실행 환경 준비 완료'
fi

if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
  bridge_checkout="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$bridge_checkout/ops/onboarding.py" && -z "${BRIDGE_HOME:-}" ]]; then
    bridge_launch "$bridge_checkout" "$@"
  fi
fi

if [[ ! -f "$bridge_install_home/bridge" ]]; then
  echo 'KakaoTalk Bridge 다운로드 및 설치 중…'
  bridge_tmp="$(mktemp -d)"
  trap 'rm -rf "$bridge_tmp"' EXIT
  # The bootstrap helper, like this script, is trusted from the official HTTPS
  # repository. It verifies the release bundle against GitHub's asset SHA-256.
  bridge_run curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/ops/releases.py \
    -o "$bridge_tmp/releases.py"
  if [[ "$bridge_source" == 1 ]]; then
    bridge_run "$bridge_python" "$bridge_tmp/releases.py" "$bridge_install_home" "$bridge_version" --source
  else
    bridge_run "$bridge_python" "$bridge_tmp/releases.py" "$bridge_install_home" "$bridge_version"
  fi
  rm -rf "$bridge_tmp"
  trap - EXIT
  echo 'KakaoTalk Bridge 다운로드 완료'
fi
echo "Bridge 설치 위치: $bridge_install_home"
bridge_launch "$bridge_install_home" "$@"
