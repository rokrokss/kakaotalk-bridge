# 고급 설치

[설치와 실행](quickstart.md) · [운영과 복구](operations.md) · [README](../README.md)

일반 설치는 [설치와 실행](quickstart.md)의 설치 명령 하나면 됩니다. 이 문서는 릴리스 출처 검증, 직접 준비한 호스트·VM, 소스 빌드, 백업 복구, 릴리스 관리를 다룹니다.

<a id="install"></a>
## 릴리스를 검증해 설치

```bash
git clone https://github.com/rokrokss/kakaotalk-bridge.git
cd kakaotalk-bridge
# Download release.json from GitHub Releases into this folder, then:
gh attestation verify release.json --repo rokrokss/kakaotalk-bridge
./bridge install --manifest release.json
./bridge passkey-login
```

현재 소스로 직접 빌드하려면:

```bash
./bridge install --source   # Also compiles the Android components; takes longer
./bridge passkey-login
```

- 필요한 것: Mac은 Lima(`brew install lima`), Linux는 Docker Engine·Compose v2·Bash·OpenSSL·Android Binder. 호스트 CLI는 Python 3.12 이상만 있으면 됩니다.
- 매니페스트는 Linux arm64·amd64의 서버·기기·게이트웨이 이미지 다이제스트를 고정합니다.
- Mac은 Lima VM 안에서 빌드하며 Docker Desktop이 필요 없습니다. 기본 VM 이름은 `kakaotalk-bridge`이고 `--vm`으로 바꿉니다.
- 첫 설치에서 포트가 겹치면 `--admin-port 19443`처럼 지정하세요.
- 다시 실행하면 기존 키·컨테이너를 유지합니다. 이미지 변경은 `update`로 하세요. 다른 VM·폴더의 배포는 가져오지 않습니다.
- Android 데이터만 새 설치에 복사하지 마세요. 원래 등록·API 데이터·키와 함께 있어야 합니다.

<a id="manual-deployment"></a>
## 직접 준비한 Linux 호스트

```bash
./bridge install --manifest release.json   # or --source
./bridge passkey-login
./bridge doctor
./bridge stop
./bridge start
```

| 준비 | 내용 |
| --- | --- |
| 호스트 | 전용 amd64·arm64 호스트 또는 VM. CPU 4개·메모리 8 GB로 시작 권장(측정된 최소 사양 아님) |
| 도구 | Docker Engine, Compose v2, Bash, OpenSSL, Android Binder(`binder_linux` 모듈 또는 binderfs). `./bridge up`은 Ubuntu·Debian에서 설치까지 하고, `./bridge install`은 확인만 함 |

