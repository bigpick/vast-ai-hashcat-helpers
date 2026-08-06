"""Thin wrapper over the Vast.ai Python SDK.

Adapted from the sibling `hashcat-benchmarks` repo. The `vastai` import is
deferred into `__init__` so importing this module (e.g. in tests) never requires
the SDK or an API key. `__repr__` is overridden and every SDK error is sanitized
so the API key cannot leak into logs or tracebacks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from remote_hashcat.core.config import sanitize


class VastProvider:
    def __init__(self, sdk: Any = None, api_key: str | None = None):
        if sdk is not None:
            self._sdk = sdk
            return
        key = api_key or os.environ.get("VAST_API_KEY")
        if not key:
            raise RuntimeError(
                "VAST_API_KEY not set. Export it as an environment variable or "
                "add it to .env (see .env.example)."
            )
        from vastai import VastAI

        self._sdk = VastAI(api_key=key)

    def __repr__(self) -> str:  # never render the wrapped SDK / key
        return "VastProvider(...)"

    # --- offers -----------------------------------------------------------

    def search_offers(
        self, query: str, order: str = "dph_total", limit: int = 50
    ) -> list[dict]:
        try:
            offers = self._sdk.search_offers(query=query, order=order, limit=str(limit))
        except Exception as e:
            raise RuntimeError(sanitize(str(e))) from None
        return offers or []

    def offers_for_machine(self, machine_id: int) -> list[dict]:
        """Offers on one physical machine, biggest bundle first (num_gpus desc)."""
        offers = self.search_offers(f"machine_id={machine_id} rentable=true")
        return sorted(offers, key=lambda o: o.get("num_gpus", 0), reverse=True)

    # --- ssh keys ---------------------------------------------------------

    def ensure_ssh_key(self, pub_key_path: Path | None = None) -> str:
        """Make sure our SSH public key is registered on the Vast account."""
        if pub_key_path is None:
            env_val = os.environ.get("REMOTE_HASHCAT_SSH_KEY")
            if env_val:
                pub_key_path = Path(env_val).expanduser()
                if pub_key_path.suffix != ".pub":
                    pub_key_path = pub_key_path.with_suffix(".pub")
            else:
                ssh_dir = Path.home() / ".ssh"
                for name in ("id_ed25519_vast_ai.pub", "id_ed25519.pub", "id_rsa.pub"):
                    candidate = ssh_dir / name
                    if candidate.exists():
                        pub_key_path = candidate
                        break
        if pub_key_path is None or not pub_key_path.exists():
            raise RuntimeError(
                "No SSH public key found. Set REMOTE_HASHCAT_SSH_KEY to your key path."
            )

        pub_key = pub_key_path.read_text().strip()
        parts = pub_key.split()
        fingerprint = parts[1][:20] if len(parts) >= 2 else pub_key[:20]

        try:
            existing = self._sdk.show_ssh_keys()
            keys_list = (
                existing
                if isinstance(existing, list)
                else (existing or {}).get("ssh_keys", [])
            )
            for k in keys_list:
                stored = k.get("ssh_key", "") if isinstance(k, dict) else str(k)
                if fingerprint in stored:
                    return pub_key
        except Exception:
            pass

        try:
            self._sdk.create_ssh_key(ssh_key=pub_key)
        except Exception:
            pass
        return pub_key

    # --- instances --------------------------------------------------------

    def create_instance(
        self,
        offer_id: int,
        image: str,
        *,
        disk: int = 64,
        env: dict[str, str] | None = None,
        onstart_cmd: str | None = None,
        label: str | None = None,
        ssh: bool = True,
        direct: bool = True,
    ) -> int:
        kwargs: dict = dict(
            id=offer_id,
            image=image,
            disk=disk,
            env=env or {},
            ssh=ssh,
            direct=direct,
        )
        if onstart_cmd:
            kwargs["onstart_cmd"] = onstart_cmd
        if label:
            kwargs["label"] = label
        try:
            result = self._sdk.create_instance(**kwargs)
        except Exception as e:
            raise RuntimeError(sanitize(str(e))) from None
        return result["new_contract"]

    def show_instance(self, instance_id: int) -> dict:
        try:
            return self._sdk.show_instance(id=instance_id) or {}
        except Exception as e:
            raise RuntimeError(sanitize(str(e))) from None

    def destroy_instance(self, instance_id: int) -> None:
        try:
            self._sdk.destroy_instance(id=instance_id)
        except Exception as e:
            raise RuntimeError(sanitize(str(e))) from None

    def list_instances(self) -> list[dict]:
        try:
            result = self._sdk.show_instances()
        except Exception as e:
            raise RuntimeError(sanitize(str(e))) from None
        return result or []
