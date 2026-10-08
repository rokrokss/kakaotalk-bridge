# 개인 OpenAI Secure MCP 터널

[README](../README.md) · [HTTPS/OAuth](dot-plugin.md) · [보안](security.md)

내 OpenAI 계정에서만 MCP를 사용하고 공개 HTTPS 주소를 만들고 싶지 않을 때 선택하세요. 원격 Linux 서버에서도 사용할 수 있고 다른 클라이언트용 HTTPS/OAuth를 함께 운영할 수 있습니다.

```text
내 브라우저 → localhost / SSH / HTTPS 관리 화면 → 패스키 로그인·터널 승인
OpenAI ↔ 서버에서 연결한 터널 클라이언트 → 내부 MCP → 수집 조회 API
다른 MCP 클라이언트 → 공개 HTTPS /mcp → 기존 OAuth (선택 사항)
```

서버의 터널 클라이언트가 OpenAI로 연결하므로 인바운드 접근·Funnel 주소·공유기 포트 개방이 필요하지 않습니다. 관리 화면은 localhost, 원격 서버의 SSH 포워딩 또는 기존 신뢰할 수 있는 HTTPS로 별도 접속합니다. Tailscale은 선택 사항입니다. 터널은 관리 화면·ADB·수집기 비공개 API를 전달하지 않습니다.

<a id="before-setup"></a>
## 설정 전 준비

