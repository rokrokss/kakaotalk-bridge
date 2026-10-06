# 개인 Bridge 설정

자동 준비와 단일 실행 명령은 [빠른 시작](quickstart.md)의 `bash install.sh` 또는 `./bridge up`을 사용하세요. 아래 개별 명령은 고급 배포에도 사용할 수 있습니다.

Linux Docker 호스트에서 계정 하나를 관리합니다. Mac에서는 홈 폴더를 마운트하지 않는 Lima VM을 만듭니다. 웹 화면에서 카카오톡 설치, 보조 기기 로그인, 휴대폰 확인, ChatGPT 연결을 안내합니다.

<a id="install"></a>
## 설치

저장소를 복제하고 루트에서 실행하세요.

```bash
git clone https://github.com/rokrokss/kakaotalk-bridge.git
cd kakaotalk-bridge
```

Mac에는 Lima(`brew install lima`), Linux에는 Docker Engine·Compose v2·Bash·OpenSSL·Android binder가 필요합니다. [Linux 설치](install.md)를 참고하세요. 호스트 CLI는 Python 3.12 이상을 사용하고 별도 Python 패키지는 필요하지 않습니다.

공개 릴리스는 이 저장소의 GitHub Releases에서 `release.json`을 내려받아 출처를 검증하세요.

```bash
gh attestation verify release.json --repo rokrokss/kakaotalk-bridge
./bridge install --manifest release.json
./bridge passkey-login
```

매니페스트는 Linux arm64·amd64의 서버·기기·게이트웨이 이미지 다이제스트를 고정합니다. 세 이미지가 모두 필요하므로 이전 두 이미지 매니페스트는 새 릴리스로 바꿔야 합니다. 아직 공개 릴리스가 없다면 소스를 빌드하세요.

```bash
./bridge install --source
./bridge passkey-login
```

Android 구성 요소도 컴파일하므로 시간이 더 걸립니다. Mac은 Lima 안에서 빌드하며 Docker Desktop이 필요하지 않습니다. 첫 시작에 Ubuntu와 컨테이너 의존성을 내려받습니다. 기본 VM `kakaotalk-bridge`는 이전 개발 VM `kakaotalk-test`와 별개입니다. 첫 설치에서 포트 충돌을 피하려면 `./bridge install --source --admin-port 19443` 등을 사용하세요.

반복 설치는 기존 키·컨테이너를 유지합니다. 이미지 변경은 `update`로 수행하세요. 다른 VM·폴더의 배포를 자동 가져오지 않습니다. Android 데이터만 새 설치에 복사하지 마세요. 원래 등록·API 데이터·키와 함께 유지해야 합니다.

<a id="register-a-passkey-and-open-admin"></a>
## 패스키 등록과 관리 화면

