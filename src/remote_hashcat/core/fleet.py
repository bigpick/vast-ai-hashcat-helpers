"""Local fleet registry: the seam between provision_worker and remote_hashcat.

Maps a friendly index (1..N) to a Vast instance. Stored as JSON at
~/.config/remote-hashcat/fleet.json (outside the repo). Contains no secrets:
instance ids, public ssh host/port, and GPU metadata only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from remote_hashcat.core.config import config_dir

REGISTRY_VERSION = 1


@dataclass
class FleetInstance:
    index: int
    vast_instance_id: int
    gpu_name: str = ""
    num_gpus: int = 0
    dph_total: float = 0.0
    geolocation: str = ""
    cuda_max_good: float = 0.0
    image: str = ""
    label: str = ""
    created_at: str = ""
    ssh_host: str = ""
    ssh_port: int = 0
    current_job: str | None = None


class FleetRegistry:
    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "fleet.json")

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": REGISTRY_VERSION, "instances": {}}
        return json.loads(self.path.read_text())

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self.path)

    def list(self) -> list[FleetInstance]:
        raw = self._load()
        out = []
        for key, value in raw.get("instances", {}).items():
            value = {k: v for k, v in value.items() if k != "index"}
            out.append(FleetInstance(index=int(key), **value))
        return sorted(out, key=lambda i: i.index)

    def get(self, index: int) -> FleetInstance | None:
        for inst in self.list():
            if inst.index == index:
                return inst
        return None

    def next_index(self) -> int:
        used = {inst.index for inst in self.list()}
        n = 1
        while n in used:
            n += 1
        return n

    def upsert(self, inst: FleetInstance) -> None:
        raw = self._load()
        value = {k: v for k, v in asdict(inst).items() if k != "index"}
        raw.setdefault("instances", {})[str(inst.index)] = value
        self._save(raw)

    def remove(self, index: int) -> None:
        raw = self._load()
        raw.get("instances", {}).pop(str(index), None)
        self._save(raw)
