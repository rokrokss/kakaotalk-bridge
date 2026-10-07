# ChatGPT 연결

[README](../README.md) · [이벤트](events.md) · [보안](security.md)

`dot-plugin`은 ChatGPT 등 원격 AI 클라이언트를 연결하는 OAuth MCP 서버입니다. 이 문서는 공개 HTTPS 연결을 다룹니다. 서버에서 나가는 연결만 사용하려면 [개인 터널](openai-tunnel.md)을 참고하세요.

<a id="connect"></a>
## 연결

**AI 연결 → AI 연결 설정**에서 **ChatGPT** 또는 **다른 원격 AI 서비스**를 선택하고 기존 HTTPS 주소나 Tailscale을 고르세요. 출처 주소 또는 전체 `/mcp` URL을 입력하면 OAuth를 준비하고 클라이언트 주소를 표시합니다. 기존 관리·패스키 출처는 유지됩니다. 수동 배포는 아래 절차를 따르세요.

1. ChatGPT 웹에서 **플러그인(Plugins) → + → 사용자 지정 MCP 서버 만들기(Create custom MCP server)** 메뉴를 여세요. 이름을 `KakaoTalk Bridge`로 정하고 저장된 `https://<your-host>/mcp`와 **OAuth**를 선택하세요. 등록 방식을 물으면 CIMD를 선택하고 선택적인 고정 클라이언트 인증 정보는 비워 두세요. 안내를 확인하고 생성하세요.
2. 동의 화면을 따르세요. 공용 HTTPS 관리·MCP 구성은 패스키로 인증하고 클라이언트·돌아갈 주소·권한을 확인한 뒤 **연결 허용**을 누릅니다. localhost·비공개 관리 구성은 **AI 연결**에서 8자리 코드를 맞추고 **연결 승인**을 누릅니다. 취소하면 연결되지 않습니다.
3. 플러그인을 설치하고 대화에서 **@KakaoTalk Bridge**를 선택하세요. 수집 상태를 요청한 뒤 휴대폰에서 나에게 구별되는 메시지를 보내 정확한 문구를 찾아보세요. [완료와 문제 해결](web-ui.md#finish-in-your-ai-client)

기존 HTTPS 프록시가 있다면 Tailscale은 필요하지 않습니다. 공용 HTTPS는 연결 키나 별도 관리 화면 방문 없이 패스키로 동의합니다. 출처가 분리되어 있으면 `DOT_APPROVAL_MODE=admin`을 자동 선택하고 비공개 관리 화면에서 코드로 승인합니다. `key`는 명시적으로 선택하는 이전 방식입니다. **AI 연결**에서 연결을 해제할 수 있습니다.

**AI 앱에 추가** 단계 표시는 서비스 설정 결과이며 클라이언트 접근 확인이 아닙니다. 관리 현황과 카드에서 승인과 성공한 도구 호출을 구분합니다. 도구 목록 조회·실패 호출은 기록하지 않으며 시각은 현재 연결 가능 여부를 보장하지 않습니다. 저장된 안내는 점검·새로고침 후에도 유지됩니다. [상태 의미](web-ui.md#what-each-status-proves)

연결만으로 이벤트 구독이나 자동 작업이 생성되지 않습니다. 필요하면 [이벤트](events.md)를 별도로 구독하세요.

<a id="tools"></a>
## 도구

| 도구 | 용도 |
| --- | --- |
| `get_recent_messages` | 발신 시각 기준 최신 메시지, 대화·발신자·시간 필터 |
| `search_messages` | 본문 부분 문자열 검색, 대화·발신자·시간 필터 |
| `list_conversations` | 구분된 대화 목록, 확인 가능한 이름·최근 시각·보관 건수 |
| `get_conversation_context` | 같은 대화의 특정 메시지 앞뒤 문맥 |
| `get_collector_status` | 수집 상태와 현재 연결의 구독·전달 상태 |
| `get_profile` | 연결을 식별하는 불투명 프로필 ID |
| `get_pending_messages` | 소비자의 미처리 메시지 조회 |
| `acknowledge_messages` | 조회한 페이지까지 처리 완료 기록 |
| `send_message` | 현재 계정으로 정확한 대화방에 텍스트 전송 (`kakao.send` 필요) |
| `get_message_send_status` | 요청 UUID로 전송 상태 확인 (`kakao.send` 필요) |

최근·검색 결과는 발신 시각 내림차순이며 불투명 커서를 사용합니다. 대화 필터는 개수 제한 전에 적용합니다. 이름·시간·문맥·호환성은 [메시지 조회](mcp-queries.md)를 참고하세요. 전송에는 별도 `kakao.send` 동의가 필요하며 기존 승인은 자동 확장되지 않습니다. 클라이언트에서 전송 범위를 요청해 다시 연결하세요. [전송 권한·상태·제한](sending.md)을 참고하세요. 로그인·ADB 조작 도구는 없습니다.

<a id="deploy-on-linux"></a>
## Linux 배포

설치된 서버에서 공개 HTTPS 출처를 지정하세요. 끝에 `/`나 `/mcp`를 붙이지 않습니다.

```bash
./bridge connect --url https://bridge.example.com
./bridge passkey-login
```

`connect`는 `.env`의 `DOT_PUBLIC_URL`을 저장하고 `dot-plugin`, `dot-control`, `dot-ingress`를 시작합니다. 필요한 키는 `./bridge install`이 이미 만들었습니다. `passkey-login`은 이 주소의 OAuth 승인 방식을 설정합니다. 관리 화면의 **기존 HTTPS 주소 사용**이나 `./bridge setup-connection --method https --url https://bridge.example.com`도 같은 설정을 합니다.

공개 프록시는 기본 `127.0.0.1:18787`의 `dot-ingress`로 전달합니다. **이 포트만 공개하세요.** API·관리 게이트웨이나 dot-plugin을 직접 공개하지 마세요. 진입점이 내부 경로를 차단하고 MCP 경로의 관리자 쿠키를 제거합니다. 기기·API·제어망이 아닌 전용 관리 진입망에 연결됩니다. 관리 화면을 비공개로 유지하려면 공개 프록시에서 `/admin`, `/admin/*`를 거부하세요. 그렇지 않으면 해당 호스트에 인증된 관리 화면을 제공합니다. dot-plugin은 별도 API 읽기·전송 토큰을 사용하며 Android 볼륨이나 관리자 토큰을 받지 않습니다.

<a id="deploy-in-lima-on-a-mac"></a>
## Mac의 Lima 배포

Mac의 `./bridge`가 만든 VM은 MCP 진입점을 Mac의 `127.0.0.1:18787`(첫 설치 때 사용 중이면 다른 빈 포트)로 전달합니다. Mac에서 실행한 `./bridge expose`는 Mac의 Tailscale Funnel을 이 포트에 연결하고, 관리 화면의 **Tailscale로 HTTPS 주소 만들기**는 VM 안의 Tailscale을 사용합니다. 어느 쪽도 별도 터널이 필요하지 않습니다.

[직접 만든 Lima VM](onboarding.md#manual-deployment)은 이 포트를 전달하지 않으므로 SSH 터널을 사용합니다.

```text
Tailscale Funnel HTTPS :443
  → Mac 127.0.0.1:18788
  → SSH 터널 → Lima 127.0.0.1:18787 → dot-ingress:8786 → dot-plugin:8787
```

`scripts/dot-tunnel.sh`를 실행하거나(VM 이름은 `LIMA_INSTANCE`) `deploy/dev.kakaotalkbridge.dot-tunnel.plist.example`의 절대 경로를 수정해 사용자 LaunchAgent로 설치하세요. 장비별 파일은 Git에서 제외된 `deploy/*.local.plist`에 보관하세요. Mac의 Funnel을 `127.0.0.1:18788`로 연결하고 기존 목적지와 충돌하지 않는지 확인하세요.

Mac 잠자기·종료, Lima·Tailscale 중지는 공개 연결을 끊습니다. Funnel 주소가 공개되어도 `/mcp`는 OAuth 인증을 요구합니다.

<a id="verification-and-troubleshooting"></a>
## 검증과 문제 해결

```bash
./bridge doctor
docker compose --profile dot ps
docker compose logs --tail 30 dot-plugin
tailscale funnel status
uv run python scripts/smoke-dot.py https://your-host.example
```

`docker compose`는 Linux 설치 폴더에서 실행하고, 직접 만든 Lima VM에서는 `./scripts/lima-compose.sh`를 사용하세요. 스모크 스크립트는 명시적 `DOT_APPROVAL_MODE=key`가 필요하며 패스키를 검증하지 않습니다. 일반 설치는 패스키와 명시적 동의를 사용합니다. 키 모드 테스트는 임시 OAuth 권한으로 TLS·인증·도구 목록·실제 최근 메시지 조회를 검증한 뒤 권한을 취소합니다. 본문·키를 출력하거나 이벤트를 구독하지 않습니다.

`/authorize`와 패스키 동의 화면은 오류 코드 대신 한국어 오류 페이지를 표시합니다. OAuth·MCP 프로토콜 응답은 JSON 오류 코드를 유지합니다.

| 오류·상황 | 확인할 내용 |
| --- | --- |
| 다른 주소에서 보낸 요청(`invalid_origin`) | `DOT_PUBLIC_URL`의 스킴·호스트·포트가 브라우저와 일치하고 승인 HTML의 Referrer-Policy가 `same-origin`인지 확인 |
| 승인 요청 만료·처리됨(`invalid_approval`) | 10분이 지났거나 쿠키가 없으면 ChatGPT에서 다시 연결 |
| 서버 소유자 승인 필요(`approval_required`) | 비공개 관리 화면의 **AI 연결**에서 일치하는 코드 승인 |
| 패스키 설정 필요 | 서버에서 `./bridge passkey-login` 실행 후 비공개 관리 호스트에서 등록 |
| 패스키를 찾을 수 없음 | 저장한 기기·비밀번호 관리자와 호스트를 확인하고 시스템 브라우저에서 다시 시작 |
| 코드 불일치·만료 | 연결을 시작한 브라우저 확인. 10분 이상 지났으면 새 요청 시작 |
| 연결 후 도구 오류 | 수집 API 상태·읽기 토큰·수집 승인 확인 |

승인 폼의 Origin·쿠키 검사와 PKCE 검증은 유지하세요. 폼 정책을 바꾸면 실제 브라우저에서 승인과 ChatGPT 복귀까지 확인하세요.

<a id="protocol"></a>
## 프로토콜

MCP `2026-07-28`과 `kakao.read`, `kakao.events` 범위를 제공합니다. DCR·ChatGPT CIMD를 지원하며 CIMD 가져오기에 실패했다고 임의 리디렉션을 허용하지 않습니다. CIMD는 `none`, DCR은 `none`, `client_secret_basic`, `client_secret_post`를 지원합니다. `private_key_jwt`는 지원하지 않습니다.

[OpenAI MCP Events](https://developers.openai.com/plugins/build/mcp-events) · [OAuth 인증](https://developers.openai.com/plugins/build/auth) · [ChatGPT 연결](https://developers.openai.com/plugins/build/app-quickstart#connect-your-mcp-server-in-chatgpt)
