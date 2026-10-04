# Iris collector adaptation

Upstream: https://github.com/dolidolih/Iris
Pinned commit: ee1dc978ec465df11642596e40f74caff497301d
Source archive SHA256: 1b194b137b0912ef360a4a0b511c6ed5169aaaf0da85c1de1cf59b325bebfcd0

This is a modified Iris build, not an upstream release. CollectorMain.kt is the
only launched entry point. It uses Iris's KakaoDecrypt with Android read-only
SQLite queries and a loopback-only Ktor server. It never starts the upstream
sender, observer, dashboard, token endpoint or file-deletion task. A restricted metadata endpoint resolves local room and sender display names.
Media and message edits/deletions are not collected.

Collector v4 authenticates data requests with an enrollment-bound, root-only
credential. Its health challenge authenticates the listener before the host sends
that credential. All Netty modules are aligned with the enforced 4.1.138.Final BOM;
the resolved runtime dependency report is retained at /opt/iris-dependencies.txt.

The APK still compiles upstream GPL/MIT source; distribute it under the upstream
GPL-3.0 terms with corresponding source and notices. The device image includes
/opt/iris-source.tar.gz (exact upstream), /opt/iris-overlay/ (our additions), and
/opt/iris-build.Dockerfile (build recipe). Upstream license texts are in the archive.
Our Kotlin collector overlay is offered under GPL-3.0-or-later. Keep these files when exporting
or distributing the APK. No upstream install_redroid script is executed.

The modern profile reader bundles SQLCipher for Android 4.10.0 (Community edition),
from https://github.com/sqlcipher/sqlcipher-android. Its AAR SHA-256 is
cc60b1a40d023bec06a1e56740db7172d2516668570140cd9de00ca90f84cd9f.
The redistribution notice is included in SQLCipher-LICENSE. AndroidX SQLite
2.4.0 supplies its support interfaces. No KakaoTalk APK or application source
is included in the collector image.
