# 개발

[README](../README.md) · [구조](design.md) · [검증 범위](implementation.md)

## 로컬 검사

```bash
uv sync --frozen --python 3.12
uv run pytest -q
uv run ruff check .
node --check webui/static/app.js
docker compose --profile dot config --quiet
```

Python 의존성은 `uv.lock`과 해시를 포함한 `requirements.lock`으로 고정합니다. 의존성을 변경했다면 다음으로 동기화합니다.

```bash
uv export --frozen --no-dev --no-emit-project --output-file requirements.lock
```

## 코드 위치

| 경로 | 역할 |
| --- | --- |
| `device/` | redroid 설정, 로그인 검사, Iris 수집기 |
| `iris/` | Iris의 읽기 전용 진입점과 라이선스 고지 |
| `android/` | 등록 앱과 웹 입력기. 이전 알림 수집 코드 포함 |
| `server/` | 저장, API, stdio MCP, 백업 |
| `webui/` | 관리자 인증, 기기 조작, 정적 웹 화면 |
| `dot_plugin/` | OAuth, 원격 MCP, 선택적 Events |
| `tests/` | 합성 데이터 테스트와 브라우저용 가짜 기기 |
| `deploy/`, `scripts/` | Lima, supervisor, 설치·진단·백업 도구 |

## 웹 화면 미리보기

ADB와 실제 계정에 연결되지 않는 fixture를 사용합니다. 로컬에서 신뢰하는 localhost TLS 인증서가 필요합니다. 기존 설치의 인증서가 신뢰되어 있다면:

```bash
uv run uvicorn tests.webui_preview:create_preview --factory \
  --host 127.0.0.1 --port 19443 \
  --ssl-certfile secrets/tls_cert.pem --ssl-keyfile secrets/tls_key.pem \
  --no-access-log
```

`https://localhost:19443/admin/`에 접속합니다. 키는 `preview-only-key-` 뒤에 숫자 `0` 32개입니다. `/test/calls`에는 가짜 기기에 보낸 동작 이름만 표시합니다. 설치·로그인 검사·양쪽 확인·핸드폰 보고를 이 환경에서 시험하세요. 운영 화면에서는 설치나 승인 초기화 동작으로 UI를 검증하지 않습니다.

## 컨테이너 검사

```bash
docker compose build api device-agent
./scripts/smoke.sh
```

smoke는 독립적인 `kakaocollector-smoke-PID` 프로젝트에 합성 Iris 행을 넣어 HTTPS 인증, 재전송, 영속성, 백업, stdio MCP를 확인합니다. 테스트 프로젝트의 볼륨만 제거하며 실제 redroid나 계정은 사용하지 않습니다. 호스트에 uv 또는 Python 3.12와 의존성이 필요합니다. 기본 테스트 subnet은 `172.29.88.0/24`, 포트는 `18443`이므로 기존 배포와 충돌하지 않도록 확인하세요.

Docker 기반 이미지는 digest로 고정합니다. device 빌드는 Bridge의 `assembleRelease`, `lintRelease`, `apksigner verify`와 Iris의 `assembleRelease`를 실행합니다.

## 변경 원칙

UI에는 상태와 다음 행동에 필요한 설명을 둡니다. 설치·운영 절차는 해당 문서에, 프로토콜과 저장 형식은 구조·API 문서에 기록합니다. 진행 상황이나 실패 후 재시도 과정을 README에 덧붙이지 않습니다.

로그인·인증을 수정했다면 단위 테스트 외에 실제 브라우저의 폼 제출도 확인합니다. HTTP 클라이언트가 직접 지정한 Origin은 브라우저 동작의 대체 검증이 아닙니다. 테스트나 스크린샷에 토큰·실제 대화·계정 정보를 남기지 않습니다.

OAuth 승인 화면도 실제 계정 없이 확인할 수 있습니다.

```bash
uv run uvicorn tests.dot_preview:create_preview --factory \
  --host 127.0.0.1 --port 20443 \
  --ssl-certfile secrets/tls_cert.pem --ssl-keyfile secrets/tls_key.pem \
  --no-access-log
```

`https://localhost:20443/test/start`에서 같은 미리보기 키를 입력하면 로컬 콜백으로 돌아옵니다. 상태는 임시 디렉터리에 저장되며 수집 API와 이벤트 worker는 연결하지 않습니다.
