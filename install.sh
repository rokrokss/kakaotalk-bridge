#!/usr/bin/env bash
# Install or upgrade KakaoTalk Bridge, then open setup. Git checkouts keep their own code.
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

# Run a child with the terminal for sudo/interactive prompts when available, and never
# let it consume the rest of a curl-piped installer. Linux installs are managed as root,
# so elevate once for the whole run.
bridge_attached() {
  local bridge_elevate=''
  if [[ "$(uname -s)" == Linux && "$(id -u)" != 0 ]]; then bridge_elevate=sudo; fi
  if [[ ! -t 0 && -r /dev/tty ]] && ( : </dev/tty ) 2>/dev/null; then
    $bridge_elevate "$@" </dev/tty
  elif [[ -t 0 ]]; then
    $bridge_elevate "$@"
  else
    $bridge_elevate "$@" </dev/null
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

bridge_home="$bridge_install_home"
bridge_helper=''
if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
  bridge_checkout="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$bridge_checkout/ops/releases.py" ]]; then
    # A local installer uses its own helper and, without BRIDGE_HOME, manages its folder.
    bridge_helper="$bridge_checkout/ops/releases.py"
    if [[ -z "${BRIDGE_HOME:-}" ]]; then bridge_home="$bridge_checkout"; fi
  fi
fi

if [[ -z "$bridge_helper" ]]; then
  bridge_helper_dir="$(mktemp -d)"
  # Cleanup never changes the installer's result.
  trap 'rm -rf "$bridge_helper_dir" || true' EXIT
  # The helper, like this script, is trusted from the official HTTPS repository. It
  # verifies release bundles against GitHub's asset SHA-256, and it upgrades existing
  # installations with the new version's code before any installed code runs.
  bridge_run curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/ops/releases.py \
    -o "$bridge_helper_dir/releases.py"
  bridge_helper="$bridge_helper_dir/releases.py"
fi

if [[ ! -f "$bridge_home/bridge" ]]; then
  echo 'KakaoTalk Bridge 다운로드 및 설치 중…'
  if [[ "$bridge_source" == 1 ]]; then
    bridge_run "$bridge_python" "$bridge_helper" download "$bridge_home" "$bridge_version" --source
  else
    bridge_run "$bridge_python" "$bridge_helper" download "$bridge_home" "$bridge_version"
  fi
  echo 'KakaoTalk Bridge 다운로드 완료'
fi
echo "Bridge 설치 위치: $bridge_home"
bridge_attached "$bridge_python" "$bridge_helper" launch "$bridge_home" "$bridge_version" -- "$@"
