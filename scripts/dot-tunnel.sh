#!/usr/bin/env bash
# Local Mac/Lima only: forward the isolated plugin port without restarting Android.
set -euo pipefail
exec ssh -F "$HOME/.lima/kakaotalk-test/ssh.config" \
  -o ControlMaster=no -o ControlPath=none -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -N -L 127.0.0.1:18788:127.0.0.1:18787 lima-kakaotalk-test
