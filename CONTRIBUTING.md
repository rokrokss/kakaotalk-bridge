# 기여하기

[README](README.md) · [개발](docs/development.md) · [검증 범위](docs/implementation.md)

버그 제보, 문서 개선, 다른 실행 환경에서의 검증 결과를 환영합니다. 큰 변경은 먼저 이슈를 열어 범위를 논의해 주세요.

## 문제 제보

[이슈](https://github.com/rokrokss/kakaotalk-bridge/issues)에 다음 내용을 포함해 주세요.

- 호스트 운영체제·아키텍처와 Lima 사용 여부
- 프로젝트 리비전, 관련 redroid 이미지와 카카오톡 버전
- 재현 절차, 기대 동작, 실제 동작
- 관련 오류 메시지나 민감한 정보를 제거한 로그

로그나 화면을 공유하기 전에 토큰, 계정 정보, 개인 메시지를 제거하세요. 재현 예시에는 가상 메시지를 사용하세요. 데이터와 인증 정보의 경계는 [보안](docs/security.md) 문서를 참고하세요.

호환성 보고에는 실제로 확인한 단계를 구분해 적어 주세요. 이미지 빌드, Android 시작, 보조 기기 로그인, 휴대폰 로그인 유지, 메시지 수집, MCP 클라이언트 연결을 각각 명시하고 직접 확인한 내용도 구분하세요.

## 변경 제안

PR은 하나의 변경에 집중하고 동작이 어떻게 달라지는지 설명해 주세요. 실행한 검사와 결과를 포함하고, 가상 데이터 테스트와 실제 기기·계정 검증을 구분하세요.

[기여 지침](docs/development.md#contribution-guidelines)에 따라 관련 [로컬 검사](docs/development.md#local-checks)를 실행하세요. **문서, 프로젝트가 제공하는 화면, 터미널 안내는 한국어를 기본으로 합니다. 코드 주석, 내부 예외·로그, API 오류 코드와 프로토콜 식별자는 영어로 유지합니다.** 내부 진단 내용을 사용자에게 그대로 노출하기보다 한국어로 상태와 다음 조치를 안내하세요. 카카오톡 화면 인식용 문자열과 다국어 테스트 데이터는 보존하세요.

관리 화면이나 OAuth를 변경하면 [로컬 브라우저 미리보기](docs/development.md#preview-the-web-console)로 실제 계정 없이 폼과 사용자 동작을 확인하세요. 설치나 수집을 변경하면 [검증 범위](docs/implementation.md)를 갱신하고 남은 제한을 기록하세요.

<a id="upgrade-compatibility"></a>
## 업데이트 호환

설치 명령과 `kakaotalk-bridge upgrade`는 새 버전의 코드로 업데이트합니다. 업데이트가 매끄럽게 이어지도록 릴리스마다 다음을 지키세요.

- **바로 이전 릴리스에서 올리는 업데이트는 항상 지원합니다.** DB 스키마, 메시지 다이제스트, `enrollment.json`, `.env`·`secrets/`·`.bridge/`의 파일과 키처럼 저장되는 형식을 바꾸면 그 릴리스의 `update`에서 이전 형식을 변환하세요.
- **변환 코드는 다음 릴리스에서 지울 수 있습니다.** 지울 때는 `ops/releases.py`의 `UPGRADE_FROM`을 변환이 들어간 버전으로 올리세요. 업데이트는 내려받은 릴리스의 이 값을 읽고, 그보다 오래된 설치는 업데이트하지 않고 삭제 후 새로 설치하라고 안내합니다.
- **바꾸지 않습니다:** 릴리스 서명 키(GitHub `release` 환경의 키보드 앱 키스토어), 앱 ID `dev.kakaocollector.bridge`, Compose 프로젝트와 볼륨 이름. 바꾸면 기존 설치를 이어 쓸 수 없습니다.
- **릴리스 전에 실제 업데이트를 확인합니다.** 계정 없는 테스트 VM에 이전 릴리스를 그때의 설치 명령으로 설치하고, 작업 트리의 `install.sh`를 같은 `BRIDGE_HOME`으로 다시 실행해 업데이트하세요. 볼륨과 `secrets/`가 그대로인지, `kakaotalk-bridge doctor`가 정상인지, 다시 실행하면 업데이트하지 않는지 확인한 뒤 VM을 지우세요.

```bash
git show <이전 태그>:install.sh | BRIDGE_HOME=/tmp/bridge-e2e BRIDGE_VERSION=<이전 태그> bash -s -- --no-browser --vm kakaotalk-e2e
BRIDGE_HOME=/tmp/bridge-e2e bash install.sh --no-browser
```

아직 게시하지 않은 코드로 업데이트하려면 소스 설치는 커밋을 임시 브랜치에 올려 `BRIDGE_VERSION=<커밋>`으로, 릴리스 설치는 `vX.Y.Z-rc.N` 태그로 게시한 프리릴리스를 `BRIDGE_VERSION`으로 지정하세요. 프리릴리스는 최신 릴리스로 선택되지 않습니다.
