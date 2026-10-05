# KakaoTalk Bridge 설치와 실행

같은 명령으로 Bridge를 시작하고 다시 열 수 있습니다. 실행 환경과 서비스를 준비한 뒤 로컬 관리 화면을 엽니다. 기본값으로 외부 AI를 연결하지 않으며 기존 설치·키·카카오톡 로그인을 재사용합니다. 기존 이미지를 업데이트하거나 이전 배포를 새 VM으로 옮기지는 않습니다.

<a id="download-and-start"></a>
## 다운로드와 시작

Bridge를 실행할 macOS·Linux 컴퓨터의 터미널에 붙여 넣으세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

저장소를 먼저 복제할 필요는 없습니다. 첫 실행은 소스를 내려받아 서버 이미지를 빌드하므로 시간이 걸릴 수 있습니다. 이후에는 설치된 사본을 재사용합니다. HTTPS와 공식 의존성 설치 프로그램을 사용하며 운영체제에서 관리자 승인을 요청할 수 있습니다. 필요하면 uv로 Python, Mac의 Homebrew·Lima, Linux의 Docker를 준비합니다. Tailscale은 명시적으로 선택할 때만 설치하며 셸 시작 파일은 바꾸지 않습니다.

터미널에는 **실행 환경 준비 중…**, **개인 Bridge 시작 중…** 같은 한국어 단계와 완료 여부가 표시됩니다. 오래 걸리는 단계는 30초마다 경과 시간을 알립니다. 하위 명령의 stdout·stderr는 설치 폴더의 비공개 `.bridge/logs/`에 저장하고, 초기 Python·다운로드 준비는 임시 로그를 사용합니다. 실패하면 한국어로 재시도 안내와 로그 위치를 표시합니다. 내부 예외와 진단 로그는 영어를 유지합니다. 외부 설치 프로그램의 비밀번호·동의 요청은 한국어 안내 후 원래 화면을 표시합니다. 일회용 등록·로그인 링크는 로그에 저장하지 않습니다.

