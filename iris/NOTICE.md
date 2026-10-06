# Iris 수집기 수정 빌드

원본: https://github.com/dolidolih/Iris

고정 커밋: `ee1dc978ec465df11642596e40f74caff497301d`

소스 압축 파일 SHA-256: `1b194b137b0912ef360a4a0b511c6ed5169aaaf0da85c1de1cf59b325bebfcd0`

이 빌드는 원본 릴리스가 아닌 수정된 Iris입니다. 실행 진입점은 `CollectorMain.kt`뿐이며 Iris의 KakaoDecrypt, Android 읽기 전용 SQLite 조회, 루프백 전용 Ktor 서버를 사용합니다. 원본의 전송 큐·관찰기·대시보드·토큰 경로·파일 삭제 작업은 시작하지 않습니다. 제한된 메타데이터 경로로 로컬 대화방·발신자 이름을 조회합니다. 미디어와 메시지 수정·삭제는 수집하지 않습니다.

수집기는 등록에 묶인 root 전용 키로 데이터 요청을 인증합니다. 호스트가 키를 보내기 전에 상태 challenge로 리스너를 검증합니다. 모든 Netty 모듈은 `4.1.138.Final` BOM으로 맞추며 실제 실행 의존성 보고서는 `/opt/iris-dependencies.txt`에 보관합니다.

APK에는 원본 GPL·MIT 소스가 컴파일되어 있으므로 원본 GPL-3.0 조건에 따라 대응 소스와 고지를 함께 배포해야 합니다. 기기 이미지에는 `/opt/iris-source.tar.gz`(정확한 원본), `/opt/iris-overlay/`(추가 코드), `/opt/iris-build.Dockerfile`(빌드 절차)이 포함됩니다. 원본 라이선스 전문은 압축 파일에 있습니다. `CollectorSender.kt`의 알림 답장 Intent 구성은 고정 원본 `Replier.kt`의 GPL-3.0 전송 경로를 기반으로 하며 GPL-3.0 조건을 따릅니다. 그 외 이 프로젝트의 Kotlin 수집기 오버레이 소스는 [MIT 라이선스](../LICENSE)로 제공하지만, 이를 포함해 빌드한 APK 전체에는 GPL-3.0이 적용됩니다. APK를 내보내거나 배포할 때 이 파일들을 유지하세요. 원본 `install_redroid` 스크립트는 실행하지 않습니다.

최신 프로필 리더는 [SQLCipher for Android](https://github.com/sqlcipher/sqlcipher-android) 4.10.0 Community 에디션을 포함합니다. AAR SHA-256은 `cc60b1a40d023bec06a1e56740db7172d2516668570140cd9de00ca90f84cd9f`입니다. 재배포 고지는 [SQLCipher-LICENSE](SQLCipher-LICENSE)에 원문으로 포함되어 있습니다. 지원 인터페이스는 AndroidX SQLite 2.4.0을 사용합니다. 수집기 이미지에 카카오톡 APK나 앱 소스는 포함하지 않습니다.
