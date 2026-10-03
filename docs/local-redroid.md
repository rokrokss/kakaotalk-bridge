# Mac에서 실제 redroid 테스트하기

Docker Desktop의 Linux 커널 검사에서 `# CONFIG_ANDROID_BINDER_IPC is not set`을 확인했다. 이 커널에서는 redroid를 실행할 수 없으므로 Mac의 Lima/VZ 안에 Ubuntu 24.04 arm64를 준비한다. 가상머신 안에서는 기존 `compose.yaml`과 `deploy/compose.lima.yaml`을 함께 사용해 redroid, API, admin, device-agent, iris-collector, gateway를 실행한다. 물리 보조 태블릿은 필요하지 않다.

Apple Silicon VM에서는 기본 이미지의 32비트 vendor 프로그램이 `Exec format error`로 실패했다. 로컬 VM용 override는 공식 `14.0.0_64only-latest` 이미지를 digest로 고정하며, Ubuntu binderfs의 세 장치를 Android의 `/dev/binder`, `/dev/hwbinder`, `/dev/vndbinder`에 연결한다. `kakaocollector-binder.service`가 VM 재부팅 시 장치를 먼저 준비한다. 서버용 기본 Compose 설정은 유지한다.

Binder 장치는 단순한 `devices:` 매핑으로 복제하면 `ENXIO`가 발생하므로 binderfs inode를 그대로 bind mount한다. Docker 재시작 시 고정 gateway IP와 자동 배정 IP가 충돌하지 않도록 기본 네트워크의 `DEVICE_IP_RANGE`는 `172.29.87.128/25`로 제한한다. 기존 네트워크에 적용할 때는 `down` 후 `up -d --no-build`로 네트워크만 재생성하며 `--volumes`는 사용하지 않는다.

## 구성

- VM 이름: `kakaotalk-test`, 6 CPU, 8 GiB RAM, 최대 40 GiB 가상 디스크
- VM 정의: `deploy/lima.yaml`
- VM 내부 배포 경로: `/srv/kakaotalk-collector`
- 실제 admin 접속: `https://localhost:18443/admin/`
- 관리자 키: 이 프로젝트의 `secrets/admin_token`과 동일한 값을 VM에 복사한다. 데모 키를 사용하지 않는다.
- Mac의 홈 디렉터리는 VM에 마운트하지 않는다. 배포 파일과 시크릿은 VM 디스크로 복사한다.
- Docker Desktop과 별도의 Docker Engine이다. Mac의 기본 `docker ps`에는 이 VM의 컨테이너가 나타나지 않는다.
- 이전 `19443` 데모는 실제 계정 테스트 경로가 아니다.

## 운영 명령

프로젝트 디렉터리에서 실행한다.

```bash
# VM 최초 생성 (Homebrew lima 필요)
limactl start --name=kakaotalk-test --tty=false deploy/lima.yaml

# 기존 VM 시작
limactl start kakaotalk-test

# 실제 컨테이너 상태 / Android 부팅·설치 상태
./scripts/lima-compose.sh ps
./scripts/lima-compose.sh exec -T admin python -m device.cli probe

# 설치된 이미지로 전체 컨테이너 실행
./scripts/lima-compose.sh up -d --no-build

# VM 종료: 컨테이너와 로그인 상태 볼륨을 삭제하지 않음
limactl stop kakaotalk-test
```

`down -v`와 `limactl delete`는 계정/메시지 볼륨을 삭제하므로 일반 종료에 사용하지 않는다. VM을 껐다 켠 후에는 위의 `up -d --no-build`로 redroid까지 다시 시작한다.

## 핸드폰에서 카카오톡 설치 파일 가져오기

안드로이드폰을 USB로 연결하고 USB 디버깅과 이 컴퓨터 연결을 허용한 뒤 실행한다.

```bash
uv run python scripts/import-phone-apks.py
```

이 도구는 `adb -d shell pm path com.kakao.talk`와 `adb -d pull`만 사용한다. 한 대의 USB 폰에 설치된 APK/split APK 파일을 `inputs/kakao/`에 복사하며 폰의 앱 데이터, 로그인 설정, 실행 상태를 바꾸지 않는다. 기존 APK가 있으면 덮어쓰지 않고 중단한다. Android 설정의 디버깅 허용 자체는 사용자가 수행한다.

