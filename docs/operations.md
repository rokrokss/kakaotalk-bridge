# 운영과 복구

[README](../README.md) · [보안](security.md)

아래는 Linux 호스트 명령입니다. Mac의 실제 컨테이너는 Lima 안에 있으므로 `docker compose` 대신 `./scripts/lima-compose.sh`를 사용합니다.

## 상태 확인

```bash
docker compose --profile dot ps
./scripts/status.sh
docker compose logs --tail 30 iris-collector
```

`collecting_partial`은 최근 Iris DB 접근과 보조 로그인 승인이 유효하다는 뜻입니다. 전체 대화의 누락 여부나 핸드폰 세션을 자동으로 확인한 결과는 아닙니다.

| 증상 | 확인할 곳 |
| --- | --- |
| Android 화면 연결 안 됨 | redroid 부팅 상태, 호스트 binder 장치 |
| 수집 승인 잠김 | 관리 화면의 로그인 검사와 양쪽 확인 |
| 앱 업데이트 후 수집 멈춤 | versionCode 변경. 새 로그인 확인 필요 |
| 복호화·JSON 오류 | Iris 로그. 잘못된 행을 건너뛰지 않고 중단함 |
| DB 교체·ID 역행 | Android 복원 또는 DB 재생성 여부. 원인 확인 후 새 epoch 등록 |
| ChatGPT 연결 실패 | dot-plugin 상태, 공개 HTTPS, OAuth 연결 키. [연결 안내](dot-plugin.md) |

Iris는 기본 3초마다 최대 50행씩 읽고, 밀린 행이 있으면 계속 조회합니다. 최근 수신 지연은 카카오톡과 redroid의 연결 상태에 따라 달라집니다.

## 종료와 재시작

```bash
docker compose down
docker compose up -d --no-build
```

`down`은 볼륨을 보존합니다. **`down -v`는 로그인 상태와 DB를 삭제합니다.** 일상적인 종료에 사용하지 마세요.

redroid는 반복 장애를 피하려고 자동 재시작을 끈 상태입니다. 필요하면 `docker compose start redroid`로 시작합니다. 나머지 상시 서비스는 `unless-stopped` 정책을 사용합니다. Linux에서 자동 복구가 필요하면 `deploy/kakaocollector-supervisor.service.example`의 경로를 맞춰 설치합니다. supervisor는 redroid 재시작을 30분 안에 3회로 제한합니다.

## 저장 위치

| 볼륨 | 내용 |
| --- | --- |
| `android-data` | 카카오톡 세션·로컬 DB, 등록 앱 데이터 |
| `collector-data` | 수집 메시지, 서버 커서 |
| `device-state` | 등록 epoch, ADB 키 |
| `iris-state` | Iris 수집기의 ADB 키 |
| `dot-state` | OAuth, 구독, 처리 완료 커서, 웹훅 대기열 |

서버는 매시간 30일 초과 관찰 기록을 정리합니다. 기간은 `RETENTION_DAYS`로 바꿉니다. 재전송 중복 제거도 이 보관 범위에 적용됩니다. Android 자체 DB, 이전 알림 quarantine, 백업 파일은 이 정리 대상이 아닙니다. 컨테이너 로그는 각 10MB × 3개로 제한합니다.

## 수집 DB 백업

```bash
./scripts/backup.sh
```

SQLite 온라인 backup API로 일관된 사본을 만들고 AES-256-GCM으로 암호화합니다. `secrets/backup_key`는 백업 파일과 별도로 보관하세요. 키를 잃으면 복원할 수 없습니다. 백업 자동 삭제와 원격 복제는 직접 구성해야 합니다.

복원할 때는 API를 멈춥니다.

```bash
docker compose stop api
./scripts/restore.sh backups/collector-TIMESTAMP.kcb
docker compose start api
./scripts/status.sh
```

복원은 인증 태그·DB 무결성·schema를 검사합니다. `cursor_epoch`가 바뀌므로 API 소비자는 기존 페이지 커서를 초기화해야 합니다. Iris는 복원된 서버 커서부터 다시 읽습니다.

백업 스크립트는 실행한 호스트의 Docker Engine을 사용합니다. Lima 배포에서는 VM의 `/srv/kakaotalk-collector` 안에서 실행합니다.

```bash
limactl shell --workdir=/srv/kakaotalk-collector kakaotalk-test sudo ./scripts/backup.sh
```

## Android와 MCP 상태 백업

Android는 redroid를 정지한 뒤 `android-data`와 `device-state`를 함께 암호화된 호스트 스냅샷으로 보관합니다. 원본과 복원본을 같은 계정으로 동시에 켜지 않습니다. 복원 후 새 등록 epoch를 만듭니다.

```bash
docker compose --profile setup run --rm bootstrap bootstrap --rotate-epoch
```

이 작업 후에는 보조 로그인 재확인이 필요합니다. Iris가 새 epoch에서 남아 있는 DB 행을 다시 읽으므로 이전 기록과 중복될 수 있습니다.

`dot-state`는 수집 DB 백업에 포함되지 않습니다. dot-plugin을 정지하고 볼륨을 복사하거나 SQLite 온라인 백업을 사용합니다. `secrets/mcp_storage_key`도 별도로 보관하세요. 실행 중인 DB 파일 하나만 복사하면 WAL의 데이터가 빠질 수 있습니다.

## 인증서 갱신

기본 TLS 인증서는 365일입니다. 갱신할 때 같은 gateway IP를 SAN에 포함하고 gateway를 재시작합니다. 등록 앱의 신뢰 인증서도 bootstrap으로 갱신해야 하므로 로그인 재확인 시간을 잡아 진행하세요. Bridge 서명 키를 바꾸면 앱 업데이트가 실패합니다.