1. **Tunnels Read + Manage** 권한이 있는 계정으로 [OpenAI 터널 설정](https://platform.openai.com/settings/organization/tunnels)에서 터널을 만드세요.
2. 사용할 ChatGPT 워크스페이스에 연결하고 `tunnel_…` ID를 복사하세요. **Tunnels Read + Use** 권한의 실행용 API 키도 발급받으세요.
3. 두 값을 Bridge 연결 폼에 입력하세요. Bridge가 터널 클라이언트를 시작하면 아래 클라이언트 설정을 완료하세요.

메뉴·터널이 보이지 않으면 관리자에게 조직 권한과 워크스페이스 연결을 확인하세요. [공식 터널 안내](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)를 참고하세요. 조직·워크스페이스가 터널 연결을 지원해야 합니다. 접근 가능한 모든 사용자가 같은 Bridge 권한을 가지므로 본인만 사용하도록 제한하세요. Bridge는 단일 소유자용이며 워크스페이스 사용자별 계정을 구현하지 않습니다.

관리 폼은 키를 가려서 입력받고 제출 후 지우며 저장된 키를 브라우저에 반환하지 않습니다. CLI도 입력을 숨깁니다. 비대화형 설정에서는 키를 명령 인수나 채팅 대신 실행할 컴퓨터의 비공개 파일에 보관하세요. 설치의 보호된 `secrets/`로 복사하고 별도 내부 서비스 인증 정보를 생성합니다. Mac은 비공개 임시 폴더를 거쳐 VM으로 옮깁니다. `.env`나 작업 기록에는 키를 저장하지 않습니다.

<a id="add-a-tunnel-to-an-existing-installation"></a>
## 기존 설치에 터널 추가

기존 설치는 [업데이트](operations.md#update)한 뒤 관리 화면에서 추가하세요. 설치 명령, `kakaotalk-bridge upgrade`, `kakaotalk-bridge up`이 웹 설정 서비스를 준비하며 기존 관리 주소는 유지됩니다.

1. **AI 연결 → AI 연결 설정**을 여세요.
2. **ChatGPT**를 고르고 **개인 터널**(기본 선택)에 ID와 실행용 키를 입력하세요. 같은 ID의 저장된 키를 재사용하려면 비워 두고 교체하려면 새 키를 입력하세요.
3. 접근 동의를 확인하고 **터널 연결**을 누르세요. 서비스 시작·승인·서버 검증을 한국어로 안내합니다. 화면을 나갔다가 돌아와도 작업은 계속됩니다. 웹 절차에는 승인이 포함됩니다.
4. [AI 클라이언트에서 마무리](web-ui.md#finish-in-your-ai-client)에 따라 ChatGPT의 사용자 지정 MCP 플러그인을 만들고 **터널(Tunnel)**, 저장된 ID, **인증 없음(No authentication)** 옵션을 선택하세요. 설치한 뒤 대화에서 선택하세요. 실행용 API 키는 Bridge 설정 폼에만 입력합니다.
5. 수집 상태와 휴대폰에서 보낸 메시지를 요청하세요. 현황에는 승인과 별도로 도구 호출 성공을 기록합니다. 터널이 실행 중이라고 수집까지 검증된 것은 아닙니다.

터널의 **연결 안내**는 언제든 다시 열 수 있습니다. **서버 연결 확인**·새로고침 후에도 ID와 안내를 유지합니다. 마지막 단계의 **설정 변경**으로 수정하고, 실패하면 안내를 읽고 **다시 시도**를 누르세요. 터널 생성과 ChatGPT 추가에는 제공업체 계정이 필요합니다.

<a id="terminal-alternative"></a>
### 터미널에서 설정

`kakaotalk-bridge setup-connection --method openai-tunnel`을 실행하세요. 인증 정보를 입력받고 서비스를 시작한 뒤 관리 화면을 엽니다. 웹 폼과 달리 CLI는 **AI 연결 → 개인 터널 허용**으로 별도 승인해야 합니다. 이후 같은 클라이언트 설정과 검증을 따르세요.

```bash
kakaotalk-bridge tunnel configure \
  --tunnel-id tunnel_REPLACE_WITH_YOUR_32_CHARACTER_ID \
  --api-key-file /private/path/openai-runtime-key
```

예시 ID는 자리 표시자이며 OpenAI가 발급한 소문자 ID로 바꿔야 합니다. 고정된 공식 `ghcr.io/openai/tunnel-client:v0.0.15` 이미지와 내부 서비스 두 개를 실행합니다. 관리 주소·기존 OAuth를 유지합니다. 같은 ID로 반복하면 실행용 키를 갱신하고 승인을 유지합니다. ID를 바꾸면 이전 승인을 취소합니다. 시작 실패 시 이전 설정 복구를 시도하지만 취소된 권한은 되살리지 않으므로 재승인이 필요합니다.

<a id="approval-lifetime"></a>
## 승인 유효 기간

자동 만료 없이 승인되며 설정·키·볼륨을 유지하면 서비스·서버 재시작 후에도 유효합니다. 연결 해제, 터널 ID 변경, 패스키 정책 초기화 시 무효화됩니다. 주기적 브라우저 승인은 필요하지 않습니다. 서비스는 Docker의 `unless-stopped` 정책을 사용하므로 서버 시작 시 Docker도 시작되어야 합니다. 클라이언트는 비공개 MCP 준비 지연을 견디도록 시작 연결을 최대 60초 재시도합니다.

공개 OAuth와 같은 MCP 도구 10개·이벤트 구현을 사용합니다. 기본 승인은 메시지 조회·검색, 요청한 이벤트 구독과 처리 커서 관리입니다. 첫 AI 요청이 성공한 뒤 **AI 연결 → 메시지 전송 허용**을 누르면 내 계정으로 텍스트를 보낼 수 있으며 **메시지 전송 권한 해제**로 되돌릴 수 있습니다. 업데이트나 승인 만료 기한 변경은 기존 전송 권한을 확대하지 않습니다. [전송 안내](sending.md)를 참고하세요. [이벤트 구독](events.md)은 별도 요청해야 합니다. 관리 화면의 **대화 이벤트**에서도 해당 대화를 허용해야 하며 기본값은 꺼짐입니다. 같은 설정이 OAuth와 터널에 적용됩니다.

<a id="fresh-installation-without-external-connections"></a>
## 외부 연결 없이 새로 설치

```bash
kakaotalk-bridge up
```

Tailscale·OpenAI 터널 없이 로컬 관리 화면과 수집을 준비합니다. 나중에 웹 화면이나 `kakaotalk-bridge setup-connection --method openai-tunnel`로 추가하세요. 원격 서버에서는 `--no-browser`와 [SSH 포워딩](quickstart.md#local-and-ssh-admin-access)을 사용하세요.

기존 인증 정보로 비대화형 설정을 하려면 다음을 실행하세요.

```bash
kakaotalk-bridge up --connection openai-tunnel \
  --tunnel-id tunnel_REPLACE_WITH_YOUR_32_CHARACTER_ID \
  --api-key-file /private/path/openai-runtime-key
```

신뢰할 수 있는 비공개 관리 프록시가 있다면 선택적으로 `--admin-url https://admin.example.com`을 지정하고 관리 게이트웨이나 기존 공용 진입점으로 전달하세요. 로컬 관리 구성의 터널은 공개 HTTP MCP 진입점을 시작하지 않습니다. 기존 HTTPS 관리 경로는 유지합니다. 이후 `kakaotalk-bridge up`은 저장된 인증 정보와 관리 주소를 재사용합니다. 공개 HTTPS/OAuth는 **AI 연결 설정**이나 `kakaotalk-bridge setup-connection`으로 별도 추가할 수 있습니다.

<a id="check-revoke-and-restore"></a>
## 점검·취소·복구

**서버 연결 확인**은 서비스를 점검하고 **연결 새로고침**은 승인·활동을 가져옵니다. **마지막 도구 호출 성공**은 과거 기록이며 현재 연결 가능 여부를 뜻하지 않습니다. 목록 조회·실패 호출은 기록하지 않고 이전 버전의 호출은 소급하지 않습니다.

```bash
kakaotalk-bridge tunnel status     # Configured ID and client readiness; no keys
kakaotalk-bridge doctor            # Service health and missing secret files
kakaotalk-bridge tunnel disable    # Revoke grant and stop tunnel services
```

**터널 연결 해제**는 데이터 접근을 즉시 취소하지만 연결 클라이언트는 계속 실행됩니다. 클라이언트 준비 완료가 소유자 승인을 뜻하지는 않습니다. 다시 허용하면 새 권한을 만듭니다. CLI 비활성화는 서비스도 중지하며 기존 공개 OAuth는 유지합니다. 어느 방법도 OpenAI의 터널 자체를 삭제하지 않습니다.

백업에는 실행 설정과 키가 포함됩니다. 복구 시 MCP 권한·구독은 지우므로 유지된 패스키로 로그인하고 터널을 다시 승인하세요. 원하는 이벤트도 재구독하세요. 패스키 복구·정책 변경 후에도 재승인이 필요합니다.

준비되지 않으면 서버의 외부 HTTPS, 실행용 키의 터널 권한과 ID를 확인하세요. 도구 목록은 조회되는데 호출이 403이라면 관리자 승인과 이전 정책의 만료 여부를 확인하세요. 비공개 OAuth 검색 URL은 의도적으로 404를 반환합니다. 비공개 리스너는 공식 클라이언트 시작 점검의 이전 `initialize`와 기존 `server/discover`를 지원합니다. 메타데이터 조회는 내부 인증 정보만 필요하며 도구·이벤트에는 소유자 승인도 필요합니다.

시작 재시도는 연결 거절을 처리하지만 Docker DNS 실패는 처리하지 않습니다. `dot-tunnel`의 DNS 등록 전에 클라이언트가 시작되었다면 서비스가 정상화된 뒤 `docker compose --profile dot --profile tunnel restart openai-tunnel`을 실행하세요.

<a id="validation-scope"></a>
## 검증 범위

자동 테스트는 공개·비공개 인증 분리, 도구 10개, tunnel-client 시작 점검의 MCP 프로토콜 버전, 시간·재시작 후 승인 유지, 취소, 정책 변경, 이벤트·대기 조회·처리 확인, 설정 롤백을 검증합니다. Compose는 비공개 네트워크와 터널 호스트 포트 미공개를 확인합니다. 공식 v0.0.15 소스의 파일 헤더와 시작 점검도 확인했습니다.

실제 OpenAI 터널로 브라우저 승인·취소, 서비스 재시작 후 승인 유지, MCP 시작 지연 복구를 확인했습니다. [검증 내역](implementation.md)

OpenAI 이벤트 전체 전달과 완전한 VM 재부팅은 배포 환경에서 추가 검증해야 합니다. 준비 상태만으로 메시지 조회·이벤트 전달을 보장하지 않습니다.
