# 이전 버전 호환 코드 정리

0.3.0 이하 버전이 남긴 데이터와 설정을 읽거나 옮기던 호환 코드를 정리했습니다. 0.3.1부터 설치한 환경은 다음 버전으로 업데이트할 수 있으며, 0.3.0 이하에서 이 버전으로 올리는 업데이트는 지원하지 않습니다.

## 주요 변경

- **업데이트 지원 범위:** 설치 명령은 0.3.0 이하 설치를 업데이트하지 않고 삭제한 뒤 새로 설치하라고 안내합니다. 카카오톡 로그인, 수집한 메시지, 패스키, 백업은 함께 삭제됩니다. 앞으로는 바로 이전 릴리스에서 올리는 업데이트를 항상 지원합니다.
- **호환 코드 제거:** 예전 위치의 수집 승인 정보·Iris 파일, 이전 Compose 프로젝트 이름, 빠진 인증 키 생성, 예전 인증 방식, Tailscale :8443 경로, 전송 대기열 DB 변환, 예전 형식 메시지와 기록을 읽던 처리를 지웠습니다.
- **로컬 관리자 승인 정책 이름:** 관리 화면을 로컬 비밀번호로 쓰면서 AI 연결을 관리 화면에서 승인하는 설치는 AI 연결을 한 번 다시 승인해야 합니다. 기본 패스키 설치는 영향이 없습니다.

## 설치 방법

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

0.3.0 이하를 쓰고 있다면 먼저 `kakaotalk-bridge cleanup`(0.3.0) 또는 설치 폴더의 `./bridge cleanup`(0.2.2)으로 삭제한 뒤 위 명령을 실행하세요. 그보다 오래된 설치는 Lima VM(Mac)과 설치 폴더를 직접 지우세요. [삭제 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md#uninstall)

## 확인한 범위

자동 테스트와 함께, 카카오톡 계정이 없는 Apple Silicon Mac의 테스트 VM에서 이 버전의 소스로 새로 설치해 다음을 확인했습니다.

- 설치가 끝까지 진행되고 상태 점검이 모두 정상이며 서비스 로그에 오류가 없었습니다.
- 실제 Android에서 수집 승인 정보 쓰기·읽기·삭제, 등록 여부 확인, Iris 중지가 동작했습니다.
- `kakaotalk-bridge` 명령으로 상태 점검, stdio MCP 응답, 삭제(명령 파일 포함)를 확인했습니다.
- 0.3.0 설치에 이 버전으로의 업데이트를 실행하면 아무것도 바꾸지 않고 삭제 후 새로 설치하라는 안내와 함께 멈췄습니다.

릴리스 이미지로 새로 설치하는 과정, 실제 카카오톡 계정의 로그인·수집·전송, Linux 서버와 Intel Mac·WSL에서의 설치는 확인하지 않았습니다.

새로 설치하는 방법과 실행 조건은 [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md)를 참고하세요.

`SHA256SUMS`로 수동 다운로드를 검사할 수 있으며, GitHub CLI의 `gh attestation verify <파일> --repo rokrokss/kakaotalk-bridge`로 출처 증명을 확인할 수 있습니다.
