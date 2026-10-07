# 설치와 실행

[README](../README.md) · [관리 화면](web-ui.md) · [운영과 복구](operations.md)

<a id="download-and-start"></a>
## 1. 설치

Apple Silicon Mac 또는 Linux의 터미널에서 실행하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

- 끝나면 브라우저에 관리 화면이 열립니다.
- 필요한 도구를 함께 설치합니다(Mac: Homebrew·Lima, Linux: Docker). 관리자 암호를 물을 수 있습니다.
- 검증된 릴리스 설치 파일과 미리 빌드한 이미지를 받으며, 이 컴퓨터에서 빌드하지 않습니다.
- 실패하면 표시된 안내대로 고친 뒤 같은 명령을 다시 실행하세요. 데이터를 유지한 채 이어서 진행합니다.

화면 없는 Linux 서버는 [원격 서버에 설치](#local-and-ssh-admin-access), Windows는 [실행 환경](#platforms)을 보세요.

<a id="what-you-do-in-the-browser"></a>
## 2. 관리 화면에서 설정

관리 화면이 태블릿 옆에 지금 할 일을 하나씩 표시합니다.

1. **패스키 만들기**로 패스키를 저장합니다.
2. 태블릿의 Aurora에서 약관에 동의한 뒤 **익명(Anonymous)** 로그인을 고릅니다. 설치 방식을 물으면 **Session Installer**를 고릅니다.
3. 자동으로 열린 페이지에서 **Kakao Corp.의 카카오톡**을 **설치**합니다.
4. 카카오톡 로그인 화면에서 **다른 기기와 함께 사용**을 선택하고 로그인합니다. 아이디·비밀번호는 **텍스트 입력**으로 보냅니다.
5. 휴대폰 카카오톡 로그인이 유지되는지 확인하고 **휴대폰의 카카오톡 로그인이 유지되고 있습니다**를 체크한 뒤 **메시지 수집 시작**을 누릅니다.
6. 휴대폰에서 나에게 메시지를 보내 수집되는지 확인합니다.

> **다른 기기와 함께 사용** 옵션이 없거나 기기 이전을 요구하면 멈추세요. 휴대폰 카카오톡이 로그아웃될 수 있습니다.

막히면 단계 안내의 **다시 시도** 또는 **다시 확인**을 누르세요. [화면별 상세](web-ui.md#first-login)

<a id="connect-an-ai-when-ready"></a>
## 3. AI 연결 (선택)

**AI 연결 → AI 연결 설정**에서 사용할 곳을 고르세요.

| 사용할 곳 | 방식 | 준비물 |
| --- | --- | --- |
| ChatGPT | 개인 터널 (권장) | OpenAI 터널 ID와 실행용 API 키 · [터널 안내](openai-tunnel.md) |
| ChatGPT · 다른 원격 AI | 기존 HTTPS 주소 또는 Tailscale | 이 서버로 연결된 HTTPS 프록시 또는 Tailscale 계정 · [HTTPS 안내](dot-plugin.md) |
| 내 컴퓨터의 AI 앱 | stdio | 없음. 표시된 설정을 앱에 붙여 넣기 · [예시](api.md#stdio-mcp) |

연결한 뒤 AI에게 “카카오톡 수집 상태 알려줘”라고 요청해 확인하세요. 터미널에서도 설정할 수 있습니다.

```bash
kakaotalk-bridge setup-connection                          # Choose interactively
kakaotalk-bridge setup-connection --method openai-tunnel   # Then allow the tunnel in the admin screen
```

<a id="reopen-retry-and-advanced-environments"></a>
## 자주 쓰는 명령

어느 폴더에서나 실행할 수 있습니다. 설치하면 `kakaotalk-bridge` 명령이 Mac은 `~/.local/bin`(PATH에 없으면 `~/.zprofile`에 추가), Linux는 `/usr/local/bin`에 생깁니다. 설치 폴더의 기본 위치는 Mac `~/Library/Application Support/KakaoTalk Bridge`, Linux `~/.local/share/kakaotalk-bridge`이며, 설치 폴더 안의 `./bridge`도 같은 명령입니다.

```bash
kakaotalk-bridge up          # Start services and open the admin screen (no update)
kakaotalk-bridge admin       # Open the admin screen
kakaotalk-bridge doctor      # Status summary (--json for JSON)
kakaotalk-bridge stop        # Stop; data and logins are kept
kakaotalk-bridge start       # Start again
kakaotalk-bridge backup      # Encrypted backup to backups/*.kcs
kakaotalk-bridge cleanup     # Delete Bridge, its data and backups (shared tools stay)
```

> `docker compose down -v`는 카카오톡 로그인과 DB를 지웁니다. 중지는 `kakaotalk-bridge stop`을 쓰세요. [운영과 복구](operations.md)

<a id="update"></a>
## 업데이트

```bash
# Same command as install
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash

# Or (add --version <tag> to pick one)
kakaotalk-bridge upgrade

# Git checkouts
git pull && kakaotalk-bridge update --source
```

- 설정, Android 데이터, 카카오톡 로그인, 수집 승인은 유지됩니다. 업데이트 전에 암호화 백업을 만들고, 실패하면 이전 버전으로 되돌립니다.
- 0.2.2 이하 버전이나 첫 릴리스 전에 받은 설치에는 `kakaotalk-bridge` 명령이 없습니다. 첫 줄의 설치 명령으로 업데이트하면 명령이 생깁니다.
- `kakaotalk-bridge up`은 업데이트하지 않습니다.

[업데이트 상세](operations.md#update)

<a id="install-options"></a>
## 설치 옵션

설치 명령에서는 `bash -s --` 뒤에, 설치한 뒤에는 `kakaotalk-bridge up` 뒤에 붙이세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh \
  | bash -s -- --no-browser
kakaotalk-bridge up --no-browser
```

| 옵션 | 용도 |
| --- | --- |
| `--no-browser` | 브라우저를 열지 않고 링크만 출력 |
| `--verbose` | 도구 원문 출력 표시. 기본은 설치 폴더의 `.bridge/logs/`에 기록 |
| `--no-install` | 호스트 도구를 설치하지 않고 기존 도구만 사용 |
| `--admin-port 19443`, `--mcp-port 19787` | Mac 첫 설치의 관리·MCP 포트 지정 |
| `--apk-folder /path/to/apks` | 공식 카카오톡 APK 전체 세트로 스토어 설치 생략. 버전을 섞지 말 것 |
| `--url https://bridge.example.com` | 기존 HTTPS 프록시 사용 (아래) |
| `--plan` | 바꾸지 않고 진행 단계만 표시 |

| 환경 변수 | 용도 |
| --- | --- |
| `BRIDGE_HOME` | 설치 위치 변경. 예: `curl … \| BRIDGE_HOME=/srv/bridge bash` |
| `BRIDGE_VERSION` | 설치·업데이트할 릴리스 지정. 예: `BRIDGE_VERSION=v0.2.0` |

**기존 HTTPS 프록시:** 한 HTTPS 출처를 공용 진입점 `127.0.0.1:18787`로 전달한 뒤 `kakaotalk-bridge up --url https://bridge.example.com`을 실행하세요. 관리 화면은 `/admin/`, AI는 `/mcp`를 씁니다. 로그인 화면까지 숨기려면 프록시에서 `/admin`, `/admin/*`를 막으세요.

**수동 다운로드:** [GitHub Releases](https://github.com/rokrokss/kakaotalk-bridge/releases)에서 `bridge-install.tar.gz`를 받아 풀고 `bash install.sh`를 실행해도 됩니다. 출처 증명 확인은 [고급 설치](onboarding.md#install)를 보세요.

<a id="local-and-ssh-admin-access"></a>
## 원격 서버에 설치 (SSH)

```bash
# On the server
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh \
  | bash -s -- --no-browser
```

```bash
# On your computer: keep this running, then open the printed link
ssh -N -L 127.0.0.1:18789:127.0.0.1:18789 user@your-server
```

- 관리 화면은 서버의 `http://localhost:18789/admin/`에만 열립니다. 이 포트로는 MCP·ADB·수집 API를 제공하지 않습니다.
- `localhost`를 LAN 주소로 바꾸지 마세요. 패스키가 동작하지 않습니다.
- SSH를 닫아도 서버는 계속 실행되며, systemd 서버는 재부팅 후에도 자동으로 시작합니다.
- 링크를 다시 받으려면 서버에서 `kakaotalk-bridge passkey-login`을 실행하세요.
- 내 컴퓨터의 18789 포트가 사용 중이면 서버에서 `kakaotalk-bridge passkey-login --url http://localhost:19789`를 실행하고 `-L 127.0.0.1:19789:127.0.0.1:18789`로 연결하세요. 이후 이 주소를 계속 쓰세요.

<a id="from-a-downloaded-source-checkout"></a>
## 소스에서 실행 (개발용)

```bash
git clone https://github.com/rokrokss/kakaotalk-bridge.git
cd kakaotalk-bridge
bash install.sh --source   # Builds the images and Android components locally
```

- `BRIDGE_HOME`을 지정하지 않으면 이 폴더를 설치 위치로 씁니다.
- 자동 업데이트는 하지 않습니다. `git pull` 후 `kakaotalk-bridge update --source`를 쓰세요.

<a id="platforms"></a>
## 실행 환경

| 환경 | 실행 방식 | 검증 |
| --- | --- | --- |
| Apple Silicon Mac | 전용 Lima VM 자동 준비. Docker Desktop 불필요 | 0.1.0 새 설치 확인. 이번 버전의 설치 전체 과정은 미검증 |
| Intel Mac | QEMU 기반 Lima | 미검증 |
| Ubuntu·Debian Linux | Docker Engine과 Binder 모듈 자동 준비 | 0.1.0 새 설치·재부팅·업데이트 확인. 0.1.0 → 이번 버전 업데이트는 계정 없는 테스트 VM에서 확인 |
| 기타 Linux | 기존 Docker·Binder 사용 | 필수 도구가 없으면 안내 후 중단 |
| Windows + Linux 서버 | `install.ps1 -Remote`로 SSH 설치 | 미검증 |
| Windows WSL2 | Binder가 로드된 기존 배포판 | 동작 보장 없음 |

```powershell
.\install.ps1 -Remote user@linux-host   # Install on an existing Linux server over SSH
.\install.ps1 -Distribution Ubuntu      # WSL2 distribution with Binder already loaded
```

- Windows에는 OpenSSH가 필요합니다. `-Remote`는 설치 후 18789 포트 포워딩을 유지하며, Ctrl+C는 포워딩만 끝냅니다.
- 내려받은 스크립트 실행이 막히면 조직 정책에 따라 차단을 해제하세요.
- WSL2는 Binder가 없으면 아무것도 바꾸지 않고 멈춥니다. 설치한 뒤에는 `wsl kakaotalk-bridge doctor`처럼 실행합니다.
- 메모리·디스크가 충분한 arm64·x86_64 전용 호스트나 VM을 쓰세요. 권한이 제한된 컨테이너나 회사 관리 장비에서는 동작하지 않을 수 있습니다.

[검증 내역](implementation.md) · [미검증 범위](implementation.md#not-yet-verified)