- `install`: Docker·Binder 확인 → 없는 `.env`와 인증 키 생성 → 이미지 다운로드(`--manifest`) 또는 빌드(`--source`) → 서비스 시작. 이미 설치된 폴더에서는 키와 컨테이너를 유지하고 서비스만 시작합니다.
- `passkey-login`은 [관리 화면 등록 링크](#register-a-passkey-and-open-admin)를 발급합니다. 관리 화면의 AI 연결 설정에는 [웹 연결 설정 서비스](operations.md#web-connection-setup)가 필요합니다.
- Linux에서 `./bridge`는 sudo로 다시 실행되며 설치 폴더를 root로 관리합니다. 코드와 `.env`(비밀값 없음)는 다른 계정도 읽을 수 있고 `secrets/`는 비공개입니다. AI 앱이 SSH 계정으로 실행하는 `./bridge mcp`만 예외이며, 그 계정은 `docker` 그룹에 속해야 합니다.

| 설정 | 방법 |
| --- | --- |
| Android 네트워크 | `DEVICE_SUBNET`(기본 `172.29.87.0/24`)이 LAN·VPN·다른 Docker 네트워크와 겹치면, 첫 설치 전에 `.env`에 `DEVICE_SUBNET`과 그 안의 `DEVICE_IP_RANGE`(기본 `172.29.87.128/25`)를 함께 지정. 다른 기본값은 `.env.example` |
| arm64 Android 이미지 | `REDROID_IMAGE`를 지정하지 않으면 `install`이 64비트 전용 이미지를 고름 |
| 카카오톡 APK | `./bridge import-apks /path/to/apk-folder`. 버전·서명이 같은 전체 분할 세트여야 하고 redroid ABI를 지원해야 함. 다른 세트가 이미 있으면 섞지 않고 중단 |
| arm64에서 소스 빌드 | Android 빌드 도구가 amd64용이라 amd64 에뮬레이션이 필요. 없으면 `install --source`가 권한 있는 컨테이너로 QEMU를 등록 |

### 직접 만든 Lima VM (Mac)

`./bridge`는 자신이 만든 전용 VM(기본 `kakaotalk-bridge`, 설치 경로 `/srv/kakaotalk-bridge`)만 관리합니다. `deploy/lima.yaml`(Ubuntu 24.04, CPU 6개, 메모리 8 GiB, 디스크 40 GiB, Mac 홈 폴더 미공유, 부팅 때 binderfs 준비)로 직접 만든 VM에서는 VM 안의 설치 폴더에서 위 Linux 명령을 쓰세요.

```bash
scripts/lima-compose.sh ps   # docker compose inside the VM (reads LIMA_INSTANCE, BRIDGE_DIR)
scripts/dot-tunnel.sh        # Forward Mac 127.0.0.1:18788 to the VM's MCP ingress (18787)
```

- `lima-compose.sh`는 `deploy/compose.lima.yaml`(Apple Silicon용 64비트 Android 14 이미지 고정, binderfs 기기 직접 연결)을 함께 적용합니다. `.bridge/`의 Compose 설정은 적용하지 않으므로 서비스 시작·중지는 VM 안의 `./bridge`로 하세요.
- 공개 HTTPS 구성은 [Mac의 Lima 배포](dot-plugin.md#deploy-in-lima-on-a-mac)를 보세요.

> Mac이 잠들면 수집과 외부 접속이 멈출 수 있습니다. `limactl delete`와 `docker compose down -v`는 로그인 상태와 데이터를 지웁니다.

<a id="register-a-passkey-and-open-admin"></a>
## 패스키와 관리 화면

```bash
./bridge passkey-login            # One-time registration link
./bridge admin                    # Open the saved admin address
./bridge passkey-login --enroll   # Lost every passkey: new one-time enrollment link
./bridge admin --recovery         # One-time link for a 30-minute emergency session
```

- 등록 링크는 localhost 주소이며, 기존 HTTPS 관리 주소가 있으면 그 주소를 씁니다. 원격 서버는 [SSH 포워딩](quickstart.md#local-and-ssh-admin-access)을 쓰세요. 링크는 비공개로 두고 **패스키 만들기**로 기기나 비밀번호 관리자에 저장하세요. [패스키 설정·복구](passkeys.md)
- **로그인 유지**를 고르면 7일, 아니면 30분 유지됩니다. **태블릿 및 설정 → 관리 브라우저**에서 취소합니다.
- 백업 패스키는 **태블릿 및 설정 → 패스키 및 복구**에서 추가하세요.
- 비밀번호·키 로그인은 `ADMIN_AUTH_MODE=local`일 때만 쓸 수 있습니다.

**공용 HTTPS (Tailscale Funnel)**

```bash
./bridge setup-connection --method tailscale   # Funnel with a trusted certificate
```

| 주소 | 접근 |
| --- | --- |
| `https://<node>.ts.net/admin/` | 로그인 화면은 공개, 관리는 패스키 인증 필요 |
| `https://<node>.ts.net/mcp` | 공개 Funnel, MCP OAuth와 패스키 승인 필요 |

- 기존 localhost 관리 주소는 그대로 두고, 공개 OAuth는 코드 승인으로 구성합니다.
- 공용 HTTPS에서는 패스키에 묶인 호스트 이름으로 접속하세요. Tailscale 인증 헤더가 패스키 인증을 대신하지 않습니다. Funnel을 관리·API 게이트웨이에 연결하지 마세요.
- `expose`는 다른 앱의 Tailscale 경로를 덮어쓰지 않습니다. 직접 만든 경로라면 443 Funnel을 공용 `dot-ingress` HTTP 포트(기본 `127.0.0.1:18787`, 직접 만든 Lima VM은 18788)에 연결한 뒤 실행하세요.

```bash
./bridge connect --url https://<node>.ts.net
./bridge passkey-login --url https://<node>.ts.net --public-url https://<node>.ts.net
```

- 기존 8443 경로는 전체 구성이 Bridge 것인지 확인한 뒤에만 지웁니다.
- 같은 호스트의 패스키는 유지되지만, 출처를 바꾸면 이전 세션과 진행 중인 인증은 무효가 됩니다.

<a id="install-kakaotalk-and-verify-both-sessions"></a>
## 카카오톡 설치와 두 기기 확인

1. 로그인 후 **카카오톡 연결** 단계의 자동 준비를 기다립니다. 새 기기는 한국어 설정, Android 프레임워크 재시작, SHA-256으로 검증한 F-Droid Aurora 설치, Aurora 설치 권한 허용까지 진행합니다. 기존 카카오톡·Bridge가 있으면 건너뜁니다.
2. 태블릿의 Aurora에서 익명으로 로그인하면 카카오톡 페이지가 열립니다. **Kakao Corp.의 카카오톡**을 설치합니다.
3. Bridge가 설치를 감지해 카카오톡 서명을 검증하고 키보드 앱과 기기 등록을 준비합니다. Iris는 수집을 승인한 뒤 수집기가 설치합니다.
4. **다른 기기와 함께 사용**을 선택하고 직접 로그인합니다.
5. 휴대폰 로그인이 유지되는지 확인하고 **휴대폰의 카카오톡 로그인이 유지되고 있습니다**를 체크한 뒤 **메시지 수집 시작**을 누릅니다. 승인은 태블릿에 로그인된 카카오톡 계정에 묶입니다.
6. **태블릿 및 설정 → 수집 테스트 및 유지 관리**에서 테스트를 시작하고 휴대폰에서 나에게 메시지를 보냅니다.

> **다른 기기와 함께 사용** 옵션이 없거나 주 기기 이전을 요구하면 중단하세요.

- 실패하면 단계 안내의 **다시 시도**를 누르세요. 수동 복구는 **태블릿 및 설정 → 설치**에 있습니다. 기존 등록이 있으면 승인과 앱 데이터를 유지합니다.
- 수집 테스트는 새 메시지 도착만 확인하므로 다른 메시지로도 통과할 수 있습니다. AI 연결 후 정확한 내용을 조회하세요.
- 로그인 화면 안내는 한국어 화면을 인식합니다. 이미 영어로 설치했다면 같은 버전의 한국어를 Aurora 수동 다운로드나 일치하는 APK 세트로 가져오세요. 언어를 바꾸려고 로그인된 앱을 지우지 마세요.
- Aurora는 비공식 Play 클라이언트이며 서비스 가용성이 달라질 수 있습니다.

Aurora를 쓸 수 없다면 휴대폰의 공식 APK 전체 세트를 가져오세요.

```bash
./bridge import-apks /path/to/apk-folder
```

- 자동 준비나 **수집 구성 요소 설치**에서 검증하고 설치합니다. 이전 세트와 섞이지 않게 막습니다.
- 신뢰하는 카카오 서명은 `device/setup.py`에 고정되어 있습니다. 정당한 서명 교체도 별도로 검증한 코드 업데이트가 필요하며 자동으로 우회하지 않습니다. APK·계정 정보는 저장소에서 배포하지 않습니다.

<a id="connect-an-ai-client-optional"></a>
## AI 클라이언트 연결 (선택)

관리 화면의 **AI 연결 → AI 연결 설정**을 쓰거나 터미널에서 설정합니다.

```bash
./bridge setup-connection                  # Choose interactively
./bridge setup-connection --method stdio   # Local app: copy the ./bridge mcp client config
```

| 방식 | 필요한 것 | 승인 |
| --- | --- | --- |
| 개인 OpenAI 터널 | 터널 ID, 실행용 키, 명시적 권한 체크. 터널 생성과 ChatGPT 선택은 OpenAI에서 | 설정할 때 허용하며 해제할 때까지 유지. 같은 ID의 저장된 키는 재사용. [터널 안내](openai-tunnel.md) |
| 기존 HTTPS | MCP 진입점에 미리 연결된 프록시. DNS·외부 프록시는 설정하지 않음 | OAuth. 비공개 관리 구성은 **AI 연결**의 코드로, 공용 HTTPS는 연결 브라우저의 패스키로 승인. 요청은 10분 후 만료 |
| Tailscale | Tailscale 계정. Mac은 전용 Linux VM의 Tailscale 사용 | 링크에서 로그인·승인 후 **설정 계속** |
| stdio | 원격 서버라면 SSH 대상, 비대화형 인증, `docker` 그룹 권한 | 필요 없음. OAuth·공개 URL 불필요 |

- 웹 설정은 한 번에 하나씩 실행합니다. 실패하면 **서버 준비** 단계의 안내를 확인하고 **다시 시도**하세요. 중단된 작업을 자동으로 다시 제출하지 않습니다. [진행과 복구](web-ui.md#progress-and-recovery)
- 다른 Funnel·Serve 경로는 유지하며, 충돌하면 자동 설정을 멈춥니다. HTTPS 출처나 전체 `/mcp` 주소를 입력하면 정규화합니다.
- 웹 점검은 서버 서비스만 확인합니다. AI에게 상태와 테스트 메시지를 요청해 전체 연결을 확인하세요. 승인과 마지막 성공 호출은 따로 표시하며 stdio는 기록하지 않습니다.
- 연결만으로 이벤트를 구독하지 않습니다.
- 설정 에이전트가 없으면 성공으로 표시하지 않고 복구를 안내합니다. [웹 연결 설정 서비스](operations.md#web-connection-setup)

<a id="maintain-and-recover"></a>
## 유지 관리와 복구

```bash
./bridge doctor
./bridge backup
./bridge upgrade            # Release installs
./bridge update --source    # Git checkouts, after git pull
```

> **`secrets/backup_key`는 백업과 따로 보관하세요.** 암호화된 백업 안의 키로는 그 백업을 열 수 없습니다.

Mac 자동 설치의 백업 키 내보내기:

```bash
umask 077
limactl shell --workdir=/ kakaotalk-bridge sudo cat /srv/kakaotalk-bridge/secrets/backup_key \
  > /your/private/location/backup_key
```

복구 (같은 코드 릴리스로 초기화한 설치에서):

```bash
./bridge stop
./bridge restore /path/to/snapshot.kcs --key /path/to/backup_key
./bridge start
./bridge admin
```

- `backup`은 잠시 스택을 멈추고 AES-256-GCM으로 오프라인 백업한 뒤, 실행 중이던 서비스를 다시 시작합니다. 볼륨 7개, `.env`, `secrets/`와 Android 파일의 소유권·권한·링크·확장 속성을 보존합니다.
- 백업은 `backups/*.kcs`에 저장하고 Mac에서는 Lima 밖으로 자동 복사합니다. 백업과 복원 데이터를 함께 담을 디스크 공간이 필요합니다.
- `restore`는 압축을 풀기 전에 인증을 검증하고, 새 볼륨에 쓰고 검증한 뒤 설정을 전환합니다. 실패하면 롤백하며 이전 볼륨·설정은 남깁니다(`down -v`를 실행하지 않음).
- 복구 후 패스키·설정·로컬 비밀번호·프로필 식별자는 유지되고, 브라우저 세션·OAuth·이벤트 콜백은 지워집니다. ChatGPT를 다시 연결하고, 이벤트를 다시 구독하고, 두 기기 로그인을 확인하세요. 저장된 Android 세션을 카카오 서버가 거부할 수도 있습니다.
- 업데이트 동작은 [운영의 업데이트](operations.md#update)를 보세요. 카카오톡은 재설치하지 않고, 키보드 앱은 기기의 빌드와 다르면 같은 서명 키로 다시 설치합니다. 개인 Bridge 서명 키를 릴리스 키로 바꾸는 작업은 자동화하지 않습니다.

<a id="release-maintainers"></a>
## 릴리스 관리

```bash
git tag -a vX.Y.Z -m "KakaoTalk Bridge vX.Y.Z"
git push origin vX.Y.Z   # Runs the release workflow
```

| 준비 | 내용 |
| --- | --- |
| 서명 키 | 보호된 GitHub `release` 환경에 `BRIDGE_RELEASE_KEYSTORE_BASE64`, `BRIDGE_RELEASE_KEY_PASSWORD`. 일반 업데이트에서 서명 식별자를 바꾸지 말 것 |
| GHCR 공개 | 첫 게시 때 `ghcr.io/rokrokss/kakaotalk-bridge-server`, `-device`, `-gateway` 패키지를 Public으로. 설치 프로그램은 GHCR에 로그인하지 않음 |
| 릴리스 본문 | `docs/release-notes.md` |

- 워크플로: pytest·Ruff → 양쪽 아키텍처 빌드 → SBOM·출처 메타데이터 → 익명 다운로드와 amd64·arm64 이미지 확인 → 게시. 공개 설정이 준비되지 않으면 멈추고, 미완성 릴리스를 최신 버전으로 안내하지 않습니다.
- 첨부 파일: `bridge-install.tar.gz`, `release.json`, `install.sh`, `install.ps1`, `SHA256SUMS`. 설치 번들에는 같은 커밋의 실행 코드·Compose 설정과 세 이미지의 고정 다이제스트가 들어 있습니다.
- 공개 릴리스 설치 프로그램은 이미지 다운로드에 실패해도 로컬 소스 빌드로 바꾸지 않습니다. 로컬 빌드나 격리 테스트가 모든 지원 호스트의 새 설치 성공을 입증하지는 않습니다.
