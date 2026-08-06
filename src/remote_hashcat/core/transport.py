"""SSH/rsync transport to fleet instances.

Shells out to the system `ssh`/`rsync` (robust, matches muscle memory, no extra
deps for file moves). Argv construction is split from execution so it can be
unit-tested without a network.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from remote_hashcat.core.fleet import FleetRegistry


def resolve_private_key_path() -> Path:
    env_path = os.environ.get("REMOTE_HASHCAT_SSH_KEY")
    if env_path:
        priv = Path(env_path).expanduser()
        if priv.suffix == ".pub":
            priv = priv.with_suffix("")
        if priv.exists():
            return priv
    ssh_dir = Path.home() / ".ssh"
    for name in ("id_ed25519_vast_ai", "id_ed25519", "id_rsa"):
        candidate = ssh_dir / name
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "No SSH private key found. Set REMOTE_HASHCAT_SSH_KEY to your key path."
    )


class SSHTransport:
    def __init__(self, host: str, port: int, key_path: Path | None = None):
        if not host or not port:
            raise RuntimeError(
                "Instance has no SSH endpoint yet (still booting?). "
                "Check `provision_worker ls`."
            )
        self.host = host
        self.port = int(port)
        self.key_path = key_path or resolve_private_key_path()

    @classmethod
    def for_instance(
        cls, index: int, provider=None, registry: FleetRegistry | None = None
    ) -> "SSHTransport":
        registry = registry or FleetRegistry()
        inst = registry.get(index)
        if inst is None:
            raise RuntimeError(f"No fleet instance [{index}]. See `provision_worker ls`.")
        host, port = inst.ssh_host, inst.ssh_port

        # Refresh the ssh endpoint from the live API when possible (it can change).
        if provider is None:
            try:
                from remote_hashcat.core.provider import VastProvider

                provider = VastProvider()
            except Exception:
                provider = None
        if provider is not None:
            try:
                status = provider.show_instance(inst.vast_instance_id)
                if status.get("ssh_host"):
                    host = status["ssh_host"]
                    port = int(status.get("ssh_port", port) or port)
                    inst.ssh_host, inst.ssh_port = host, port
                    registry.upsert(inst)
            except Exception:
                pass
        return cls(host, port)

    def _ssh_opts(self) -> list[str]:
        return [
            "-p", str(self.port),
            "-i", str(self.key_path),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
        ]

    def _rsync_e(self) -> str:
        return "ssh " + " ".join(self._ssh_opts())

    def send_argv(
        self, sources: list[str], dest: str, extra: list[str] | None = None
    ) -> list[str]:
        argv = ["rsync", "-av", "--progress", "-e", self._rsync_e()]
        argv += extra or []
        argv += list(sources)
        argv.append(f"root@{self.host}:{dest}")
        return argv

    def receive_argv(
        self, sources: list[str], dest: str, extra: list[str] | None = None
    ) -> list[str]:
        argv = ["rsync", "-av", "--progress", "-e", self._rsync_e()]
        argv += extra or []
        argv += [f"root@{self.host}:{s}" for s in sources]
        argv.append(dest)
        return argv

    def exec_argv(self, command: str) -> list[str]:
        return ["ssh", *self._ssh_opts(), f"root@{self.host}", command]

    def run(self, argv: list[str]) -> int:
        return subprocess.call(argv)
