# 메시지 전송 준비 확인

카카오톡이 아직 알림을 한 번도 띄우지 않은 태블릿에서 AI의 메시지 전송이 원인 표시 없이 실패하던 문제를 고쳤습니다. 0.3.1에서 바로 업데이트할 수 있습니다.

## 주요 변경

- **첫 알림 전 전송 거절:** 카카오톡은 알림 답장에 필요한 값을 첫 메시지 알림 때 저장합니다. 그 전에는 전송 요청이 접수된 뒤 `device_rejected`로 실패했습니다. 이제 요청을 바로 `sending_unavailable_until_kakaotalk_notification`(423)으로 거절하고 관리 화면 현황에 **메시지 전송 준비 필요**를 표시합니다. 태블릿에서 대화방 밖의 화면을 띄운 채 다른 사람의 메시지를 한 번 받으면 10여 초 안에 보낼 수 있습니다. 수집기는 이 값이 있는지만 확인하고 값 자체는 기기 밖으로 가져오지 않습니다.
- **터널 전송 권한 버튼:** 관리 화면 **AI 연결**의 **메시지 전송 허용**은 터널을 허용한 뒤 AI 요청이 한 번 성공해야 켜집니다. 이미 허용한 전송 권한은 그대로 유지됩니다.
- **대화 이벤트 안내:** 관리 화면의 **대화 이벤트**에 새 카카오톡 메시지를 AI에 바로 알리는 기능이라는 설명과 준비 단계를 추가했습니다.

## 업데이트 방법

0.3.1을 쓰고 있다면 `kakaotalk-bridge upgrade`를 실행하거나 설치 명령을 다시 실행하세요. 저장된 메시지·설정·카카오톡 로그인은 그대로 유지됩니다.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

0.3.0 이하를 쓰고 있다면 0.3.1과 마찬가지로 삭제한 뒤 새로 설치해야 합니다. [삭제 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/operations.md#uninstall)

## 확인한 범위

자동 테스트를 통과했습니다. 테스트 VM에서의 실제 업데이트 확인은 진행 중입니다.

새로 설치하는 방법과 실행 조건은 [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md)를 참고하세요.

`SHA256SUMS`로 수동 다운로드를 검사할 수 있으며, GitHub CLI의 `gh attestation verify <파일> --repo rokrokss/kakaotalk-bridge`로 출처 증명을 확인할 수 있습니다.
