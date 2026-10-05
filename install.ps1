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
        throw 'Remote must be user@hostname. Use an SSH config alias for custom ports or keys.'
    }
    if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
        throw 'Enable the Windows OpenSSH Client optional feature, then run this command again.'
    }
    Write-Host 'Preparing Bridge on your Linux server. Open the setup link printed below.'
    & ssh -t -- $Remote $command
    exit $LASTEXITCODE
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Use .\install.ps1 -Remote user@linux-host. Local execution requires WSL2 with an Android Binder-enabled kernel.'
}
& wsl.exe -d $Distribution -- sh -c 'test -d /sys/module/binder_linux || test -e /dev/binderfs/binder-control'
if ($LASTEXITCODE -ne 0) {
    throw "The '$Distribution' WSL kernel has no loaded Android Binder support. Use .\install.ps1 -Remote user@linux-host, or prepare a Binder-enabled WSL2 kernel. No distribution or kernel was replaced."
}
& wsl.exe -d $Distribution -- bash -c $command
exit $LASTEXITCODE
