#!/usr/bin/env bash
# For a Lima VM built by hand: forward the isolated MCP port without restarting Android.
set -euo pipefail
instance="${LIMA_INSTANCE:-kakaotalk-bridge}"
exec ssh -F "$HOME/.lima/$instance/ssh.config" \
  -o ControlMaster=no -o ControlPath=none -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -N -L 127.0.0.1:18788:127.0.0.1:18787 "lima-$instance"
