# KakaoTalk Bridge 첫 공개 릴리스

개인 GitHub 계정의 GHCR에서 미리 빌드한 이미지를 배포합니다. 설치 프로그램은 같은 버전의 설치 파일과 고정된 이미지 조합을 내려받으며 사용자 컴퓨터에서 소스를 빌드하지 않습니다.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

Linux 헤드리스 서버에서는 끝에 `bash -s -- --no-browser`를 사용하고, 출력된 SSH 포워딩 안내에 따라 내 컴퓨터의 브라우저에서 설정하세요. Apple Silicon Mac에서는 전용 Lima Linux VM을 준비합니다.

- 터미널 설치 안내·관리 화면·문서는 한국어를 기본으로 제공합니다.
- 설치 파일의 SHA-256을 확인하고, 서비스 이미지는 다이제스트로 고정합니다.
- 기존 설치 폴더에서 `./bridge upgrade`로 릴리스 코드와 이미지를 함께 업데이트합니다.
- 설정·Android 데이터는 유지하며 업데이트 전에 암호화 백업을 만듭니다. Iris 구성 요소 이전이 필요한 업데이트는 자동 적용하지 않습니다.
- 카카오톡은 관리 화면의 스토어에서 사용자가 설치하고 로그인합니다. 배포물에는 카카오톡 APK·개인 대화·설치 인증 키가 포함되지 않습니다.

Linux 실행에는 Docker Engine, Compose v2, Android Binder가 필요합니다. 기본 Windows/WSL2와 Intel Mac에서의 실제 실행은 아직 검증하지 않았습니다. 자세한 실행 조건과 검증 범위는 [설치 안내](https://github.com/rokrokss/kakaotalk-bridge/blob/main/docs/quickstart.md)를 참고하세요.

`SHA256SUMS`로 수동 다운로드를 검사할 수 있으며, GitHub CLI의 `gh attestation verify <파일> --repo rokrokss/kakaotalk-bridge`로 출처 증명을 확인할 수 있습니다.
