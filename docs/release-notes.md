# 보관 기간 무제한과 첨부 읽기

수집한 메시지를 기본으로 계속 보관하고, AI가 메시지의 사진·파일·링크 같은 첨부를 요청할 때 읽을 수 있게 했습니다. 0.3.1·0.3.2·0.3.3에서 바로 업데이트할 수 있습니다.

## 주요 변경

- **메시지를 기본으로 계속 보관:** 지금까지는 30일이 지난 메시지를 매시간 지웠습니다. 이제 `RETENTION_DAYS`의 기본값이 `0`이며, `0`이면 아무것도 지우지 않습니다. 설치 프로그램은 이 값을 `.env`에 쓰지 않으므로 **기존 설치도 업데이트하면 무제한 보관으로 바뀌고, 서버의 디스크 사용량이 계속 늘어납니다.** 이미 지워진 메시지는 돌아오지 않습니다. 30일 보관을 유지하려면 `.env`에 `RETENTION_DAYS=30`을 추가한 뒤 `kakaotalk-bridge start`를 실행하세요. `.env`는 Linux에서는 설치 폴더에, Mac에서는 VM 안의 `/srv/kakaotalk-bridge/.env`(`limactl shell kakaotalk-bridge`로 접속)에 있습니다. 음수는 허용하지 않으며 서버가 시작되지 않습니다.
- **첨부 읽기 도구 3개:** `get_message_attachment`는 한 메시지의 첨부 정보(사진 크기, 파일 이름, 위치, 링크 미리보기, 인용 원문 등)를, `get_message_image`는 사진 썸네일이나 원본을, `get_message_file`은 2MiB 이하 파일을 돌려줍니다. 요청할 때 태블릿의 카카오톡 DB에서 그 메시지 한 건만 복호화하며 서버에 저장하지 않습니다. 이미지는 2MiB를 넘으면 JPEG로 줄입니다. 원본 영상과 음성 파일은 받지 않습니다.
- **카카오 CDN에서만 받기:** 이미지와 파일은 태블릿 쪽 수집기가 카카오 CDN 주소(`kakaocdn.net` 등)에서 HTTPS로만 받아 전달합니다. 조회 서버는 여전히 외부로 연결하지 않습니다. 만료된 주소는 `image_expired`로 알려 줍니다.
- **목록에 첨부 표시:** 메시지 조회 결과에 `log_id`, `attachment_type`, `has_attachment`가 추가되었습니다. 이 값은 이미 저장된 종류 코드로만 계산하며 URL은 넣지 않습니다.
- **Iris 수집기 갱신:** 수집기 빌드가 `iris-ee1dc978-collector-v7`로 바뀝니다. 업데이트 뒤 수집기가 태블릿의 Iris를 자동으로 교체하며, 카카오톡 재설치나 다시 로그인할 필요는 없습니다.

첨부 읽기는 기존 읽기 권한(`kakao.read`)으로 동작합니다. 새 도구가 보이지 않으면 AI 클라이언트의 도구 목록을 새로고침하세요.

## 업데이트 방법

0.3.1·0.3.2·0.3.3을 쓰고 있다면 `kakaotalk-bridge upgrade`를 실행하거나 설치 명령을 다시 실행하세요. 저장된 메시지·설정·카카오톡 로그인은 그대로 유지됩니다.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

0.3.0 이하를 쓰고 있다면 0.3.1과 마찬가지로 삭제한 뒤 새로 설치해야 합니다. [삭제 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md#uninstall)

## 확인한 범위

자동 테스트로 첨부 종류별 정보 정리, 크기 제한, CDN 주소 검사, 보관 기간 `0`에서 정리하지 않는 동작을 확인했습니다. 함께, 카카오톡 계정을 연결하지 않은 Apple Silicon Mac의 테스트 VM에서 다음을 확인했습니다.

- 0.3.3을 그때의 설치 명령으로 설치한 뒤, 설치 명령을 다시 실행해 이 버전의 시험판(v0.4.0-rc.1)으로 업데이트했습니다. 인증 키, 볼륨, 이미지 주소 외의 `.env`는 그대로였고, 이미지 주소는 시험판의 `release.json`과 같았습니다. 상태 점검이 모두 정상이었습니다.
- `.env`에 `RETENTION_DAYS`가 없는 설치에서 조회 서버의 보관 기간이 30일에서 `0`(무제한)으로 바뀌었습니다.
- 업데이트한 조회 서버가 첨부 조회 경로에 응답했습니다.
- 다시 실행하면 업데이트하지 않았고 VM도 다시 시작하지 않았습니다.

로그인된 카카오톡 기기에서 실제 첨부를 복호화하고 받는 과정, 실행 중인 Iris가 새 수집기 빌드로 교체되는 과정은 확인하지 않았습니다. 테스트 VM은 카카오톡을 등록하기 전이라 Iris가 실행되지 않았습니다. `kakaotalk-bridge upgrade` 명령으로의 업데이트와 Linux 설치에서의 업데이트도 확인하지 않았습니다.

새로 설치하는 방법과 실행 조건은 [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md)를 참고하세요.

`SHA256SUMS`로 수동 다운로드를 검사할 수 있으며, GitHub CLI의 `gh attestation verify <파일> --repo rokrokss/kakaotalk-bridge`로 출처 증명을 확인할 수 있습니다.
