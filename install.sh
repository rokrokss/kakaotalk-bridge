#!/usr/bin/env bash
# Download once, reuse on every launch. No Git, Python or Docker knowledge needed.
set -euo pipefail
umask 077

case "$(uname -s)" in
  Darwin) bridge_default_home="$HOME/Library/Application Support/KakaoTalk Bridge" ;;
  Linux) bridge_default_home="${XDG_DATA_HOME:-$HOME/.local/share}/kakaotalk-bridge" ;;
  *) echo 'Windows에서는 install.ps1을 사용하세요. 이 설치 프로그램은 macOS/Linux용입니다.' >&2; exit 1 ;;
esac
bridge_install_home="${BRIDGE_HOME:-$bridge_default_home}"
bridge_version="${BRIDGE_VERSION:-main}"
if [[ ! "$bridge_version" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo 'BRIDGE_VERSION에 릴리스 태그 또는 커밋 ID를 지정하세요.' >&2; exit 1
fi
if ! command -v curl >/dev/null; then
  echo '설치 프로그램 다운로드에 curl이 필요합니다. curl을 설치하고 다시 실행하세요.' >&2
  exit 1
fi

bridge_verbose=0
bridge_bootstrap_log=''
for bridge_argument in "$@"; do
  if [[ "$bridge_argument" == '--verbose' ]]; then bridge_verbose=1; fi
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

# Redirect only when replacing this shell. Changing fd 0 while bash is still
# reading a curl pipe can discard the rest of the installer itself.
bridge_launch() {
  if [[ ! -t 0 && -r /dev/tty ]] && ( : </dev/tty ) 2>/dev/null; then
    exec "$bridge_python" "$1/bridge" up "${@:2}" </dev/tty
  else
    exec "$bridge_python" "$1/bridge" up "${@:2}"
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
  bridge_run "$bridge_python" - "$bridge_install_home" "$bridge_version" <<'PY'
import os, pathlib, shutil, sys, tarfile, tempfile, urllib.request
target, version = pathlib.Path(sys.argv[1]).expanduser().absolute(), sys.argv[2]
if target.exists():
    raise SystemExit('Installation folder already exists but is incomplete. Choose another BRIDGE_HOME; existing files were preserved.')
target.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='.bridge-download-', dir=target.parent) as temporary:
    scratch = pathlib.Path(temporary)
    archive = scratch / 'source.tar.gz'
    with urllib.request.urlopen('https://codeload.github.com/rokrokss/kakaotalk-bridge/tar.gz/' + version, timeout=120) as response, archive.open('wb') as output:
        shutil.copyfileobj(response, output)
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        for item in members:
            path = pathlib.PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts or not (item.isfile() or item.isdir()):
                raise SystemExit('Unexpected source archive; installation cancelled.')
        bundle.extractall(scratch / 'source', filter='data')
    roots = list((scratch / 'source').iterdir())
    if len(roots) != 1 or not (roots[0] / 'ops/onboarding.py').is_file():
        raise SystemExit('This source version does not include the one-command installer.')
    roots[0].rename(target)
PY
  echo 'KakaoTalk Bridge 다운로드 완료'
fi
echo "Bridge 설치 위치: $bridge_install_home"
bridge_launch "$bridge_install_home" "$@"
