# Bridge 삭제 명령

`./bridge cleanup` 한 번으로 이 설치가 만든 VM, 컨테이너, 데이터와 설치 폴더를 지울 수 있습니다.

## 주요 변경

- **`./bridge cleanup`:** 지울 항목을 보여 주고 `삭제`를 입력하면 진행합니다(`--yes`로 확인 생략). Mac은 관리되는 Lima VM을, Linux는 이 설치의 컨테이너·볼륨(복구 전 볼륨 포함)·네트워크·이미지, 웹 연결 설정 서비스, Binder 자동 로드 설정을 지운 뒤 설치 폴더를 지웁니다. 카카오톡 로그인, 수집한 메시지, 패스키, 백업도 함께 사라지며 되돌릴 수 없습니다. [삭제 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md#uninstall)
- **공용 도구 유지:** Docker, Homebrew, Lima, Tailscale, uv는 다른 프로그램도 쓸 수 있으므로 지우지 않습니다. `./bridge expose`로 켠 Tailscale Funnel은 설정이 바뀌지 않았을 때만 끕니다. AI 앱에 추가한 연결과 Tailscale 관리 콘솔의 기기는 직접 지우세요.

이전 버전에서 바로 업데이트한다면 건너뛴 릴리스의 변경 사항도 확인하세요: [0.2.1](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.2.1)(밝은 관리 화면), [0.2.0](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.2.0).

## 업데이트 방법

처음 설치할 때와 같은 명령을 다시 실행하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

최신 릴리스를 내려받아 검증하고 암호화 백업을 만든 뒤 업데이트하고 관리 화면을 엽니다. 설정, Android 데이터, 카카오톡 로그인, 수집 승인은 유지됩니다.

0.1.0을 설치한 Linux 서버는 `./bridge up`이 아니라 이 설치 명령으로 업데이트하세요. 그 밖의 릴리스 설치는 설치 폴더에서 `./bridge upgrade`를 실행해도 되며, Git 작업 폴더는 `git pull` 후 `./bridge update --source`를 사용합니다. [업데이트 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md#update)

## 확인한 범위

자동 테스트와 함께, 카카오톡 계정이 없는 Linux 테스트 VM의 릴리스 설치에서 `./bridge cleanup`을 실행해 서비스, 컨테이너, 볼륨, 네트워크, 이미지, Binder 설정, 설치 폴더가 지워지고 관련 없는 볼륨과 네트워크는 남는 것을 확인했습니다. Mac의 VM 삭제와 Tailscale Funnel 해제는 자동 테스트로만 확인했습니다. [0.2.0에서 확인되지 않은 부분](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.2.0)은 그대로입니다.

새로 설치하는 방법과 실행 조건은 [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md)를 참고하세요.

`SHA256SUMS`로 수동 다운로드를 검사할 수 있으며, GitHub CLI의 `gh attestation verify <파일> --repo rokrokss/kakaotalk-bridge`로 출처 증명을 확인할 수 있습니다.
