#!/usr/bin/env bash
# Keepalive entrypoint. Vast.ai --ssh mode runs its own SSH daemon in front and
# injects your public key; this prepares work dirs, fixes perms, and stays up so
# the host tool can SSH in and run hashcat on demand.
set -euo pipefail

mkdir -p /root/jobs /root/wordlists /root/rules

if [ -d /root/.ssh ]; then
    chmod 700 /root/.ssh || true
    [ -f /root/.ssh/authorized_keys ] && chmod 600 /root/.ssh/authorized_keys || true
fi

touch /tmp/worker_ready
exec sleep infinity