가져온 파일을 VM으로 전달한다.

```bash
set -o pipefail
COPYFILE_DISABLE=1 tar --no-xattrs -czf - inputs/kakao |
  limactl shell --workdir=/ kakaotalk-test sudo tar --no-same-owner -xzf - -C /srv/kakaotalk-collector
```

`--no-same-owner`는 Mac의 사용자 ID 대신 VM의 root 소유로 설치 파일을 만든다. admin 컨테이너는 root로 실행하되 모든 capability를 제거하므로, Mac 사용자 소유의 0600 파일은 읽을 수 없다. 파일 권한을 공개하지 않고 소유자를 맞춘다.

이후 실제 admin에서 **초기 설치 → 카카오톡 열기**를 실행한다. 등록 앱과 Iris도 함께 배치한다. 카카오톡 화면에서 **다른 기기와 함께 사용**을 선택한 다음 **보조 로그인 옵션 검사**를 통과한 뒤 로그인한다. 해당 옵션이 없거나 주 기기 이전을 요구하면 진행하지 않는다.

핸드폰의 기존 세션과 redroid 로그인을 직접 확인한 후에만 양쪽 확인을 기록하고 Iris를 활성화한다. admin은 핸드폰 원격 세션을 자동 검증하지 않는다. 로그인 해제 여부의 실제 판정은 폰에서 해야 한다.

## 이미지 전달

Mac에서 빌드한 arm64 런타임 이미지를 전달한다. 별도의 이미지 레지스트리는 사용하지 않는다.

```bash
set -o pipefail
docker save kakaotalk-collector/device:0.1.0 kakaotalk-collector/server:0.1.0 |
  gzip -1 > artifacts/linux-arm64-images.tar.gz
limactl shell --workdir=/ kakaotalk-test sudo docker load < artifacts/linux-arm64-images.tar.gz
```

VM에는 `compose.yaml`, `docker/`, `.env`, `secrets/`, `inputs/` 등 배포 파일이 먼저 복사되어 있어야 한다. 기존 배포의 서명 키와 토큰을 유지한다. 이미 빌드한 런타임을 사용하는 구성으로, VM에서 Android SDK 빌드를 다시 수행할 필요가 없다.

## 실행 확인 (2026-10-04)

