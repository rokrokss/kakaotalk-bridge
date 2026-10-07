# 밝은 관리 화면

관리 화면이 운영체제의 다크 모드 설정과 관계없이 항상 밝은 화면으로 표시됩니다.

## 주요 변경

- **관리 화면 라이트 모드:** 운영체제가 다크 모드여도 관리 화면과 입력창·스크롤바를 밝은 색으로 표시합니다. AI 연결 동의와 패스키 로그인 화면은 계속 운영체제 설정을 따릅니다.
- **설치·운영 안내 정리:** [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md), [운영](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md), [고급 설치](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/onboarding.md) 문서를 실행할 명령과 단계부터 보이도록 다시 썼습니다.

0.1.0에서 바로 업데이트한다면 [0.2.0 릴리스](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.2.0)의 변경 사항도 확인하세요.

## 업데이트 방법

처음 설치할 때와 같은 명령을 다시 실행하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

최신 릴리스를 내려받아 검증하고 암호화 백업을 만든 뒤 업데이트하고 관리 화면을 엽니다. 설정, Android 데이터, 카카오톡 로그인, 수집 승인은 유지됩니다.

0.1.0을 설치한 Linux 서버는 `./bridge up`이 아니라 이 설치 명령으로 업데이트하세요. 그 밖의 릴리스 설치는 설치 폴더에서 `./bridge upgrade`를 실행해도 되며, Git 작업 폴더는 `git pull` 후 `./bridge update --source`를 사용합니다. [업데이트 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md#update)

## 확인한 범위

자동 테스트와 운영체제를 다크 모드로 설정한 브라우저에서 관리 화면이 밝게 표시되는 것을 확인했습니다. [0.2.0에서 확인되지 않은 부분](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.2.0)은 그대로입니다.

새로 설치하는 방법과 실행 조건은 [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md)를 참고하세요.

`SHA256SUMS`로 수동 다운로드를 검사할 수 있으며, GitHub CLI의 `gh attestation verify <파일> --repo rokrokss/kakaotalk-bridge`로 출처 증명을 확인할 수 있습니다.
