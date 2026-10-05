# Windows entry point: use an existing Linux server or a Binder-enabled WSL2 distribution.
[CmdletBinding()]
param(
    [string]$Remote,
    [string]$Distribution = 'Ubuntu'
)
$ErrorActionPreference = 'Stop'
$installer = 'https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh'
$command = "curl --fail --silent --show-error --location --proto '=https' $installer | bash -s -- --no-browser"

if ($Remote) {
    if ($Remote -notmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*$') {
        throw 'Remote는 user@hostname 형식이어야 합니다. 별도 포트나 키는 SSH 설정 별칭으로 지정하세요.'
    }
    if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
        throw 'Windows의 OpenSSH 클라이언트 선택 기능을 켜고 다시 실행하세요.'
    }
    Write-Host 'Linux 서버에서 Bridge 준비 중… 아래에 표시되는 설정 링크를 여세요.'
    & ssh -t -- $Remote $command
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host 'localhost:18789를 서버에 연결하고 있습니다. 위 설정 링크를 여세요. Ctrl+C를 누르면 포워딩을 종료합니다.'
    & ssh -N -o ExitOnForwardFailure=yes -L '127.0.0.1:18789:127.0.0.1:18789' -- $Remote
    exit $LASTEXITCODE
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw '.\install.ps1 -Remote user@linux-host를 사용하세요. 로컬 실행에는 Android Binder를 지원하는 WSL2 커널이 필요합니다.'
}
& wsl.exe -d $Distribution -- sh -c 'test -d /sys/module/binder_linux || test -e /dev/binderfs/binder-control'
if ($LASTEXITCODE -ne 0) {
    throw "'$Distribution' WSL 커널에 Android Binder가 로드되지 않았습니다. .\install.ps1 -Remote user@linux-host를 사용하거나 Binder를 지원하는 WSL2 커널을 준비하세요. 배포판이나 커널은 변경하지 않았습니다."
}
& wsl.exe -d $Distribution -- bash -c $command
exit $LASTEXITCODE
