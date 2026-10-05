<div align="center">

<img src="assets/logo.svg" width="88" height="88" alt="KakaoTalk Bridge 로고">

<h1>KakaoTalk Bridge</h1>

**내 대화에서 찾는 답, 내가 쓰는 AI로.**

약속을 찾고, 놓친 대화를 읽고, 달라진 내용을 물어보세요.<br>
수집한 카카오톡 메시지를 ChatGPT나 MCP를 지원하는 AI에 연결합니다.

직접 호스팅 · 브라우저에서 설정 · 메시지 읽기 전용

[시작하기](#getting-started) · [첫 질문 해보기](#try-your-first-question) · [AI 연결하기](#connect-your-ai) · [사용 안내](#documentation)

</div>

<a id="getting-started"></a>
## 시작하기

Apple Silicon Mac 또는 호환되는 Linux 서버에서 실행하세요. 휴대폰을 그대로 사용하면서 가상 Android 태블릿으로 메시지를 수집합니다. 실제 태블릿은 필요하지 않습니다.
[실행 환경과 검증 범위](#requirements-and-validation)

실행할 컴퓨터의 터미널에서 아래 명령을 입력하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

설치 프로그램이 Bridge를 다운로드하고 실행한 뒤 브라우저에서 설정 화면을 엽니다. 같은 명령을 다시 실행하면 이어서 설정하거나 화면을 다시 열 수 있습니다.

프로젝트를 이미 내려받았다면 해당 폴더에서 `bash install.sh`를 실행하세요.
[Windows·원격 서버를 포함한 설치 안내 →](docs/quickstart.md)

<p align="center">
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-journey-mobile.svg">
    <img src="docs/assets/readme-journey.svg" width="1120" alt="브라우저에서 Bridge를 열고, 카카오톡에 로그인해 두 기기의 로그인을 확인한 뒤, AI를 연결해 보낸 메시지를 찾아보는 세 단계">
  </picture>
</p>

1. **관리 화면을 여세요.** 패스키를 저장하면 태블릿이 자동으로 준비됩니다. 화면의 스토어에서 **Kakao Corp.의 카카오톡**을 설치하세요.
2. **휴대폰 로그인을 유지하며 태블릿에 로그인하세요.** 카카오톡에서 **다른 기기와 함께 사용**을 선택한 뒤 관리 화면의 **로그인 옵션 확인**을 실행하세요. 로그인을 마치고 휴대폰의 기존 로그인이 유지되는지 확인하세요. 두 기기를 모두 확인한 뒤 **메시지 수집 시작**을 누르세요.
3. **[AI를 연결하세요.](#connect-your-ai)** 연결 안내를 따르거나 **나중에 결정**을 선택하고 수집만 계속해도 됩니다.

로그인 점검은 현재 한국어 카카오톡 화면을 인식합니다. 보조 기기 옵션이 없거나 주 계정 이전을 요구하면 진행을 멈추세요.
[로그인 단계별 안내 →](docs/web-ui.md#first-login)

<a id="try-your-first-question"></a>
## 첫 질문 해보기

수집이 시작되면 휴대폰에서 나에게 아래 두 메시지를 보내세요.

> 금요일 모임은 저녁 7시야. 지난번 그 카페에서 만나.
>
> 금요일 모임 7시 반으로 바뀌었어. 장소는 그대로야.

연결한 AI에 **“금요일 모임에 관한 메시지를 찾아줘. 몇 시에 만나고, 장소도 바뀌었어?”**라고 물어보세요. 두 메시지를 모두 찾았는지 확인하세요.

<p align="center">
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-example-mobile.svg">
    <img src="docs/assets/readme-example.svg" width="1120" alt="가상 메시지 예시: 같은 카페에서 열리는 모임이 저녁 7시에서 7시 30분으로 변경됩니다. AI가 두 메시지를 찾아 변경 내용을 설명합니다.">
  </picture>
</p>

**대화 요약**, **키워드·날짜별 메시지 검색**, **수집 상태 확인**도 요청할 수 있습니다.

<a id="connect-your-ai"></a>
## AI 연결하기

**AI 연결 → 연결 추가 또는 변경**에서 메시지를 사용할 곳을 선택하세요. 여러 연결 방식을 함께 사용할 수 있습니다.

| 사용하려는 환경 | 관리 화면에서 선택 | 필요한 것 |
| --- | --- | --- |
| 공개 서버 주소 없이 ChatGPT 사용 | **개인 터널 · 공개 주소 불필요** | OpenAI 터널 ID와 실행용 API 키. [터널 안내](docs/openai-tunnel.md) |
| HTTPS로 ChatGPT 또는 다른 원격 AI 연결 | **기존 HTTPS 주소 사용** 또는 **Tailscale로 HTTPS 주소 만들기** | 설정된 HTTPS 프록시 또는 Tailscale Funnel. [HTTPS 안내](docs/dot-plugin.md) |
| 내 컴퓨터의 AI 앱 | **AI 앱에서 Bridge 실행 · 로컬 또는 SSH** | MCP 명령을 실행할 수 있는 클라이언트. 원격 서버라면 SSH 접근 권한. [클라이언트 설정](docs/api.md#stdio-mcp) |

폼을 작성한 뒤 AI 클라이언트에서도 연결을 추가하세요.
[단계별 연결 안내 →](docs/web-ui.md#finish-in-your-ai-client)

**연결 확인:** AI에 수집 상태 확인을 요청하고 직접 보낸 메시지를 찾아보세요. 서버 점검만으로 AI 접근까지 확인되지는 않습니다.

<a id="how-the-connection-methods-work"></a>
## 연결 방식별 동작

### 개인 OpenAI 터널

서버에서 OpenAI로 연결하므로 공개 MCP 주소가 필요하지 않습니다. 관리 화면 접근은 별도로 유지됩니다.

<img src="docs/assets/connection-tunnel.svg" width="960" alt="서버에서 OpenAI로 연결해 MCP 요청을 전달합니다. 관리 화면 접근과 개인 터널 승인은 별개입니다.">

### HTTPS와 OAuth

AI가 공개 MCP 주소로 연결합니다. 패스키로 승인하거나 비공개 관리 화면에서 일치하는 코드를 확인해 승인하세요.

<img src="docs/assets/connection-https.svg" width="960" alt="공용 HTTPS 예시: 클라이언트가 Funnel 또는 리버스 프록시를 거쳐 MCP에 접근합니다. 소유자가 패스키로 승인하면 클라이언트가 OAuth를 사용합니다.">

### 로컬 또는 SSH를 통한 stdio

AI 앱이 내 컴퓨터 또는 SSH를 통해 Bridge 어댑터를 실행합니다.

<img src="docs/assets/connection-stdio.svg" width="960" alt="AI 앱이 로컬 또는 SSH stdio 어댑터를 실행해 서버에 수집된 메시지를 읽습니다.">

[구조](docs/design.md) · [편집 가능한 연결도](docs/assets/connection-methods.drawio)

<a id="your-everyday-view"></a>
## 평소에는 관리 화면에서 확인하세요

메시지 수집, AI 사용 기록, 휴대폰 확인 기록을 한눈에 볼 수 있습니다.

<p align="center">
  <img src="docs/assets/admin-overview.png" width="1120" alt="가상 데이터를 사용한 KakaoTalk Bridge 관리 화면: 메시지 수집, 원격 AI 사용 기록, 직접 확인한 휴대폰 상태와 AI 연결·대화 이벤트·태블릿 설정 메뉴">
</p>

*실제 관리 화면에 가상 데이터를 표시한 예시입니다.* 휴대폰 상태는 직접 확인한 기록입니다. AI 사용 기록은 과거 원격 호출 기록이며 현재 연결 가능 여부를 뜻하지 않습니다. 로컬 stdio 사용은 기록하지 않습니다.

새 메시지 이벤트를 사용하려면 **대화 이벤트**에서 해당 대화를 **허용**하고 AI에도 구독을 요청하세요. [이벤트 설정과 제한 →](docs/events.md)

[관리 화면 안내](docs/web-ui.md) · [재시작·업데이트·복구](docs/operations.md) · [패스키와 복구](docs/passkeys.md)

<a id="requirements-and-validation"></a>
## 실행 환경과 검증 범위

| 실행 환경 | 지원 조건과 검증 상태 |
| --- | --- |
| Apple Silicon Mac | 가장 많이 검증한 환경입니다. 전용 Lima Linux VM을 사용하며 Docker Desktop은 필요하지 않습니다. 보조 기기 로그인, 수집, AI 접근을 확인했습니다. |
| Linux amd64 / arm64 | 전용 호스트 또는 VM에 Docker Engine, Compose v2, Android Binder가 필요합니다. 검증된 Mac/Lima 환경 밖의 카카오톡·redroid 호환성은 아직 확인하지 않았습니다. |
| Windows | 기존 Linux 서버 또는 Binder를 지원하는 WSL2가 필요합니다. Windows에서의 실행은 아직 검증하지 않았습니다. |

Mac VM에는 CPU 6개와 메모리 8 GiB가 설정됩니다. 측정된 최소 사양은 아닙니다.
[사전 조건](docs/quickstart.md#platforms)

HTTPS/OAuth와 터널을 통한 메시지 접근은 검증했고, stdio는 프로토콜 테스트를 수행했습니다. 모든 호스트의 완전한 신규 설치와 AI 이벤트의 전체 전달 과정은 아직 검증하지 않았습니다.
[검증 내역 →](docs/implementation.md)

<a id="your-data-and-collection-scope"></a>
## 데이터와 수집 범위

- **내 인프라에 보관합니다.** 기본 보관 기간은 30일이며, 요청한 결과는 연결한 AI에 전달됩니다.
- **MCP는 읽기 전용입니다.** 메시지 검색·조회만 가능하며 전송이나 태블릿 조작은 지원하지 않습니다.
- **일부 기록만 수집합니다.** 보조 태블릿에서 볼 수 있는 메시지만 대상입니다. 휴대폰 전체 기록, 원본 첨부파일, 수정·삭제 동기화는 제공하지 않습니다.
- **직접 확인해야 합니다.** 태블릿에서 대화를 열면 읽음 상태가 바뀔 수 있습니다. 휴대폰 로그인 유지 여부는 직접 확인하세요.

공식 redroid 이미지의 Android 보안 패치가 오래되었으므로 전용 호스트 또는 VM을 사용하세요.
[보안과 남은 위험](docs/security.md) · [수집 방식](docs/iris.md)

<a id="documentation"></a>
## 사용 안내

| 하고 싶은 일 | 읽을 문서 |
| --- | --- |
| 설치하고 로그인하기 | [빠른 시작](docs/quickstart.md) · [관리 화면](docs/web-ui.md) |
| AI 연결하기 | [OpenAI 터널](docs/openai-tunnel.md) · [HTTPS/OAuth](docs/dot-plugin.md) · [로컬/SSH 클라이언트](docs/api.md#stdio-mcp) |
| 이벤트를 보낼 대화 선택하기 | [MCP Events](docs/events.md) |
| 접근 관리·업데이트·복구 | [패스키](docs/passkeys.md) · [운영](docs/operations.md) |
| 배포 또는 내부 기능 개발 | [고급 설치](docs/onboarding.md) · [구조](docs/design.md) · [개발](docs/development.md) |

기존 설치를 사용 중이라면 [보안 업데이트 안내](docs/operations.md#upgrading-to-the-security-update)를 읽으세요.
[기여하기](CONTRIBUTING.md)

<a id="license-and-attribution"></a>
## 라이선스와 출처

프로젝트 전체 라이선스는 아직 지정되지 않았습니다. 수정된 Iris 빌드에는 별도의 [라이선스 및 소스 배포 조건](iris/NOTICE.md)이 적용됩니다.
KakaoTalk Bridge는 카카오의 공식 서비스가 아닙니다.
