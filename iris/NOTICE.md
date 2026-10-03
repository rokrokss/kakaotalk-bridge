# Iris collector adaptation

Upstream: https://github.com/dolidolih/Iris
Pinned commit: ee1dc978ec465df11642596e40f74caff497301d
Source archive SHA256: 1b194b137b0912ef360a4a0b511c6ed5169aaaf0da85c1de1cf59b325bebfcd0

This is a modified Iris build, not an upstream release. CollectorMain.kt is the
only launched entry point. It uses Iris's KakaoDecrypt with Android read-only
SQLite queries and a loopback-only Ktor server. It never starts the upstream
sender, observer, dashboard, token endpoint or file-deletion task. Names, media
and message edits/deletions are not collected in this first implementation.

The APK still compiles upstream GPL/MIT source; distribute it under the upstream
GPL-3.0 terms with corresponding source and notices. The device image includes
/opt/iris-source.tar.gz (exact upstream), /opt/iris-overlay/ (our additions), and
/opt/iris-build.Dockerfile (build recipe). Upstream license texts are in the archive.
CollectorMain.kt is offered under GPL-3.0-or-later. Keep these files when exporting
or distributing the APK. No upstream install_redroid script is executed.
