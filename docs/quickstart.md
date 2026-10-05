# KakaoTalk Bridge 설치와 실행

설치 명령을 실행하면 필요한 도구와 서비스를 준비하고 브라우저에서 관리 화면을 엽니다. 기존 설치에서는 저장된 설정과 카카오톡 로그인을 그대로 사용합니다.

<a id="download-and-start"></a>
## 다운로드와 시작

Bridge를 실행할 macOS·Linux 컴퓨터의 터미널에 붙여 넣으세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

첫 실행은 최신 정식 릴리스의 설치 파일과 미리 빌드한 이미지를 내려받습니다. 설치 파일의 SHA-256을 확인하고 이미지 버전을 고정합니다. 사용자 컴퓨터에서 Android 앱이나 서버 이미지를 빌드하지 않습니다. 필요하면 Python과 Mac의 Homebrew·Lima, Linux의 Docker를 설치하며 관리자 승인을 요청할 수 있습니다. Tailscale은 선택한 경우에만 설치합니다.

터미널에서 진행 상태를 확인할 수 있습니다. 실패하면 재시도 방법과 로그 위치가 표시됩니다.

자세한 진단 출력은 `--verbose`로 확인하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash -s -- --verbose
# Or, from a downloaded source checkout:
./bridge up --verbose
```

기본 설치 위치는 Mac의 `~/Library/Application Support/KakaoTalk Bridge`, Linux의 `${XDG_DATA_HOME:-~/.local/share}/kakaotalk-bridge`입니다. `BRIDGE_HOME`으로 바꿀 수 있습니다. `BRIDGE_VERSION=v0.1.0`처럼 새 설치의 릴리스 버전을 지정할 수 있습니다. 기존 사본은 같은 설치 명령으로 업데이트되지 않습니다. 소스 폴더에서 `bash install.sh`를 실행하면 `BRIDGE_HOME`을 지정하지 않는 한 그 폴더를 사용합니다.

[GitHub Releases](https://github.com/rokrokss/kakaotalk-bridge/releases)에서 `bridge-install.tar.gz`를 직접 내려받아 압축을 풀고 `bash install.sh`를 실행해도 됩니다. 자동 설치는 GitHub API가 제공하는 자산 해시와 비교하며, 공급망 출처 증명을 별도로 확인하려면 [고급 설치](onboarding.md)를 참고하세요.

설치 폴더에서 `./bridge upgrade`를 실행하면 최신 정식 릴리스의 설치 파일과 이미지를 함께 업데이트합니다. 특정 버전은 `./bridge upgrade --version v0.1.0`으로 선택하세요. Linux에서는 필요한 경우 sudo를 요청합니다. 업데이트 전에 암호화 백업을 만들며, 지원하지 않는 Iris 구성 요소 변경은 적용 전에 중단합니다.

<a id="from-a-downloaded-source-checkout"></a>
## 이미 내려받은 소스에서 실행

macOS·Linux의 프로젝트 폴더에서 실행하세요.

```bash
bash install.sh --source
```

소스를 직접 개발할 때 사용하는 경로이며 로컬 빌드를 수행합니다. 필요하면 Python을 준비합니다. Python이 있다면 `./bridge up --source`도 같은 작업을 수행합니다. 변경 없이 계획만 보려면 다음을 실행하세요.

```bash
./bridge up --plan
```

<a id="what-you-do-in-the-browser"></a>
## 브라우저에서 할 일

1. 출력된 localhost 링크를 여세요. 원격 서버는 먼저 아래 SSH 포워딩을 실행하세요. 기존 설치는 관리 주소를 유지합니다.
2. 패스키를 저장해 Bridge를 보호하세요. 다시 접속할 때는 저장한 패스키를 사용합니다.
3. 가상 태블릿이 준비되면 Aurora 스토어에 익명으로 로그인하고 **Kakao Corp.의 카카오톡**을 설치하세요. 설치가 끝나면 Bridge가 카카오톡을 엽니다. [Aurora 설치 안내](web-ui.md#install-kakaotalk-in-aurora)
4. **다른 기기와 함께 사용**을 선택하고 **로그인 옵션 확인**을 실행한 뒤 로그인하세요. 휴대폰 로그인이 유지되는지 직접 확인하고 두 항목을 체크해 수집을 시작하세요.
5. 휴대폰에서 나에게 테스트 메시지를 보내 수집을 확인하세요. 필요하면 **AI 연결 → 연결 추가 또는 변경**을 열고 사용할 곳을 선택하세요. 나중에 연결해도 됩니다. 터미널에서는 `./bridge setup-connection`을 사용합니다.

공식 APK 전체 세트가 있다면 `./bridge up --apk-folder /path/to/apks`로 스토어 설치를 생략할 수 있습니다. 서로 다른 버전의 APK를 섞지 마세요. Bridge에는 카카오톡 APK나 계정 정보가 포함되지 않습니다.

준비에 실패하면 문제를 해결한 뒤 **준비 다시 시도** 또는 **다시 확인**을 누르세요. [로그인 상세](web-ui.md#first-login)

**내 Bridge**에서 수집 상태, 원격 AI 사용 기록, 휴대폰을 마지막으로 확인한 시각을 볼 수 있습니다. 태블릿 조작과 패스키·복구 설정은 **태블릿 및 설정**에 있습니다.

<a id="connect-an-ai-when-ready"></a>
## 필요할 때 AI 연결

**AI 연결 → 연결 추가 또는 변경**에서 선택하세요. **ChatGPT**는 개인 OpenAI 터널·HTTPS, **내 컴퓨터의 AI 앱**은 로컬·SSH stdio, **다른 원격 AI 클라이언트**는 기존 HTTPS·Tailscale Funnel을 제공합니다. 여러 방식을 함께 쓸 수 있으며, **나중에 결정**을 선택하면 현재 설정을 유지합니다.

화면 안내에 따라 연결을 설정하세요. HTTPS에는 서버 주소 또는 `/mcp`를 포함한 URL을 입력합니다. 터널에는 ID·실행용 키·접근 승인이 필요합니다. Tailscale 로그인 후에는 **설정 계속**을 눌러야 할 수 있습니다.

[AI 클라이언트에서도 연결을 마친 뒤](web-ui.md#finish-in-your-ai-client), 수집 상태와 직접 보낸 메시지를 요청해 연결을 확인하세요. 오류가 나면 [재시도 안내](web-ui.md#progress-and-recovery)를 참고하세요.

<a id="platforms"></a>
## 실행 환경

| 환경 | 실행 방식 | 현재 검증 |
| --- | --- | --- |
| Apple Silicon Mac | 전용 Lima Ubuntu VM 자동 준비, Docker Desktop 불필요 | 새 VM에서 소스 설치·브라우저·OAuth 확인 |
| Intel Mac | QEMU 기반 Lima, 없으면 설치 | 코드 경로 제공, 실제 설치 미검증 |
| Ubuntu·Debian Linux | 로컬 Docker Engine, Binder 모듈 설치·로드 시도 | 준비된 Ubuntu VM에서 `bridge up` 확인, 독립 신규 호스트 미검증 |
| 기타 Linux | 호환되는 기존 도구와 Binder 재사용 | 지원하지 않는 필수 도구가 없으면 조치 안내와 함께 중단 |
| Windows + Linux 서버 | PowerShell에서 SSH 설치 및 localhost 포워딩 유지 | 스크립트 제공, Windows 실행 미검증 |
| Windows WSL2 | Binder가 이미 로드된 기존 배포판 | 호환성 확인 후 진행. 기본 WSL2가 작동한다고 보장하지 않음 |

[설치 검증 내역과 미검증 범위](implementation.md#installation-and-restart-2026-10-05)

로컬 실행에는 arm64 또는 x86_64, 충분한 메모리·디스크, 가상화·커널 기능 접근 권한이 필요합니다. 권한이 제한된 컨테이너나 회사 관리 장비에서는 실행이 어려울 수 있습니다. Linux에서는 전용 호스트나 VM을 사용하세요.

Windows 소스 폴더에서 기존 Linux 서버를 사용하려면 다음을 실행하세요.

```powershell
.\install.ps1 -Remote user@linux-host
```

출력된 링크를 Windows 브라우저에서 여세요. 설치 후 18789 포트의 SSH 포워딩을 유지합니다. Ctrl+C로 포워딩만 종료하며 서버는 계속 실행됩니다. Windows OpenSSH가 필요합니다. 포트가 사용 중이면 다른 포워딩을 닫고 다시 시도하세요. 기존 HTTPS 관리 주소는 직접 접속할 수 있습니다. 조직 정책에 따라 다운로드한 스크립트의 실행 차단을 해제해야 할 수 있습니다.

Binder가 설정된 기존 WSL2 배포판에서는 다음을 실행하세요.

```powershell
.\install.ps1 -Distribution Ubuntu
```

Binder가 로드되지 않았으면 변경 전에 멈춥니다. WSL 설치·공유 커널 교체·배포판 삭제는 하지 않습니다. Windows 진입점은 공개된 Unix 설치 프로그램을 내려받습니다.

<a id="reopen-retry-and-advanced-environments"></a>
## 다시 열기·재시도·고급 환경

같은 설치 명령으로 중단된 설정을 이어서 진행하거나 관리 화면을 다시 열 수 있습니다. 실행 중인 서비스와 로그인 정보는 유지됩니다.

```bash
./bridge up --no-install                  # Require already installed host tools
./bridge up --no-browser                  # Print the link on a headless server
./bridge up --admin-port 19443            # Internal maintenance port on first Mac install
./bridge up --mcp-port 19787              # Local shared ingress port on first Mac install
./bridge doctor                          # Diagnostics (sudo may be needed on Linux)
```

기존 HTTPS 프록시가 있다면 하나의 HTTPS 출처를 공용 진입점(기본 `127.0.0.1:18787`)으로 전달하고 다음을 실행하세요.

```bash
./bridge up --url https://bridge.example.com
```

루트 주소는 `/admin/`으로 이동하며 AI는 같은 포트의 `/mcp`를 사용합니다.

공개 MCP 주소 없이 OpenAI에 연결하려면 **ChatGPT → 개인 터널 · 공개 주소 불필요**를 선택하세요. CLI는 `./bridge setup-connection --method openai-tunnel`이며 입력 키를 숨기고 저장한 뒤 서비스를 시작합니다. CLI 설정 후에는 관리 화면에서 별도로 승인해야 합니다. 마지막으로 ChatGPT에서 터널을 선택하세요. [개인 터널](openai-tunnel.md)

관리·MCP 주소는 달라도 됩니다. localhost·비공개 관리 화면은 기존 패스키를 유지하고 공개 OAuth는 관리 화면의 코드로 승인합니다. 같은 HTTPS 호스트라면 패스키로 직접 승인할 수 있습니다. 공개 로그인 화면까지 숨기려면 프록시에서 `/admin`, `/admin/*`를 차단하세요.

<a id="local-and-ssh-admin-access"></a>
## 로컬·SSH 관리 화면

기본 주소는 `http://localhost:18789/admin/`이며 Mac에서는 빈 포트를 선택할 수 있습니다. 루프백에만 공개하고 관리 화면만 제공합니다. MCP·ADB·수집 API는 제공하지 않습니다. 브라우저는 localhost에서 인증서 없이 패스키를 허용합니다. localhost를 LAN 주소로 바꾸지 마세요.

화면 없는 Linux 서버에서는 다음 명령으로 설치하세요. 서버에 데스크톱이나 브라우저는 필요하지 않습니다.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash -s -- --no-browser
```

기존 설치 폴더에서는 `./bridge up --no-browser`를 실행하세요. SSH 세션과 디스플레이 없는 Linux에서는 브라우저 실행을 자동으로 생략합니다. systemd 환경에서는 재부팅 후 실행 서비스가 시작됩니다. 내 컴퓨터에서는 다음 명령을 유지하고 출력된 설정 링크를 여세요.

```bash
ssh -N -L 127.0.0.1:18789:127.0.0.1:18789 user@your-server
```

SSH를 닫아도 서버는 계속 실행됩니다. 관리할 때 다시 연결하세요. 새 링크가 필요하면 `./bridge passkey-login --link-only`를 사용하세요. 로컬 포트가 사용 중이면 `./bridge passkey-login --url http://localhost:19789` 등으로 브라우저 출처를 바꾸고 로컬 19789를 서버 18789로 전달하세요. 이후 해당 출처를 유지하세요.

업데이트와 암호화 백업은 [운영](operations.md)을 참고하세요. `up`은 기존 이미지를 업데이트하지 않습니다.