문제 해결을 위해 원문 진단 출력을 직접 보려면 명시적으로 `--verbose`를 사용하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash -s -- --verbose
# Or, from a downloaded source checkout:
./bridge up --verbose
```

기본 설치 위치는 Mac의 `~/Library/Application Support/KakaoTalk Bridge`, Linux의 `${XDG_DATA_HOME:-~/.local/share}/kakaotalk-bridge`입니다. `BRIDGE_HOME`으로 바꿀 수 있습니다. `BRIDGE_VERSION`은 새 다운로드의 소스 태그·커밋을 선택하며 기존 사본을 업데이트하지 않습니다. 소스 폴더에서 `bash install.sh`를 실행하면 `BRIDGE_HOME`을 지정하지 않는 한 그 폴더를 사용합니다.

검증된 사전 빌드 릴리스는 [고급 설치](onboarding.md)에 따라 매니페스트를 검증한 뒤 `./bridge up --manifest /path/to/release.json`으로 사용하세요. 아직 공개되지 않은 이미지가 있다고 가정하지 않습니다.

<a id="from-a-downloaded-source-checkout"></a>
## 이미 내려받은 소스에서 실행

macOS·Linux의 프로젝트 폴더에서 실행하세요.

```bash
bash install.sh
```

필요하면 Python을 준비합니다. Python이 있다면 `./bridge up`도 같은 작업을 수행합니다. 변경 없이 계획만 보려면 다음을 실행하세요.

```bash
./bridge up --plan
```

<a id="what-you-do-in-the-browser"></a>
## 브라우저에서 할 일

1. 출력된 localhost 링크를 여세요. 원격 서버는 먼저 아래 SSH 포워딩을 실행하세요. 기존 설치는 관리 주소를 유지합니다.
2. 패스키를 저장해 Bridge를 보호하세요. 다시 접속할 때는 저장한 패스키를 사용합니다.
3. 로그인하면 기기 준비가 자동으로 시작됩니다. 화면의 Aurora 스토어에 익명으로 로그인하고 **Kakao Corp.의 카카오톡**을 설치하세요. Bridge가 감지해 배포자 서명을 확인하고 수집 구성 요소를 설치한 뒤 카카오톡을 엽니다. 화면 안내 또는 [Aurora 설치 안내](web-ui.md#install-kakaotalk-in-aurora)를 따르세요.
4. **다른 기기와 함께 사용**을 선택하고 **로그인 옵션 확인**을 실행한 뒤 로그인하세요. 휴대폰 로그인이 유지되는지 직접 확인하고 두 항목을 체크해 수집을 시작하세요. 이 확인은 자동화하지 않습니다.
5. 휴대폰에서 나에게 테스트 메시지를 보내 수집을 확인하세요. 필요하면 **AI 연결 → 연결 추가 또는 변경**을 열고 사용할 곳을 선택하세요. 나중에 연결해도 됩니다. 터미널에서는 `./bridge setup-connection`을 사용합니다.

스토어 약관 동의·앱 설치·패스키 생성·계정 인증은 사용자 대신 조용히 완료할 수 없습니다. 공식 APK 전체 세트가 있다면 `./bridge up --apk-folder /path/to/apks`로 스토어 설치를 생략할 수 있습니다. 같은 파일 가져오기는 반복해도 안전하지만 다른 버전 세트를 섞지는 않습니다. Bridge에는 카카오톡 APK나 계정 정보가 포함되지 않습니다.

작업 실패 시 자동 변경을 반복하지 않고 멈춥니다. 문제를 해결한 뒤 **준비 다시 시도** 또는 **다시 확인**을 누르세요. 기존 기기 등록과 수집 승인은 유지합니다. [로그인 상세](web-ui.md#first-login)

수집 중에는 **내 Bridge** 현황에서 수집·원격 AI 사용·휴대폰 직접 확인을 볼 수 있습니다. 화면, 설치, 패스키, 복구는 **태블릿 및 설정**에 있습니다. 휴대폰 재확인 안내는 로그아웃을 감지했다는 뜻이 아닙니다.

<a id="connect-an-ai-when-ready"></a>
## 필요할 때 AI 연결

**AI 연결 → 연결 추가 또는 변경**에서 선택하세요. **ChatGPT**는 개인 OpenAI 터널·HTTPS, **내 컴퓨터의 AI 앱**은 로컬·SSH stdio, **다른 원격 AI 클라이언트**는 기존 HTTPS·Tailscale Funnel을 제공합니다. **나중에 결정**은 현재 설정을 유지합니다. Tailscale과 OpenAI 터널은 모두 선택 사항이며 여러 방식을 함께 쓸 수 있습니다.

설정을 입력하고 한국어 진행 안내를 따르세요. HTTPS는 출처 주소 또는 전체 `/mcp` URL을 받습니다. 터널에는 ID·실행용 키·명시적 접근 승인이 필요합니다. Tailscale은 제공업체 로그인 후 **설정 계속**이 필요할 수 있습니다. 표시된 [클라이언트 연결 안내](web-ui.md#finish-in-your-ai-client)로 마무리하고 휴대폰 메시지를 조회하세요.

서버 설정·점검과 접근 승인은 AI 요청 성공과 별개입니다. AI에 수집 상태와 테스트 메시지를 요청하세요. 현황에는 성공한 원격 도구 호출만 기록하며 로컬 stdio나 현재 연결 가능 여부는 표시하지 않습니다. 저장된 안내는 점검·새로고침 후에도 유지됩니다. 수정은 **연결 설정**, 실패 후에는 **확인 후 다시 시도**를 사용하세요. [관리 화면 상세](web-ui.md#ai-connections)

<a id="platforms"></a>
## 실행 환경

| 환경 | 실행 방식 | 현재 검증 |
| --- | --- | --- |
| Apple Silicon Mac | 전용 Lima Ubuntu VM 자동 준비, Docker Desktop 불필요 | 새 VM 소스 설치와 실제 브라우저·OAuth 검증. 아래 범위 참고 |
| Intel Mac | QEMU 기반 Lima, 없으면 설치 | 코드 경로 제공, 실제 설치 미검증 |
| Ubuntu·Debian Linux | 로컬 Docker Engine, Binder 모듈 설치·로드 시도 | 준비된 Ubuntu VM에서 `bridge up` 확인, 독립 신규 호스트 미검증 |
| 기타 Linux | 호환되는 기존 도구와 Binder 재사용 | 지원하지 않는 필수 도구가 없으면 조치 안내와 함께 중단 |
| Windows + Linux 서버 | PowerShell에서 SSH 설치 및 localhost 포워딩 유지 | 스크립트 제공, Windows 실행 미검증 |
| Windows WSL2 | Binder가 이미 로드된 기존 배포판 | 호환성 확인 후 진행. 기본 WSL2가 작동한다고 보장하지 않음 |

2026-10-05 검증은 격리된 Apple Silicon Lima VM에서 소스 빌드 이미지, 실제 Android·Aurora 준비, 공식 카카오톡 APK 가져오기·서명 검증, 한국어 보조 기기 로그인 화면, 가상 인증기의 브라우저 WebAuthn, 실제 OAuth/MCP 서비스를 사용했습니다. MCP 콜백은 브라우저 테스트에서 가로챘습니다. VM을 완전히 중지한 뒤 같은 명령으로 약 27초 만에 재개했고 인증 정보·기기 등록·패스키·OAuth/MCP가 유지되었습니다. Mac 필수 도구는 이미 설치되어 있었습니다. 소스 빌드 재시도에는 약 22분이 걸렸습니다.

카카오톡 계정 로그인, Aurora 익명 다운로드, 신규 Tailscale·Funnel 설정, Intel Mac, Windows는 해당 테스트에 포함하지 않았습니다. 로컬 HTTPS 프록시를 사용해 기존 설치의 Tailscale 경로는 유지했습니다.

로컬 실행에는 arm64 또는 x86_64, 충분한 메모리·디스크, 가상화·커널 기능 접근 권한이 필요합니다. 제한된 컨테이너·회사 관리 장비·임의 커널을 모두 지원하지는 않습니다. Linux 작업은 전용 호스트·VM에서 실행하세요. Windows·Linux 커널을 교체하거나 관련 없는 Tailscale 경로·Docker 컨텍스트를 바꾸지는 않습니다.

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

같은 명령으로 재시작 후 이어서 진행하거나 브라우저를 다시 여세요. 같은 설치의 동시 작업은 프로세스 잠금으로 막습니다. `.bridge/onboarding.json`에는 단계·상태만 저장하며 일회용 링크는 저장하지 않습니다. 실행 중인 서비스와 로그인 정보는 재사용합니다.

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

VM은 유지 관리·공개 진입·로컬 관리 리스너를 분리합니다. Mac 신규 설치는 VM 시작 전에 빈 로컬 포트를 선택해 저장하며 재시도할 때 재사용합니다.

<a id="local-and-ssh-admin-access"></a>
## 로컬·SSH 관리 화면

기본 주소는 `http://localhost:18789/admin/`이며 Mac에서는 빈 포트를 선택할 수 있습니다. 루프백에만 공개하고 관리 화면만 제공합니다. MCP·ADB·수집 API는 제공하지 않습니다. 브라우저는 localhost에서 인증서 없이 패스키를 허용합니다. localhost를 LAN 주소로 바꾸지 마세요.

