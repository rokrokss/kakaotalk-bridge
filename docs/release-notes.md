# 어디서나 쓰는 `kakaotalk-bridge` 명령과 모든 설치의 업데이트

설치 폴더로 이동하지 않고 `kakaotalk-bridge doctor`처럼 바로 실행할 수 있습니다. 같은 설치 명령은 이제 설치 형태에 맞게 업데이트하며, 업데이트 중에는 이전 버전의 코드를 실행하지 않습니다. 첫 릴리스 전에 받은 설치도 업데이트할 수 있습니다.

## 주요 변경

- **`kakaotalk-bridge` 명령:** 설치하거나 업데이트하면 Mac은 `~/.local/bin`, Linux는 `/usr/local/bin`에 명령이 생깁니다. Mac에서 `~/.local/bin`이 PATH에 없으면 `~/.zprofile`(bash는 `~/.bash_profile`)에 한 줄을 추가하고 알려 줍니다. 설치 폴더 안의 `./bridge`도 그대로 쓸 수 있습니다. 이미 다른 설치를 가리키는 명령은 바꾸지 않습니다.
- **업데이트는 새 버전의 코드가 수행:** 설치 명령은 새 버전을 받아 검증한 뒤 그 버전의 코드로 파일을 바꾸고, 새 CLI로 옵션 확인과 서비스 업데이트를 합니다. 업데이트 기능이 없던 설치나 업데이트 코드에 문제가 있던 버전도 설치 명령으로 올릴 수 있습니다. 옵션이 잘못되었거나 업데이트가 실패하면 이전 코드로 되돌립니다.
- **소스로 받은 설치도 업데이트:** `release.json` 없이 소스로 받은 설치(0.1.0 릴리스 전에 설치 명령으로 받은 설치 포함)는 최신 릴리스 태그의 소스를 받아, 기기에 설치된 키보드 앱과 같은 개인 서명 키로 이미지를 다시 빌드합니다. 이전에는 이런 설치에서 설치 명령을 다시 실행해도 예전 코드가 그대로 실행됐습니다. Git 작업 폴더는 자동으로 업데이트하지 않고 `git pull && kakaotalk-bridge update --source`를 안내합니다.
- **AI 앱 stdio 설정:** 새로 복사하는 설정은 Python 경로 대신 `kakaotalk-bridge` 명령의 절대 경로를 씁니다. 이미 추가한 설정은 그대로 동작합니다.
- **삭제:** `kakaotalk-bridge cleanup`은 이 설치를 가리키는 명령도 지웁니다. 셸 설정의 PATH 줄은 다른 도구와 함께 쓰므로 남겨 둡니다.

이전 버전에서 바로 업데이트한다면 건너뛴 릴리스의 변경 사항도 확인하세요: [0.2.2](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.2.2)(설치 삭제 명령), [0.2.1](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.2.1)(밝은 관리 화면), [0.2.0](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.2.0).

## 업데이트 방법

처음 설치할 때와 같은 명령을 다시 실행하세요. 0.2.2 이하 버전에는 `kakaotalk-bridge` 명령이 없으므로 이번에는 이 명령으로 업데이트해야 합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

최신 버전을 내려받아 검증하고 암호화 백업을 만든 뒤 업데이트하고 관리 화면을 엽니다. 설정, Android 데이터, 카카오톡 로그인, 수집 승인은 유지됩니다. 다음부터는 `kakaotalk-bridge upgrade`로도 업데이트할 수 있습니다. [업데이트 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md#update)

## 확인한 범위

자동 테스트와 함께, 카카오톡 계정이 없는 Apple Silicon Mac의 테스트 VM에서 다음을 확인했습니다.

- **릴리스 설치:** 0.2.2까지의 설치 명령으로 받은 0.2.1을 이번 설치 명령으로 다시 실행해 0.2.2로 업데이트했습니다. 설치된 이전 코드는 한 번도 실행되지 않았고, 암호화 백업을 만든 뒤 볼륨과 키를 그대로 둔 채 이미지만 바뀌었으며 상태 점검이 모두 정상이었습니다. 다시 실행하면 업데이트 없이 관리 화면을 엽니다.
- **첫 릴리스 전 설치:** 0.1.0 릴리스 전의 설치 명령으로 받은 main 소스(54e4512)를 이번 버전의 소스로 업데이트했습니다. 이전 Compose 프로젝트와 볼륨, 키를 그대로 쓰면서 같은 서명 키로 이미지를 다시 빌드했고 상태 점검이 정상이었습니다. 같은 설치를 0.2.2 소스로 업데이트하면 `.git` 없는 폴더의 소스 빌드에 `LICENSE`가 빠져 빌드가 실패하는데, 이때 이전 코드와 서비스로 자동 복구되는 것도 확인했습니다. 이 빌드 문제는 이번 버전에서 고쳤습니다.
- **`kakaotalk-bridge` 명령:** 다른 폴더에서 `doctor`, stdio MCP 응답, `cleanup`(명령 파일 삭제 포함)을 확인했습니다.

실제 카카오톡 계정의 수집 승인 유지, Linux 서버와 Intel Mac·WSL에서의 업데이트, 이번 릴리스 자체로의 업데이트는 확인하지 않았습니다. [0.2.0에서 확인되지 않은 부분](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.2.0)은 그대로입니다.

새로 설치하는 방법과 실행 조건은 [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md)를 참고하세요.

`SHA256SUMS`로 수동 다운로드를 검사할 수 있으며, GitHub CLI의 `gh attestation verify <파일> --repo rokrokss/kakaotalk-bridge`로 출처 증명을 확인할 수 있습니다.
