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
        datacenter=(True if getattr(args, "datacenter", False) else None),
        min_inet_down=getattr(args, "min_down", 0.0) or 0.0,
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


def plan_cmd(args) -> None:
    from collections import defaultdict

    from remote_hashcat.core import planner

    provider = _provider()
    found = provider.search_offers(offers_mod.build_query(gpu=args.gpu), limit=max(args.limit, 200))
    min_cuda = args.min_cuda if args.min_cuda is not None else config.cuda_major_minor()
    pool = offers_mod.apply_filters(
        found, region=args.region, max_price=args.max_price,
        min_reliability=args.min_reliability, min_cuda=min_cuda,
        datacenter=(True if getattr(args, "datacenter", False) else None),
        min_inet_down=getattr(args, "min_down", 0.0) or 0.0,
    )
    if not pool:
        print(f"No {args.gpu} offers matched ({len(found)} before filters).")
        return

    # Price each offer for the WHOLE window: compute + disk (per-host $/GB/month,
    # prorated over the hours) + one-time network (per-host $/GB).
    priced = []
    for o in pool:
        n = o.get("num_gpus") or 0
        if n <= 0:
            continue
        base = o.get("dph_base")
        if base is None:
            base = o.get("dph_total", 0.0)
        storage = o.get("storage_cost") or 0.0                       # $/GB/month
        inet = o.get("inet_down_cost")
        if inet is None:
            inet = (o.get("internet_down_cost_per_tb") or 0.0) / 1024.0  # $/GB
        hourly = base + storage * args.disk / 730.0
        window = hourly * args.hours + args.xfer_gb * inet
        priced.append({
            "num_gpus": n, "cost": window, "hourly": hourly, "id": o.get("id"),
            "machine_id": o.get("machine_id"),
            "reliability": o.get("reliability") or 0.0,
            "dlperf": o.get("dlperf") or 0.0,
            "inet_down": o.get("inet_down") or 0.0,
            "inet_up": o.get("inet_up") or 0.0,
            "geo": str(o.get("geolocation") or "").strip().lstrip(", ").strip(),
        })

    groups = defaultdict(list)
    for it in priced:
        groups[it["num_gpus"]].append(it)
    for s in groups:
        groups[s].sort(key=lambda x: x["cost"])
    summary = ", ".join(f"{s}-GPU:{len(groups[s])}" for s in sorted(groups))

    print(f"Plan · {args.gpu} · ${args.budget:.0f} budget · {args.hours:g}h · {args.disk} GB disk")
    print(f"{len(priced)} offers ({summary})")
    print(f"cost = compute + {args.disk} GB disk over {args.hours:g}h + {args.xfer_gb:g} GB network/instance "
          f"(default ≈ image pull; add wordlist GB with --xfer-gb)")

    fills = planner.max_fill_by_size(priced, args.budget)
    mixes = planner.best_mixes(priced, args.budget, args.max_instances, top=6)
    options, seen = [], set()
    for opt in mixes + sorted(fills, key=lambda x: -x["gpus"]):
        sig = tuple(sorted(opt["shape"].items()))
        if sig not in seen:
            seen.add(sig)
            options.append(opt)
    options.sort(key=lambda o: (-o["gpus"], o["cost"]))
    options = options[:8]
    if not options:
        print("\nNothing fits. Raise --budget, lower --disk, or pick a cheaper GPU.")
        return

    labels = "ABCDEFGH"
    print(f"\n  #   GPUs  inst  {'shape':<30} {'cost':>9}  {'left':>8}")
    for i, o in enumerate(options):
        tag = "  <- most GPUs" if i == 0 else ""
        print(f"  {labels[i]}  {o['gpus']:>4}  {o['instances']:>4}  "
              f"{planner.format_shape(o['shape']):<30} ${o['cost']:>7.2f}  ${o['leftover']:>6.2f}{tag}")

    pick = (args.emit or "A").strip().upper()
    idx = labels.index(pick) if pick in labels[:len(options)] else 0
    chosen = options[idx]
    print(f"\nProvision option {labels[idx]}  ({chosen['gpus']} GPUs, ${chosen['cost']:.2f}/{args.hours:g}h):")
    machine_ids = []
    for s in sorted(chosen["shape"], reverse=True):
        for it in groups[s][:chosen["shape"][s]]:
            machine_ids.append(it["machine_id"])
            print(f"  just up --offer {it['id']} --disk {args.disk}"
                  f"   # {s}-GPU ${it['hourly']:.3f}/hr | machine {it['machine_id']}"
                  f" | rel {it['reliability'] * 100:.1f}% | dlperf {it['dlperf']:.0f}"
                  f" | net {it['inet_down']:.0f}/{it['inet_up']:.0f} Mbps | {it['geo']}")
    print("Offer IDs are live snapshots — provision soon (they get rented).")
    ids_csv = ",".join(str(m) for m in machine_ids if m)
    if ids_csv:
        print("\nInspect these machines — paste into the vast console search box, or run:")
        print(f"  vastai search offers 'machine_id in [{ids_csv}]'")