`./bridge passkey-login`으로 localhost의 일회용 등록 링크를 여세요. 원격 서버는 [SSH 포워딩](quickstart.md#local-and-ssh-admin-access)을 사용합니다. 기존 HTTPS 출처는 재사용합니다. 링크를 비공개로 보관하고 **패스키 만들기**로 기기·비밀번호 관리자에 저장하세요. 개발자 계정이나 관리자 비밀번호는 필요하지 않습니다. [패스키 설정·복구](passkeys.md)

관리 주소를 북마크하세요. **로그인 유지**는 7일, 선택하지 않으면 30분입니다. 컨테이너 재시작 후에도 유지되며 **태블릿 및 설정 → 관리 브라우저**에서 취소할 수 있습니다. `./bridge admin`으로 같은 주소를 엽니다.

공용 HTTPS 구성은 고정 호스트와 443 포트를 사용할 수 있습니다.

| 주소 | 접근 |
| --- | --- |
| `https://<node>.ts.net/admin/` | 로그인 화면은 공개, 관리는 패스키 인증 필요 |
| `https://<node>.ts.net/mcp` | 공개 Funnel, MCP OAuth와 패스키 승인 필요 |

`./bridge setup-connection --method tailscale`은 신뢰 인증서를 제공하는 Funnel을 설정합니다. 기존 localhost 관리자 출처는 유지하고 코드 승인을 구성합니다. 공용 HTTPS에서는 패스키에 묶인 호스트 이름으로 접속하세요. Tailscale 인증 헤더가 패스키 인증을 대신하지 않습니다. Funnel을 관리·API 게이트웨이에 연결하지 마세요.

`expose`는 다른 앱의 Tailscale 경로를 덮어쓰지 않습니다. 수동 경로가 있다면 443 Funnel을 공용 `dot-ingress` HTTP 포트에 연결하고 `./bridge connect --url https://<node>.ts.net`, `./bridge passkey-login --url https://<node>.ts.net --public-url https://<node>.ts.net`을 실행하세요. Mac 자동 설치의 진입점은 `127.0.0.1:18787`, 이전 개발 터널은 18788입니다. 기존 8443 경로는 전체 구성의 Bridge 소유권을 확인한 뒤에만 제거합니다. 같은 호스트의 패스키는 유지되지만 출처 변경은 이전 세션·진행 중 인증을 무효화합니다.

**태블릿 및 설정 → 패스키 및 복구**에서 백업을 추가하세요. 모두 잃으면 서버에서 `./bridge passkey-login --enroll`을 실행하세요. `./bridge admin --recovery`도 30분 긴급 세션용 일회용 링크를 발급합니다. 비밀번호·키 로그인은 명시적 `ADMIN_AUTH_MODE=local`에서만 가능합니다.

<a id="install-kakaotalk-and-verify-both-sessions"></a>
## 카카오톡 설치와 두 기기 확인

1. 로그인 후 **카카오톡 설정**의 자동 준비를 기다리세요. 새 기기는 한국어 설정, Android 프레임워크 재시작, SHA-256으로 검증한 고정 F-Droid Aurora 설치를 진행합니다. 기존 카카오톡·Bridge가 있으면 건너뜁니다. 수동 복구는 **태블릿 및 설정 → 설치**에 있습니다.
2. 태블릿의 Aurora에서 익명 로그인하고 Android 설치 요청을 허용한 뒤 **Kakao Corp.의 카카오톡**을 설치하세요. Aurora는 비공식 Play 클라이언트이며 서비스 가용성이 달라질 수 있습니다.
3. Bridge가 설치를 감지해 APK 서명을 검증하고 Bridge·Iris와 등록을 준비합니다. 기존 등록이 있으면 승인·앱 데이터를 유지합니다. 실패하면 멈추며 문제 해결 후 **준비 다시 시도**를 누르세요.
4. **다른 기기와 함께 사용**을 선택하고 직접 로그인하세요. 옵션이 없거나 주 기기 이전을 요구하면 중단하세요. 관리 화면이 로그인을 자동으로 확인합니다.
5. 휴대폰의 기존 로그인이 유지되는지 확인하고 두 항목을 체크해 수집을 시작하세요. 직접 확인한 기록이며 자동 보장이 아닙니다.
6. **태블릿 및 설정 → 수집 테스트 및 유지 관리**에서 테스트를 시작하고 휴대폰에서 나에게 메시지를 보내세요. 새 메시지 도착만 알리므로 다른 메시지로도 통과할 수 있습니다. AI 연결 후 정확한 내용을 조회해 확인하세요.

**준비 → 로그인 → 수집**을 마치면 **내 Bridge** 현황을 표시하고 설정·태블릿은 접습니다. AI 연결과 이벤트는 선택 사항입니다.

사전 로그인 점검은 한국어 화면을 인식합니다. 설치 전에 한국어를 설정하면 Play가 한국어 분할 APK를 선택합니다. 이미 영어로 설치했다면 같은 버전의 한국어를 Aurora 수동 다운로드 또는 일치하는 APK 세트로 가져오세요. 언어를 바꾸려고 로그인된 앱을 삭제하지 마세요.

Aurora를 사용할 수 없다면 휴대폰의 공식 APK 전체 세트를 가져오세요.

```bash
./bridge import-apks /path/to/apk-folder
```

자동 준비 또는 **수집 구성 요소 설치**에서 검증·설치합니다. 이전 세트와 혼합을 거부합니다. 신뢰하는 카카오 서명은 `device/setup.py`에 고정되어 있습니다. 정당한 서명 교체도 별도로 검증한 코드 업데이트가 필요하며 자동 우회하지 않습니다. APK·계정 인증 정보는 저장소에서 배포하지 않습니다.

<a id="connect-an-ai-client-optional"></a>
## AI 클라이언트 연결 (선택)

**AI 연결 → 연결 추가 또는 변경**에서 ChatGPT, 로컬 앱, 다른 원격 클라이언트, **나중에 결정**을 선택하세요. **모든 연결 방식**에는 stdio·기존 HTTPS·Tailscale Funnel·개인 OpenAI 터널이 표시됩니다. 기존 연결은 유지하고 수집에는 이 제공업체들이 필수가 아닙니다.

웹 설정은 필요한 서비스를 시작하고 한국어 단계·경과 시간을 표시합니다. 화면을 다시 열면 상태 조회와 마지막 성공 방식이 유지됩니다. 점검은 방식을 바꾸지 않습니다. 기존 **연결 설정**은 접혀 있으며 저장된 안내는 실패 후에도 유지됩니다. 작업은 한 번에 하나씩 실행합니다.

Tailscale 링크에서 로그인·승인한 뒤 **설정 계속**을 누르세요. Mac은 전용 Linux VM의 Tailscale을 사용합니다. 다른 Funnel·Serve 경로는 유지하고 충돌하면 자동 설정을 중단합니다. 기존 HTTPS 프록시는 미리 MCP 진입점에 연결되어 있어야 하며 DNS·외부 프록시는 설정하지 않습니다. HTTPS 출처 또는 전체 `/mcp`를 입력하면 정규화합니다.

HTTPS는 OAuth와 동의를 자동 구성합니다. AI에 `/mcp` 주소와 OAuth를 추가하세요. 비공개 관리 구성은 **AI 연결**의 코드로, 공용 HTTPS는 연결 브라우저의 패스키로 승인합니다. 요청은 10분 후 만료되며 언제든 관리 화면에서 해제할 수 있습니다. 브라우저 바인딩·Origin·리디렉션·PKCE 검증을 유지합니다.

OpenAI 폼에는 터널 ID, 가려진 실행용 키, 명시적 권한 체크가 있습니다. 설정 후 해제할 때까지 허용하며 같은 ID의 저장된 키는 재사용할 수 있습니다. OpenAI의 터널 생성과 ChatGPT 선택은 제공업체에서 완료해야 합니다. [터널 안내](openai-tunnel.md)

stdio는 `./bridge mcp` 설정을 복사하며 OAuth·공개 URL이 필요하지 않습니다. 원격 서버는 SSH 대상과 비대화형 인증·Docker 접근이 필요합니다. 웹 점검은 서버 서비스만 확인합니다. AI에 상태·테스트 메시지를 요청해 전체 연결을 확인하세요. 승인과 마지막 성공 호출은 별도로 표시하며 이전 호출은 소급하지 않고 stdio는 기록하지 않습니다. 연결만으로 이벤트를 구독하지 않습니다.

실패하면 단계별 안내와 **확인 후 다시 시도**, 점검 실패는 **다시 확인**을 사용하세요. 중단된 작업을 자동 재제출하지 않습니다. [진행과 복구](web-ui.md#progress-and-recovery)

CLI는 `./bridge setup-connection`입니다. `./bridge up`이 systemd의 비공개 설정 에이전트를 설치·재시작합니다. 기존 설치는 먼저 소스·이미지를 갱신하세요. systemd가 없는 Linux에서는 설치 폴더와 Docker 접근 권한을 갖춘 root로 `./bridge --local setup-agent serve`를 서비스 관리자에서 실행하세요. 에이전트가 없으면 성공으로 표시하지 않고 복구를 안내합니다.

<a id="maintain-and-recover"></a>
## 유지 관리와 복구

```bash
./bridge doctor
./bridge backup
./bridge update --manifest release.json
```

`doctor`는 본문·토큰·원문 로그 없이 서비스 상태와 없는 필수 항목을 출력합니다. `backup`은 잠시 스택을 멈추고 AES-256-GCM으로 오프라인 백업한 뒤 이전에 실행되던 서비스를 다시 시작합니다. 볼륨 7개·`.env`·`secrets/`와 Android 소유권·권한·링크·확장 속성을 보존합니다. Unix 소켓은 프로세스가 다시 만듭니다. 백업과 복원 데이터를 둘 다 담을 디스크가 필요합니다.

`backups/*.kcs`에 저장하고 Mac에서는 Lima 밖으로 자동 복사합니다. **`secrets/backup_key`는 별도 보관하세요.** 암호화된 백업 내부의 키로 그 백업을 열 수는 없습니다. Mac 자동 설치의 키는 다음처럼 비공개로 내보내세요.

```bash
umask 077
limactl shell --workdir=/ kakaotalk-bridge sudo cat /srv/kakaotalk-bridge/secrets/backup_key > /your/private/location/backup_key
```

같은 코드 릴리스로 초기화한 설치에 복구하세요.

```bash
./bridge stop
./bridge restore /path/to/snapshot.kcs --key /path/to/backup_key
./bridge start
./bridge admin
```

압축 해제 전에 인증을 검증하고 새 볼륨에 쓴 뒤 검증 후 설정을 전환합니다. 이전 볼륨·설정은 남기며 `down -v`는 실행하지 않습니다. 프로세스 중단을 포함한 활성화 실패는 롤백합니다. 패스키·설정·로컬 비밀번호·프로필 식별자는 유지하고 브라우저 세션·OAuth·이벤트 콜백은 지웁니다. ChatGPT를 다시 연결하고 요청한 이벤트를 재구독하며 두 기기 로그인을 확인하세요. 저장된 Android 세션도 카카오 서버에서 거부될 수 있습니다.

업데이트는 중지 전에 다운로드·빌드하고 암호화 백업 후 컨테이너 상태를 점검합니다. 실패하면 이전 이미지를 선택합니다. 로그인된 카카오톡·Bridge를 재설치하지 않습니다. Iris APK가 바뀌면 배포 전에 멈추며 별도의 검증된 이전이 필요합니다. 개인 Bridge 서명 키를 릴리스 키로 바꾸는 작업은 자동화하지 않습니다.

<a id="release-maintainers"></a>
## 릴리스 관리

`vMAJOR.MINOR.PATCH` 태그에서 양쪽 아키텍처를 빌드하고 SBOM·출처 메타데이터와 `release.json`을 버전 릴리스에 첨부합니다. 배포 전 보호된 GitHub `release` 환경에 고정 `BRIDGE_RELEASE_KEYSTORE_BASE64`, `BRIDGE_RELEASE_KEY_PASSWORD`를 설정하세요. 일반 업데이트에서 서명 식별자를 교체하지 마세요.

인증 없이 설치하려면 GHCR 세 패키지를 공개해야 합니다. 설치 프로그램은 GHCR에 로그인하지 않습니다. 이미지는 `ghcr.io/rokrokss/kakaotalk-bridge-server`, `ghcr.io/rokrokss/kakaotalk-bridge-device`, `ghcr.io/rokrokss/kakaotalk-bridge-gateway`입니다.

릴리스에는 `bridge-install.tar.gz`, `release.json`, `install.sh`, `install.ps1`, `SHA256SUMS`를 첨부합니다. 설치 번들에는 같은 커밋의 실행 코드·Compose 설정과 세 이미지의 고정 다이제스트가 함께 들어 있습니다. 익명 다운로드와 amd64·arm64 이미지가 확인되어야 정식 릴리스를 게시합니다. 첫 게시 때는 GitHub Packages의 각 패키지를 Public으로 바꾸세요. 공개 설정이 준비되지 않으면 워크플로가 중단되며 미완성 릴리스를 최신 버전으로 안내하지 않습니다.

일반 사용자는 설치 명령을 다시 실행하거나 `./bridge upgrade`로 설치 코드와 이미지를 함께 갱신합니다. Git 작업 폴더에서는 기존처럼 `git pull`과 `./bridge update --source`를 사용하세요. 공개 릴리스 설치 프로그램은 이미지 다운로드 실패 시 로컬 소스 빌드로 전환하지 않습니다. 로컬 빌드·격리 테스트가 모든 지원 호스트의 신규 설치 성공을 입증하지는 않습니다.
