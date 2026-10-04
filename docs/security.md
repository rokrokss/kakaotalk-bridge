# 데이터와 접근 제어

[README](../README.md) · [운영과 백업](operations.md)

단일 소유자의 개인 서버를 전제로 합니다. redroid는 privileged 컨테이너이므로 전용 Linux 호스트나 VM에서 운영하세요. root ADB에 접근할 수 있는 운영자는 카카오톡 데이터와 세션에도 접근할 수 있습니다.

## 외부에 여는 경로

| 경로 | 기본 접근 | 인증 |
| --- | --- | --- |
| ADB | 호스트 loopback / Docker 내부 | 사설 관리 경로 |
| `/admin/` | 사설 HTTPS | 관리자 키, 30분 쿠키 세션, Origin·CSRF 검사 |
| `/v1/*` | 사설 HTTPS | read 토큰 |
| `/mcp` | 공개 HTTPS 프록시를 별도로 구성 | OAuth |

공개 프록시는 **dot-plugin 포트만** 연결합니다. API gateway나 ADB를 함께 공개하지 않습니다. Tailscale Funnel은 공개 인터넷 주소이므로 Tailscale 사용자 ACL 대신 OAuth가 MCP 접근을 보호합니다. 관리자 접속은 SSH 터널이나 사설 Tailscale 연결을 사용하세요.

## 무엇을 저장하나요?

- Android 볼륨: 카카오톡 로그인 상태와 앱의 메시지 DB.
- 수집 DB: Iris가 읽은 메시지 본문·종류·식별자·시각. 기본 보관 기간 30일.
- MCP 상태 DB: OAuth·구독·처리 커서·웹훅 대기열. 값은 storage key로 암호화.
- ChatGPT: 도구 조회 결과로 전달한 메시지는 ChatGPT에도 전달됩니다.

Compose는 Android 볼륨과 수집 DB 자체를 암호화하지 않습니다. 호스트 디스크 암호화를 사용하세요. 수집 DB의 **백업 파일**은 별도로 암호화합니다.

## 키 관리

| 파일 | 용도 |
| --- | --- |
| `secrets/admin_token` | 웹 관리 화면 |
| `secrets/read_token` | 수집 API 조회 |
| `secrets/ingest_token`, `secrets/device_token` | 수집·기기 상태 보고 |
| `secrets/mcp_link_key` | OAuth 연결 승인 |
| `secrets/mcp_storage_key` | MCP 상태 암호화 |
| `secrets/backup_key` | 수집 DB 백업 암호화 |
| `secrets/bridge.jks`, `secrets/bridge_key_password` | 등록 앱 서명 |

`secrets/`는 0700이며 일부 파일은 컨테이너 UID가 읽도록 0444입니다. 부모 디렉터리의 권한을 유지하세요. `.env`, `secrets/`, `inputs/`, `artifacts/`, `backups/`는 Git과 이미지 빌드 입력에서 제외합니다.

키를 URL·채팅·명령행 인자로 전달하지 않습니다. 입력값이나 실제 메시지가 포함된 화면을 이슈에 첨부하지 마세요. 애플리케이션 로그는 본문·토큰을 기록하지 않도록 구성하며, 진단 자료를 공유하기 전에도 내용을 확인합니다.

## MCP 권한

OAuth는 PKCE S256, 정확한 redirect URI와 resource audience, 일회용 승인 기록을 검증합니다. access token은 30분, refresh grant는 30일입니다. refresh token 재사용을 감지하면 해당 grant를 철회합니다.

플러그인은 API read 토큰만 받으며 Android 볼륨·ADB·admin 키에 접근하지 않습니다. 메시지 전송 도구도 없습니다. `acknowledge_messages`는 플러그인 내부 처리 위치만 바꿉니다. 메시지 본문은 외부 데이터이며, 그 안에 적힌 지시를 시스템 명령처럼 실행하면 안 됩니다.