def _add_offer_filters(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--gpu", help="GPU name, e.g. RTX_5090")
    sp.add_argument("--machine", type=int, help="Target a specific Vast machine id")
    sp.add_argument("--offer", type=int, help="Target a specific offer id")
    sp.add_argument("--num-gpus", type=int, dest="num_gpus", help="Require N GPUs (with --gpu)")
    sp.add_argument("--region", help="Substring match on geolocation, e.g. US or EU")
    sp.add_argument("--max-price", type=float, dest="max_price", help="Max $/hr")
    sp.add_argument("--min-reliability", type=float, dest="min_reliability", default=0.9,
                    help="Min reliability 0..1 (e.g. 0.99 = 99%%)")
    sp.add_argument("--secure", action="store_true", dest="datacenter",
                    help="Secure Cloud only (vast datacenter-hosted machines)")
    sp.add_argument("--min-down", type=float, dest="min_down", default=0.0,
                    help="Min instance download Mbps (matters for pushing image/wordlists)")
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

    ppl = sub.add_parser("plan", help="Budget-constrained fleet suggestions (read-only)")
    ppl.add_argument("--gpu", required=True, help="GPU name, e.g. RTX_4090")
    ppl.add_argument("--budget", type=float, required=True, help="Total budget in $")
    ppl.add_argument("--hours", type=float, required=True, help="Session length in hours")
    ppl.add_argument("--disk", type=int, default=config.DEFAULT_DISK_GB,
                     help=f"Disk GB per instance, priced in (default {config.DEFAULT_DISK_GB})")
    ppl.add_argument("--xfer-gb", type=float, dest="xfer_gb", default=17.0,
                     help="Est. GB moved per instance (default 17 ~ image pull; add wordlist GB)")
    ppl.add_argument("--emit", default="A", help="Which option's `up` commands to print (A, B, ...)")
    ppl.add_argument("--region", help="Substring match on geolocation")
    ppl.add_argument("--min-reliability", type=float, dest="min_reliability", default=0.9,
                     help="Min reliability 0..1 (e.g. 0.99 = 99%%)")
    ppl.add_argument("--secure", action="store_true", dest="datacenter",
                     help="Secure Cloud only (vast datacenter-hosted machines)")
    ppl.add_argument("--min-down", type=float, dest="min_down", default=0.0,
                     help="Min instance download Mbps (matters for pushing image/wordlists)")
    ppl.add_argument("--min-cuda", type=float, dest="min_cuda",
                     help="Min cuda_max_good (default: image CUDA)")
    ppl.add_argument("--max-price", type=float, dest="max_price",
                     help="Optional per-instance $/hr cap")
    ppl.add_argument("--max-instances", type=int, dest="max_instances", default=16)
    ppl.add_argument("--limit", type=int, default=200)
    ppl.set_defaults(func=plan_cmd)

    args = p.parse_args()
    try:
        args.func(args)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