화면 없는 Linux 서버에서 `./bridge up --no-browser`를 실행하세요. 내 컴퓨터에서는 다음 명령을 유지하고 출력된 설정 링크를 여세요.

```bash
ssh -N -L 127.0.0.1:18789:127.0.0.1:18789 user@your-server
```

SSH를 닫아도 서버는 계속 실행됩니다. 관리할 때 다시 연결하세요. 새 링크가 필요하면 `./bridge passkey-login --link-only`를 사용하세요. 로컬 포트가 사용 중이면 `./bridge passkey-login --url http://localhost:19789` 등으로 브라우저 출처를 바꾸고 로컬 19789를 서버 18789로 전달하세요. 이후 해당 출처를 유지하세요.

**AI 연결 → 연결 추가 또는 변경** 또는 `./bridge setup-connection`으로 stdio, HTTPS/OAuth, Tailscale Funnel, OpenAI 터널을 추가하세요. **나중에 결정**은 기존 연결을 유지합니다. **터널 연결 해제**는 접근 권한을 취소하고 `./bridge tunnel disable`은 서비스도 중지합니다.

이미지 변경과 암호화 백업은 [운영](operations.md)을 따르세요. `up`은 기존 이미지를 업데이트하지 않습니다. 자동 호스트 테스트는 모든 운영체제에서 신규 설치·Tailscale 승인·스토어 설치·카카오톡 로그인에 성공했다는 뜻이 아닙니다.
