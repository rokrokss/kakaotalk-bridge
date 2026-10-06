# 계정 기반 수집 승인과 자동 Iris 업데이트

수집 승인을 태블릿의 카카오톡 계정에 묶고, 업데이트할 때 Iris를 자동으로 교체합니다. 수집은 더 빨라졌고 읽지 못한 행이 있어도 멈추지 않습니다.

## 주요 변경

- **계정 기반 승인과 자동 로그인 감지:** 수집 승인은 태블릿에 로그인한 카카오톡 계정에 묶입니다. 관리 화면의 **카카오톡 로그인**은 로그인 화면에서 **다른 기기와 함께 사용** 선택 여부를 보여 주고 태블릿 로그인을 자동으로 감지합니다. 휴대폰 로그인을 확인하고 **메시지 수집 시작**을 누르면 됩니다. 로그인 전 점검 버튼과 30분 제한은 없어졌습니다. 카카오톡이 업데이트되어도 같은 계정이면 계속 수집하며, 다른 계정이 확인되거나 Android 빌드가 바뀌거나 휴대폰 로그아웃을 기록하면 멈춥니다.
- **Iris 자동 업데이트:** 수집기가 Iris를 시작할 때 기기의 Iris를 이미지의 빌드와 SHA-256으로 비교하고, 다르면 검증된 업로드로 교체합니다. 업데이트와 되돌리기에 별도 이전 작업이 필요하지 않으며 `./bridge update`도 Iris 변경을 거부하지 않습니다.
- **더 빠르고 멈추지 않는 수집:** 한 번에 최대 200행(약 2 MB)을 읽고 행 단위가 아닌 묶음으로 저장합니다. 기기 확인은 한 번의 ADB 호출로 페이지마다 수행합니다. Iris가 읽지 못하거나 서버가 저장하지 못한 행은 본문 없이 건너뛰기 기록으로 남기고 수집을 계속합니다. 건너뛴 수는 `/v1/status`의 `coverage.skipped_rows`에 표시합니다.
- **보낸 메시지 없이 본인 식별:** 태블릿 카카오톡의 로그인 계정 정보로 본인을 확인하므로 직접 보낸 메시지가 없어도 본인을 **나**, 나와의 채팅을 **나와의 채팅**으로 표시합니다. 확인 근거는 `/v1/status`의 `identity_metadata.self_identity_source`에 표시합니다.
- **한국어 설치 출력과 비공개 로그:** `./bridge up`과 설치 명령은 `[1/4]`부터 `[4/4]`까지의 단계와 짧은 진행 상황을 표시합니다. 도구 출력은 비공개 로그에 기록하고, 실패하면 한국어로 원인과 로그 경로를 알립니다. 원문 출력은 `--verbose`로 볼 수 있으며 `./bridge --help`도 한국어입니다.
- **Linux 권한 처리:** Linux에서 `./bridge`는 sudo로 다시 실행되고(`./bridge mcp` 제외) 설치 명령은 root로 설치합니다. 코드와 `.env`(비밀값 없음)는 읽을 수 있게 두고 `secrets/`는 비공개로 유지하므로 `docker` 그룹 계정이 SSH로 `./bridge mcp`를 사용할 수 있습니다.
- **제거된 기능:** Android 알림 수집기와 그 업로드 경로, HTTP `/v1/search`, `/v1/conversations`, `/v1/messages`의 `conversation_ref` 필터를 제거했습니다. 메시지 조회에는 `/v2/*`와 MCP 도구를 사용하세요. 기기 CLI의 `login-check`, `confirm-secondary`, `iris-upgrade`, `prepare`, `configure`는 `approve`로 대체했고, `scripts/preflight.sh`, `status.sh`, `backup.sh`, `restore.sh`, `init-dot-secrets.py`는 `./bridge doctor`, `backup`, `restore`, `install`로 대체했습니다.
- **`doctor` 인증서 확인:** `./bridge doctor`는 한국어 요약(`--json`은 JSON)을 출력하며, 비공개 HTTPS 인증서가 30일 안에 만료되면 경고하고 만료되면 확인 필요로 표시합니다.
- **MIT 라이선스:** 저장소는 MIT 라이선스로 제공합니다. 빌드한 Iris APK에는 GPL-3.0이 적용됩니다. [라이선스 및 소스 배포 조건](https://github.com/rokrokss/kakaotalk-bridge/blob/main/iris/NOTICE.md)

그 밖에 OAuth 브라우저 화면(`/authorize`, 패스키 동의)의 오류를 한국어 페이지로 표시하고 기기 오류도 한국어로 안내합니다. 게이트웨이는 Android 네트워크에 연결하지 않으며 `GATEWAY_IP`는 쓰지 않습니다. 태블릿 쪽 파일은 root 전용 `/data/kakaotalk-bridge/`에 두며 등록 정보에는 수집 토큰·게이트웨이 주소·인증서가 들어가지 않습니다. 키보드 앱은 웹 텍스트 입력만 제공하고 알림 접근 권한이 없으며, 기기의 앱이 이미지의 빌드와 다르면 자동으로 다시 설치합니다. 새 설치의 Compose 프로젝트 이름은 `kakaotalk-bridge`입니다.

## 업데이트 방법

처음 설치할 때와 같은 명령을 다시 실행하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

최신 릴리스를 내려받아 검증하고 암호화 백업을 만든 뒤 업데이트하고 관리 화면을 엽니다. 설정, Android 데이터, 카카오톡 로그인, 수집 승인은 유지됩니다. 0.1.0의 수집 승인은 태블릿에 로그인된 계정으로 자동으로 이어지고(그때 계정을 읽을 수 없으면 다시 승인해야 합니다) Iris도 자동으로 교체됩니다. 기존 설치의 Compose 프로젝트 이름은 바뀌지 않으므로 데이터도 그대로 사용합니다.

0.1.0을 설치한 Linux 서버는 `./bridge up`이 아니라 이 설치 명령으로 업데이트하세요. 그 밖의 릴리스 설치는 설치 폴더에서 `./bridge upgrade`를 실행해도 되며, Git 작업 폴더는 `git pull` 후 `./bridge update --source`를 사용합니다. [업데이트 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md#update)

## 확인되지 않은 부분

이번 변경은 자동 테스트와 카카오톡 계정이 없는 테스트 VM의 합성 데이터로 확인했습니다. 실제 계정에서는 카카오톡이 저장한 로그인 계정 ID가 본인 사용자 ID와 같은지만 값을 출력하지 않고 읽기 전용으로 확인했습니다. 다음은 아직 확인하지 않았습니다.

- 실제로 로그인된 카카오톡 DB에서 새 Iris의 수집
- 로그아웃이나 계정 전환 후 카카오톡이 남기는 정보. 계정 확인은 변경 감지용이며 보안 경계가 아닙니다.
- 실제 기기에서 휴대폰 로그아웃을 기록했을 때의 수집 중지
- 새 출력을 포함한 Mac 설치 전체 과정
- Windows·WSL2 실행

새로 설치하는 방법과 실행 조건은 [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md)를 참고하세요.

`SHA256SUMS`로 수동 다운로드를 검사할 수 있으며, GitHub CLI의 `gh attestation verify <파일> --repo rokrokss/kakaotalk-bridge`로 출처 증명을 확인할 수 있습니다.
