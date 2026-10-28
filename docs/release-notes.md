# Mac 포트 연결 수정

Mac에서 설치가 끝났다고 표시된 뒤에도 관리 화면(`http://localhost:<포트>/admin/`)과 MCP 포트에 연결되지 않던 문제를 고쳤습니다. 0.3.1·0.3.2에서 바로 업데이트할 수 있습니다.

## 주요 변경

- **Bridge가 포트를 직접 연결:** 지금까지는 Lima가 VM 안의 포트를 Mac으로 전달했습니다. Lima는 VM 안의 에이전트가 열린 포트를 알려야 전달하는데, Lima 2.2.1과 macOS 27 조합에서 이 알림이 부팅 내내 오지 않았습니다. 그래서 VM 안의 서비스는 모두 정상인데도 Mac에서는 연결할 수 없었고, Mac을 재시작해도 반복되었습니다. 이제 LaunchAgent(`dev.kakaocollector.bridge.ports.<VM 이름>`)가 별도 SSH 연결로 관리 화면·HTTPS·MCP 포트를 연결합니다. VM이 다시 시작되거나 Mac이 잠자기에서 깨어나 연결이 끊기면 launchd가 다시 연결합니다. 포트 번호는 그대로입니다.
- **연결을 확인한 뒤 진행:** VM을 켤 때마다 Mac에서 포트가 실제로 열렸는지 확인합니다. 30초 안에 열리지 않으면 열리지 않는 설정 화면을 띄우는 대신 원인과 다음 조치를 안내합니다.
- **기존 VM 전환:** 이전 버전이 만든 VM에는 Lima의 포트 전달 규칙이 남아 있어 새 연결과 같은 포트를 두고 경합합니다. 업데이트 뒤 처음 VM을 켤 때 VM을 한 번 멈추고 이 규칙을 지운 다음 다시 켭니다.
- **삭제:** `kakaotalk-bridge cleanup`이 LaunchAgent도 함께 지웁니다.

macOS 로그인 항목(백그라운드 허용)에 `ssh`가 추가된 것으로 표시될 수 있습니다. 이 항목을 끄면 관리 화면과 MCP에 연결할 수 없습니다.

## 업데이트 방법

0.3.1이나 0.3.2를 쓰고 있다면 `kakaotalk-bridge upgrade`를 실행하거나 설치 명령을 다시 실행하세요. Mac에서는 업데이트 중에 VM이 한 번 다시 시작됩니다. 저장된 메시지·설정·카카오톡 로그인은 그대로 유지됩니다.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

0.3.0 이하를 쓰고 있다면 0.3.1과 마찬가지로 삭제한 뒤 새로 설치해야 합니다. [삭제 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md#uninstall)

## 확인한 범위

자동 테스트와 함께, 이 문제가 재현되는 Apple Silicon Mac(macOS 27.0.1, Lima 2.2.1)의 실제 설치에서 다음을 확인했습니다.

- 재시작할 때마다 Lima가 VM 안의 포트를 하나도 Mac으로 전달하지 않았습니다. VM 안에서 새로 연 포트도 마찬가지였습니다.
- 새 LaunchAgent가 실행하는 SSH 명령만으로 관리 화면과 HTTPS 포트가 Mac에서 응답했습니다.
- 기존 VM의 포트 전달 규칙을 지우는 Lima 설정 변경은 별도로 만든 VM 설정에서 확인했습니다.

launchd에 등록한 상태에서의 재연결(VM 재시작, Mac 잠자기), 이전 릴리스에서 이 버전으로의 실제 업데이트, 새로 설치, Intel Mac에서는 확인하지 않았습니다. Linux 설치는 바뀌지 않았습니다.

새로 설치하는 방법과 실행 조건은 [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md)를 참고하세요.

`SHA256SUMS`로 수동 다운로드를 검사할 수 있으며, GitHub CLI의 `gh attestation verify <파일> --repo rokrokss/kakaotalk-bridge`로 출처 증명을 확인할 수 있습니다.
