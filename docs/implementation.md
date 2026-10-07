# 검증 범위

[개발과 테스트 명령](development.md) · [현재 구조](design.md)

실제 카카오톡 계정으로 확인한 내용, 계정 없는 테스트 환경의 검사, 자동 검사를 구분합니다. 여기에 없는 환경과 동작은 검증하지 않은 것으로 보세요.

<a id="verified-with-a-real-account"></a>

## 실제 계정으로 확인한 내용

### 계정에 묶인 승인

실제 계정에서 읽기 전용으로, 값을 출력하지 않고 카카오톡 LocalUser DataStore의 `memochat_user_id`·`old_user_id`가 로그인한 사용자 본인의 ID와 같은지 확인했습니다. 이 값으로 승인하고 수집하는 현재 흐름 전체는 실제 계정으로 확인하지 않았습니다.

<a id="test-environments"></a>

## 계정 없는 테스트 환경

카카오톡 계정을 연결하지 않은 테스트 VM과 합성 Iris DB 행으로 다음을 확인했습니다.

- Iris v5 빌드와 페이지 조회, 일괄 저장과 건너뛰기 기록.
- 한국어 설치 출력, `kakaotalk-bridge doctor`, `backup`, `update`, `up`.
- docker 그룹 계정의 SSH `bridge mcp`.
- Apple Silicon Mac의 Lima VM에서 릴리스 설치와 소스로 받은 설치의 업데이트, 업데이트 실패 시 이전 코드·서비스로의 복구, `kakaotalk-bridge` 명령의 `doctor`·stdio MCP·`cleanup`.

<a id="automated-checks"></a>

## 자동 검사

명령은 [로컬 검사](development.md#local-checks)와 [컨테이너 검사](development.md#container-checks)에 있습니다. 모두 합성 데이터와 가상 기기·인증기를 사용합니다.

| 검사 | 범위 |
| --- | --- |
| `pytest` | 등록·수집 승인 조건, Iris 수집기의 페이지·일괄 저장·건너뛰기·커서 복구·Iris 자동 설치, API 인증·순서 저장·중복 제거·보관 기간, 조회·이름·과거 닉네임, MCP·OAuth·패스키·터널·이벤트, 관리 화면·연결 설정, 설치·업데이트·백업·출력·`doctor`. Caddy가 없으면 로컬 프록시 테스트는 건너뜀 |
| 전송 합성 검사 | 별도 키와 권한, 단일 전송 시도, 중복·응답 유실·계정 변경 차단, 백업 복구 시 재전송 방지, 브라우저의 OAuth 전송 동의·터널 권한 변경 |
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
- Mac에서 현재 버전을 새로 설치하는 전체 과정.
- Windows·WSL2, Intel Mac, amd64 호스트의 redroid·카카오톡 로그인·수집.
- 카카오톡 26.8.2 외 버전·스키마와 다른 호스트·커널 호환성.
- Tailscale·Funnel 신규 설정과 새 OpenAI 터널 생성의 전체 과정.
- 전체 대화 기록의 완전성, 수집 전후 읽음 상태 전체 비교, 24–72시간 연속 수신과 디스크 사용량.
- 실제 MCP 이벤트 실행. 자동 구독은 요구 사항이 아닙니다.

현재 동작은 [Iris](iris.md), [관리 화면](web-ui.md), [MCP](dot-plugin.md)를 참고하세요.