- VM: Ubuntu 24.04, `Linux 6.8.0-142-generic`, Docker `linux/aarch64`.
- `scripts/preflight.sh` (VM 안): `PASS: Linux, Docker Compose and binder presence.`
- 실제 redroid: `sys.boot_completed=1`, Android `14`, `ro.product.model=SM-T970`, `ro.build.characteristics=tablet`, `arm64-v8a`, `1200x1920`, density `240`.
- `./scripts/lima-compose.sh exec -T admin python -m device.cli probe`: `state=android_ready`, `kakao_installed=true`, `bridge_installed=true`, `android_version=14`.
- 실제 admin HTTPS 인증과 화면 조회: `PASS: real redroid screenshot through authenticated Docker admin: 1200 x 1920`. 인증서 검증을 유지했으며 실제 키 값은 출력하지 않았다. `artifacts/redroid-real-screen.png`는 데모가 아닌 Android 홈 화면이다.
- API/admin/gateway/device-agent/iris-collector 컨테이너도 실행했다. **iris-collector 실행과 Android 안의 Iris 읽기 프로세스 실행은 다르다.** 카카오톡/등록 앱 설치와 양쪽 로그인 확인 전에는 수집 승인이 잠겨 있으며 Iris DB 읽기는 시작되지 않는다.
- USB 디버깅을 허용한 폰에서 `uv run python scripts/import-phone-apks.py`: `PASS: copied 4 KakaoTalk APK(s); no app data or login settings changed`. APK만 복사해 redroid에 설치했다. base APK의 SHA256은 `9affda8567c9cd1be4deebda2ce08c43253ddf0bb70869a48dbbf946d04e847b`이다.
- `./scripts/lima-compose.sh exec -T admin python -m device.cli login-check`: `PASS: tablet configuration and selected secondary-login checkbox observed. No login was submitted.` 실제 카카오톡 화면에서 **다른 기기와 함께 사용**이 기본 선택되어 있었다. `artifacts/redroid-kakao-screen.png`에 로그인 전 화면을 저장했다.
- 실제 `Android().session_status()`: `screen.state=login_required`, `secondary_option=selected`, `collection_approval=locked`, `precheck.state=valid`, `phone.state=unknown`, `phone.automatic=false`. 계정 로그인 성공과 핸드폰 세션 유지는 사용자가 로그인 후 확인해야 한다. 사전 검사 유효시간은 30분이다.
- 등록 앱과 Iris APK 배치 및 웹 키보드 설정 완료. 실제 카카오톡 이메일 칸에 임시 문자열을 입력해 웹 키보드를 검증하고 제거했다. 로그인 버튼은 누르지 않았다. 양쪽 세션 확인 전까지 Iris 읽기는 잠겨 있다.
- Android 14의 진단 출력에 `userId=`가 없어 등록이 실패한 문제를 `pm list packages --user 0 -U`의 정확한 패키지/UID 조회로 수정했다. `uv run pytest -q`: `71 passed, 1 warning in 2.75s`. `uv run ruff check device webui tests scripts/import-phone-apks.py`: `All checks passed!`. arm64 device 이미지를 다시 빌드해 VM에 로드하고 admin/device-agent/iris-collector를 재생성했다.
- VM 재부팅 후 `kakaocollector-binder.service`: `active`, Android 부팅 완료와 `persist.sys.locale=ko-KR` 유지 확인.
- Docker 데몬 재시작 후 `./scripts/lima-compose.sh up -d --no-build`: exit 0. 6개 서비스가 `running`, API가 `healthy`, gateway가 `172.29.87.3`을 유지하고 나머지 서비스는 `172.29.87.128/25` 범위에 배정되었다.
- 재시작 후 HTTPS 재검사: `PASS: Docker restart preserves real admin HTTPS access`.

## 실제 로그인 및 Iris 활성화 확인 (2026-10-04)

- 사용자가 redroid 로그인 성공과 기존 Android 폰의 로그인 유지를 직접 확인한 뒤 admin의 **확인하고 Iris 수집 활성화**를 눌렀다. 폰 확인은 사용자 진술이며 자동 검증으로 표시하지 않는다.
- `./scripts/lima-compose.sh exec -T admin`에서 `Android().session_status()` 조회 결과: `collection_approval=approved`, `phone.state=operator_confirmed`, `tablet.state=operator_confirmed`. 승인 시각은 UTC `2026-10-03T23:14:06`이다.
- 같은 컨테이너의 `collector_status()`: `state=collecting_partial`, `warnings=[]`, `secondary_login_operator_confirmed=true`. `./scripts/lima-compose.sh logs --tail 30 iris-collector`에 `{"iris": "polling", "committed_rows": 50}`가 반복됐다.
- API의 `/data/collector.db`를 SQLite `mode=ro`로 열어 `SELECT count(*), min(received_at), max(received_at) FROM observations WHERE json_extract(body,'$.source')='iris_db'`를 실행했다. 첫 점검에서 실제 Iris 행 `1128`건, 마지막 저장 UTC `2026-10-03T23:15:28.522129`를 확인했다. 메시지 본문은 출력하지 않았다. 전체 과거 대화의 복원·누락 없음까지 확인한 것은 아니다.
- 활성화 직후 Bridge 설정 화면이 열린 원인은 `confirm_secondary`가 설정 저장 후 SetupActivity도 실행했기 때문이다. Iris 모드에서는 설정 파일만 저장하도록 변경해 카카오톡 화면을 유지한다. 승인 후 사전 검사 기록 삭제와 양쪽 확인 저장은 유지한다.
- `uv run pytest -q`: `72 passed, 1 warning in 4.78s`. `uv run ruff check device/cli.py tests/test_session_status.py`: `All checks passed!`. 수정한 arm64 이미지를 배포하며 admin만 재시작한다. redroid와 Iris 수집 프로세스는 계속 실행한다.
