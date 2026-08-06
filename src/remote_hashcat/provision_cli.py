"""`provision_worker` — provision and manage a Vast.ai hashcat fleet.

Writes the shared fleet registry that `remote_hashcat` reads.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from remote_hashcat.core import config
from remote_hashcat.core import offers as offers_mod
from remote_hashcat.core.fleet import FleetInstance, FleetRegistry

# Runs once on the instance at boot: fix SSH perms and create work dirs. Vast's
# --ssh mode keeps the container alive; this just prepares it.
ONSTART = (
    "sleep 2; "
    "chmod 700 /root/.ssh 2>/dev/null; "
    "chown -R root:root /root/.ssh 2>/dev/null; "
    "chmod 600 /root/.ssh/authorized_keys 2>/dev/null; "
    "mkdir -p /root/jobs /root/wordlists /root/rules; "
    "touch /tmp/worker_ready"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _provider():
    from remote_hashcat.core.provider import VastProvider

    return VastProvider()


def _gather_offers(provider, args) -> list[dict]:
    if args.machine:
        return provider.offers_for_machine(args.machine)
    if args.offer:
        return [{"id": args.offer}]
    if args.gpu:
        query = offers_mod.build_query(gpu=args.gpu, num_gpus=args.num_gpus)
        return provider.search_offers(query, limit=args.limit)
    raise SystemExit("Specify --machine, --offer, or --gpu")


def _filter_and_rank(found: list[dict], args) -> list[dict]:
    min_cuda = args.min_cuda if args.min_cuda is not None else config.cuda_major_minor()
    filtered = offers_mod.apply_filters(
        found,
        region=args.region,
        max_price=args.max_price,
        min_reliability=args.min_reliability,
        min_cuda=min_cuda,
    )
    return offers_mod.rank(filtered, mode=args.rank)


def search_cmd(args) -> None:
    provider = _provider()
    found = _gather_offers(provider, args)
    ranked = _filter_and_rank(found, args)
    if not ranked:
        print(f"No offers matched ({len(found)} before filters).")
        return
    print(f"{len(ranked)} offer(s) (showing up to {args.limit}):")
    for i, o in enumerate(ranked[: args.limit], 1):
        print("  " + offers_mod.format_offer(o, i))


def up_cmd(args) -> None:
    provider = _provider()
    found = _gather_offers(provider, args)
    if args.offer:
        selection = [found[0]]
    else:
        ranked = _filter_and_rank(found, args)
        if not ranked:
            print(f"No offers matched ({len(found)} before filters).")
            return
        if args.count > 1:
            selection = ranked[: args.count]
        else:
            chosen = offers_mod.pick(ranked, auto=args.yes)
            selection = [chosen] if chosen else []
    if not selection:
        print("Nothing selected.")
        return

    image = args.image or config.image_ref()
    provider.ensure_ssh_key()
    registry = FleetRegistry()
    created: list[FleetInstance] = []
    for chosen in selection:
        print(
            f"Reserving offer {chosen.get('id')} "
            f"({chosen.get('num_gpus', '?')}x {chosen.get('gpu_name', '?')}, "
            f"${chosen.get('dph_total', 0):.3f}/hr) with image {image} ..."
        )
        instance_id = provider.create_instance(
            offer_id=chosen["id"],
            image=image,
            disk=args.disk,
            onstart_cmd=ONSTART,
            label=config.label(),
        )
        index = registry.next_index()
        inst = FleetInstance(
            index=index,
            vast_instance_id=instance_id,
            gpu_name=chosen.get("gpu_name", ""),
            num_gpus=chosen.get("num_gpus", 0),
            dph_total=chosen.get("dph_total", 0.0),
            geolocation=chosen.get("geolocation", ""),
            cuda_max_good=chosen.get("cuda_max_good", 0.0),
            image=image,
            label=config.label(),
            created_at=_now_iso(),
        )
        registry.upsert(inst)
        created.append(inst)
        print(f"  Instance {instance_id} saved as fleet index [{index}].")

    if args.no_wait or len(created) != 1:
        print("Check `provision_worker ls` for status.")
        return
    _wait_and_record(provider, registry, created[0])


def _wait_and_record(provider, registry, inst, timeout=1800, interval=15) -> None:
    start = time.time()
    print("Waiting for boot (Ctrl-C to stop watching; it keeps provisioning)...")
    try:
        while time.time() - start < timeout:
            status = provider.show_instance(inst.vast_instance_id)
            actual = status.get("actual_status", "unknown")
            msg = status.get("status_msg", "") or ""
            elapsed = int(time.time() - start)
            print(f"  [{elapsed}s] status: {actual} {msg[:50]}    ", end="\r")
            if actual == "running" and status.get("ssh_host"):
                inst.ssh_host = status.get("ssh_host", "")
                inst.ssh_port = int(status.get("ssh_port", 0) or 0)
                registry.upsert(inst)
                print(f"\n  Ready: ssh root@{inst.ssh_host} -p {inst.ssh_port}")
                return
            if actual in ("exited", "error"):
                print(f"\n  Instance entered '{actual}'. Message: {msg}")
                return
            time.sleep(interval)
        print("\n  Timed out; check `provision_worker ls`.")
    except KeyboardInterrupt:
        print("\n  Stopped watching; instance still provisioning. Use `provision_worker ls`.")


def ls_cmd(args) -> None:
    provider = _provider()
    registry = FleetRegistry()
    fleet = registry.list()
    if not fleet:
        print("Fleet is empty. Provision with `provision_worker up ...`.")
        return
    live = {i.get("id"): i for i in provider.list_instances()}
    header = f"{'idx':>3}  {'instance':>10}  {'gpu':<20}  {'$/hr':>7}  {'status':<10}  {'cost':>8}  ssh"
    print(header)
    for inst in fleet:
        info = live.get(inst.vast_instance_id, {})
        status = info.get("actual_status", "gone")
        cost = ""
        start_date = info.get("start_date")
        if start_date:
            hours = max(0.0, (time.time() - float(start_date)) / 3600.0)
            cost = f"${hours * inst.dph_total:.2f}"
        host = info.get("ssh_host") or inst.ssh_host or ""
        port = info.get("ssh_port") or inst.ssh_port or ""
        ssh = f"root@{host} -p {port}" if host else ""
        gpu = f"{inst.num_gpus}x {inst.gpu_name}"
        print(
            f"{inst.index:>3}  {inst.vast_instance_id:>10}  {gpu:<20}  "
            f"${inst.dph_total:>6.3f}  {status:<10}  {cost:>8}  {ssh}"
        )


def down_cmd(args) -> None:
    provider = _provider()
    registry = FleetRegistry()
    fleet = registry.list()
    if args.all:
        targets = fleet
    elif args.instance is not None:
        one = registry.get(args.instance)
        targets = [one] if one else []
    else:
        raise SystemExit("Specify --instance N or --all")
    if not targets:
        print("No matching instances.")
        return
    print("About to destroy:")
    for t in targets:
        print(f"  [{t.index}] instance {t.vast_instance_id}  {t.num_gpus}x {t.gpu_name}")
    if not args.yes and input("Proceed? [y/N] ").strip().lower() != "y":
        print("Aborted.")
        return
    for t in targets:
        provider.destroy_instance(t.vast_instance_id)
        registry.remove(t.index)
        print(f"  Destroyed [{t.index}] instance {t.vast_instance_id}.")


def sync_cmd(args) -> None:
    provider = _provider()
    registry = FleetRegistry()
    ours = config.label()
    labeled = [i for i in provider.list_instances() if i.get("label") == ours]
    existing = {inst.vast_instance_id: inst for inst in registry.list()}
    for info in labeled:
        iid = info.get("id")
        inst = existing.get(iid) or FleetInstance(
            index=registry.next_index(), vast_instance_id=iid
        )
        inst.gpu_name = info.get("gpu_name", inst.gpu_name)
        inst.num_gpus = info.get("num_gpus", inst.num_gpus)
        inst.dph_total = info.get("dph_total", inst.dph_total)
        inst.geolocation = info.get("geolocation", inst.geolocation)
        inst.ssh_host = info.get("ssh_host", inst.ssh_host) or inst.ssh_host
        inst.ssh_port = int(info.get("ssh_port", inst.ssh_port) or inst.ssh_port or 0)
        inst.label = ours
        registry.upsert(inst)
    print(f"Synced {len(labeled)} labeled instance(s) into the registry.")


def _add_offer_filters(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--gpu", help="GPU name, e.g. RTX_5090")
    sp.add_argument("--machine", type=int, help="Target a specific Vast machine id")
    sp.add_argument("--offer", type=int, help="Target a specific offer id")
    sp.add_argument("--num-gpus", type=int, dest="num_gpus", help="Require N GPUs (with --gpu)")
    sp.add_argument("--region", help="Substring match on geolocation, e.g. US or EU")
    sp.add_argument("--max-price", type=float, dest="max_price", help="Max $/hr")
    sp.add_argument("--min-reliability", type=float, dest="min_reliability", default=0.9)
    sp.add_argument(
        "--min-cuda", type=float, dest="min_cuda",
        help="Min cuda_max_good (default: image CUDA major.minor)",
    )
    sp.add_argument("--rank", choices=["cost", "perf"], default="cost")
    sp.add_argument("--limit", type=int, default=30)


def main() -> None:
    p = argparse.ArgumentParser(
        prog="provision_worker",
        description="Provision and manage a Vast.ai hashcat fleet",
    )
    sub = p.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("search", help="Browse filtered offers")
    _add_offer_filters(ps)
    ps.set_defaults(func=search_cmd)

    pu = sub.add_parser("up", help="Provision instance(s) and add to the fleet")
    _add_offer_filters(pu)
    pu.add_argument("--image", help=f"Worker image (default: {config.image_ref()})")
    pu.add_argument("--disk", type=int, default=config.DEFAULT_DISK_GB, help="Disk GB")
    pu.add_argument("--count", type=int, default=1, help="Provision N instances")
    pu.add_argument("--yes", action="store_true", help="Auto-pick top offer, no prompt")
    pu.add_argument("--no-wait", action="store_true", dest="no_wait")
    pu.set_defaults(func=up_cmd)

    pl = sub.add_parser("ls", help="List the fleet with live status and cost")
    pl.set_defaults(func=ls_cmd)

    pd = sub.add_parser("down", help="Destroy fleet instance(s)")
    pd.add_argument("--instance", type=int)
    pd.add_argument("--all", action="store_true")
    pd.add_argument("--yes", action="store_true")
    pd.set_defaults(func=down_cmd)

    py = sub.add_parser("sync", help="Reconcile the registry from Vast labels")
    py.set_defaults(func=sync_cmd)

    args = p.parse_args()
    try:
        args.func(args)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
