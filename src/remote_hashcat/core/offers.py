"""Offer query building, client-side filtering, ranking, and the picker.

Filtering is done client-side (rather than in the Vast query string) so we never
depend on fragile query-operator syntax for geolocation/price/reliability.
"""

from __future__ import annotations


def build_query(gpu: str | None = None, num_gpus: int | None = None) -> str:
    parts: list[str] = []
    if gpu:
        parts.append(f"gpu_name={gpu.replace(' ', '_')}")
    if num_gpus:
        parts.append(f"num_gpus={num_gpus}")
    parts.append("rentable=true")
    return " ".join(parts)


def apply_filters(
    offers: list[dict],
    *,
    region: str | None = None,
    max_price: float | None = None,
    min_reliability: float = 0.9,
    min_ram_mb: int = 16384,
    min_cpu_cores: int = 4,
    min_cuda: float = 0.0,
    datacenter: bool | None = None,
    min_inet_down: float = 0.0,
) -> list[dict]:
    out = []
    for o in offers:
        if datacenter and not o.get("datacenter"):
            continue
        if (o.get("inet_down") or 0) < min_inet_down:
            continue
        if o.get("reliability", 0) < min_reliability:
            continue
        if o.get("cpu_ram", 0) < min_ram_mb:
            continue
        if o.get("cpu_cores_effective", 0) < min_cpu_cores:
            continue
        if o.get("cuda_max_good", 0) < min_cuda:
            continue
        if max_price is not None and o.get("dph_total", float("inf")) > max_price:
            continue
        if region and region.lower() not in str(o.get("geolocation", "")).lower():
            continue
        out.append(o)
    return out


def rank(offers: list[dict], mode: str = "cost") -> list[dict]:
    offers = list(offers)
    if mode == "perf":
        return sorted(offers, key=lambda o: o.get("dlperf_per_dphtotal", 0), reverse=True)
    # cost (default): cheapest per hour
    return sorted(offers, key=lambda o: o.get("dph_total", float("inf")))


def format_offer(o: dict, idx: int | None = None) -> str:
    prefix = f"[{idx}] " if idx is not None else ""
    gpu = f"{o.get('num_gpus', '?')}x {o.get('gpu_name', '?')}"
    return (
        f"{prefix}id {str(o.get('id', '?')):>9}  "
        f"{gpu:<20}  "
        f"${o.get('dph_total', 0):.3f}/hr  "
        f"CUDA {o.get('cuda_max_good', '?')}  "
        f"{int(o.get('cpu_ram', 0) / 1024)}GB  "
        f"rel {o.get('reliability', 0):.0%}  "
        f"{o.get('geolocation', '?')}"
    )


def pick(offers: list[dict], *, auto: bool = False) -> dict | None:
    if not offers:
        return None
    if auto or len(offers) == 1:
        return offers[0]
    top = offers[:20]
    for i, o in enumerate(top, 1):
        print("  " + format_offer(o, i))
    choice = input(f"  Pick [1-{len(top)}] or Enter for #1: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(top):
        return top[int(choice) - 1]
    return top[0]
