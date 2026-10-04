<h1><img src="docs/assets/wordmark.svg" width="420" height="96" alt="KakaoTalk MCP"></h1>

내 카카오톡 메시지를 내 서버에 모으고, ChatGPT에서 조회합니다.

redroid를 보조 태블릿으로 실행하고 Iris로 메시지를 읽습니다. 별도 태블릿 없이 Docker Compose로 운영하며, 설치와 카카오톡 로그인은 웹 관리 화면에서 진행합니다.

[설치](docs/install.md) · [관리 화면](docs/web-ui.md) · [ChatGPT 연결](docs/dot-plugin.md) · [운영·백업](docs/operations.md) · [개발](docs/development.md)

## 사용 흐름

1. **서버를 준비합니다.** Linux 또는 Apple Silicon Mac의 Linux VM에서 컨테이너를 실행합니다.
2. **카카오톡에 로그인합니다.** 웹에서 보조 기기 옵션을 검사하고 로그인합니다. 핸드폰의 기존 로그인이 유지되는지 직접 확인한 뒤 수집을 시작합니다.
3. **ChatGPT에 연결합니다.** OAuth로 MCP 서버를 연결하고 최근 메시지, 검색 결과, 수집 상태를 요청합니다.

플러그인 연결만으로 이벤트 구독이나 자동 작업을 만들지는 않습니다. MCP Events는 [별도로 구독하는 선택 기능](docs/events.md)입니다.

## 어디서 실행되나요?

![내 서버의 보조 태블릿에서 Iris로 메시지를 읽어 저장하고, ChatGPT가 OAuth와 MCP로 조회합니다.](docs/assets/message-flow.svg)

| 구성 | 역할 | 접근 범위 |
| --- | --- | --- |
| redroid + Iris | 보조 태블릿 실행, 로컬 메시지 DB 읽기 | 서버 내부 |
| 수집 API | 저장·조회·검색, 기본 30일 보관 | 인증된 사설 HTTPS |
| 관리 화면 | 태블릿 조작, 로그인 확인 | 관리자 키 + 사설 HTTPS |
| MCP 플러그인 | ChatGPT에 조회 도구 제공 | 공개 HTTPS + OAuth |

메시지와 카카오톡 로그인 상태는 서버 볼륨에 저장됩니다. ChatGPT가 도구로 조회한 내용은 ChatGPT에 전달됩니다. 저장 위치·키·접근 제어는 [보안 안내](docs/security.md)를 참고하세요.

## 실행 환경

| 환경 | 안내 |
| --- | --- |
| Linux amd64 / arm64 | Docker Engine, Compose v2, Android binder 지원 커널 필요. [Linux 설치](docs/install.md) |
| Apple Silicon Mac | Lima의 Ubuntu VM에서 실행. [Mac 설치](docs/local-redroid.md) |

카카오톡 APK는 직접 준비해야 합니다. Apple Silicon의 Ubuntu VM에서 보조 로그인과 Iris 수집을 확인했으며, 핸드폰 로그인 유지는 사용자가 직접 확인했습니다. amd64는 이미지 빌드와 API 실행을 검증한 범위입니다. [검증 범위](docs/implementation.md)

## 수집 범위

- 태블릿 DB에 남아 있는 메시지 본문·종류·방/발신자 ID를 읽습니다. 중단 후에는 마지막 저장 위치부터 이어 읽습니다.
- 휴대폰의 전체 대화 복원, 첨부 원본, 표시 이름, 수정·삭제 동기화는 지원하지 않습니다.
- 핸드폰 세션은 자동으로 감시하지 않습니다. **‘다른 기기와 함께 사용’ 옵션이 없으면 로그인을 진행하지 마세요.**
- MCP에는 메시지 전송이나 태블릿 조작 도구가 없습니다. 웹에서 직접 채팅방을 열면 읽음 상태가 바뀔 수 있습니다.

## 문서

| 하고 싶은 일 | 문서 |
| --- | --- |
| 설치하고 로그인하기 | [Linux](docs/install.md), [Mac](docs/local-redroid.md), [관리 화면](docs/web-ui.md) |
| ChatGPT나 다른 클라이언트 연결하기 | [OAuth MCP](docs/dot-plugin.md), [HTTP API·stdio MCP](docs/api.md), [Events](docs/events.md) |
| 상태 확인·재시작·백업 | [운영](docs/operations.md), [보안](docs/security.md) |
| 구현 이해·수정·검증 | [구조](docs/design.md), [Iris](docs/iris.md), [개발](docs/development.md), [검증 범위](docs/implementation.md) |

Iris 수정 빌드의 라이선스와 소스 제공 방법은 [NOTICE](iris/NOTICE.md)에 있습니다. 이 프로젝트는 카카오의 공식 서비스가 아닙니다.
