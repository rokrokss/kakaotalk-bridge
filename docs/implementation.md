# 검증 범위

[개발과 테스트 명령](development.md) · [현재 구조](design.md)

실제 카카오톡 계정으로 확인한 내용, 계정 없는 테스트 환경의 검사, 자동 검사를 구분합니다. 여기에 없는 환경과 동작은 검증하지 않은 것으로 보세요.

<a id="verified-with-a-real-account"></a>

## 실제 계정으로 확인한 내용

### 0.1.0 수집기

Apple Silicon Mac의 Lima VM(Ubuntu 24.04 arm64)에서 0.1.0 수집기로 확인했습니다. 이후 수집 승인 방식과 Iris가 바뀌었으므로 현재 버전의 검증으로 보지 마세요.

- Android 14 redroid 시작과 태블릿 설정(SM-T970, 1200 × 1920, 밀도 240).
- 웹 관리 화면에서 화면 보기·조작·한국어 입력.
- 카카오톡 **다른 기기와 함께 사용** 옵션 확인과 보조 기기 로그인.
- 사용자가 휴대폰에서 직접 확인한 기존 로그인 유지. 서버 자동 검사는 아닙니다.
- 승인 후 Iris DB 행 저장과 나에게 보낸 새 메시지 수집.
- 컨테이너·VM 재시작 후 상태 볼륨 유지.
- 카카오톡 26.8.2 암호화 프로필 DB의 일반·채널 발신자 이름 조회와 보관된 입장·퇴장 이벤트의 과거 오픈채팅 닉네임.
- 설치된 MCP 연결로 호출한 최근 메시지, 페이지, 방·발신자 필터, 문맥 조회. 에이전트의 호출이며 사용자 대화 안에서의 실행은 아닙니다.
- 패스키 등록, 공개 HTTPS OAuth와 ChatGPT의 `KakaoTalk Bridge` 연결, 개인 OpenAI 터널의 도구 호출. 터널 검사는 [터널 검증 범위](openai-tunnel.md#validation-scope)를 참고하세요.

### 계정에 묶인 승인

실제 계정에서 읽기 전용으로, 값을 출력하지 않고 카카오톡 LocalUser DataStore의 `memochat_user_id`·`old_user_id`가 로그인한 사용자 본인의 ID와 같은지 확인했습니다. 이 값으로 승인하고 수집하는 현재 흐름 전체는 실제 계정으로 확인하지 않았습니다.

<a id="test-environments"></a>

## 계정 없는 테스트 환경

카카오톡 계정을 연결하지 않은 테스트 VM과 합성 Iris DB 행으로 다음을 확인했습니다.

- Iris v5 빌드와 페이지 조회, 일괄 저장과 건너뛰기 기록.
- 0.1.0 승인 기록의 자동 이전.
- Linux(Ubuntu) 테스트 VM에서 0.1.0 설치를 현재 버전으로 업데이트.
- 한국어 설치 출력, `kakaotalk-bridge doctor`, `backup`, `update`, `up`.
- docker 그룹 계정의 SSH `bridge mcp`.
- 0.1.0 릴리스: 새 Ubuntu 24.04 arm64 VM과 Apple Silicon Mac의 새 Lima VM에서 공개 설치 번들로 설치(소스 빌드 없음), 재시작, 같은 릴리스 재적용. 릴리스 이미지는 amd64·arm64 모두 공개 다운로드를 확인했습니다.

<a id="automated-checks"></a>

## 자동 검사

명령은 [로컬 검사](development.md#local-checks)와 [컨테이너 검사](development.md#container-checks)에 있습니다. 모두 합성 데이터와 가상 기기·인증기를 사용합니다.

| 검사 | 범위 |
| --- | --- |
| `pytest` | 등록·수집 승인 조건과 0.1.0 승인 이전, Iris 수집기의 페이지·일괄 저장·건너뛰기·커서 복구·Iris 자동 설치, API 인증·순서 저장·중복 제거·보관 기간, 조회·이름·과거 닉네임, MCP·OAuth·패스키·터널·이벤트, 관리 화면·연결 설정, 설치·업데이트·백업·출력·`doctor`. Caddy가 없으면 로컬 프록시 테스트는 건너뜀 |
| 전송 합성 검사 | 별도 키와 권한, 단일 전송 시도, 중복·응답 유실·계정 변경 차단, 백업 복구 시 재전송 방지, 업데이트 키 생성과 롤백, 브라우저의 OAuth 전송 동의·터널 권한 변경 |
| Ruff | Python lint |
| Node (`node --test`) | 설정 흐름과 연결 안내의 JavaScript 판단 |
| Playwright | 단계별 설정 화면(준비, Aurora 로그인 감지와 카카오톡 페이지 열기, 스토어 설치 감지, 로그인 자동 감지, 휴대폰 확인 전 수집 시작 비활성, 승인 후 현황 전환), 패스키·OAuth 동의, 한국어 화면과 모바일 폭 |
| 기기 이미지 빌드 | Iris Kotlin 단위 테스트, 키보드 앱 lint·서명 확인 |
| Docker smoke | 격리된 Compose 프로젝트의 HTTPS 수집·조회, 재시작 후 보존, 암호화 DB 백업, stdio MCP, 관리 화면 세션, 공용 ingress의 쿠키 제거와 경로 차단 |

릴리스 워크플로는 이미지를 빌드하기 전에 pytest와 Ruff를 실행합니다.

<a id="not-yet-verified"></a>

## 아직 검증하지 않은 범위

- 로그인된 실제 카카오톡 DB에서 Iris v5와 계정에 묶인 승인으로 수집하는 흐름.
- 로그아웃·계정 전환 뒤 카카오톡이 LocalUser DataStore에 남기는 값.
- 실제 기기에서 휴대폰 로그아웃을 기록했을 때 수집 중지.
- 공개 설치 프로그램으로 새로 설치한 환경에서 실제 계정 로그인과 수집.
- 실제 Aurora에서 익명 로그인 감지(`ACCOUNT_SIGNED_IN`)와 카카오톡 페이지 자동 열기.
- 새 출력 방식을 포함한 Mac 설치 전체 과정.
- Windows·WSL2, Intel Mac, amd64 호스트의 redroid·카카오톡 로그인·수집.
- 카카오톡 26.8.2 외 버전·스키마와 다른 호스트·커널 호환성.
- Tailscale·Funnel 신규 설정과 새 OpenAI 터널 생성의 전체 과정.
- 전체 대화 기록의 완전성, 수집 전후 읽음 상태 전체 비교, 24–72시간 연속 수신과 디스크 사용량.
- 실제 MCP 이벤트 실행. 자동 구독은 요구 사항이 아닙니다.

현재 동작은 [Iris](iris.md), [관리 화면](web-ui.md), [MCP](dot-plugin.md)를 참고하세요.
