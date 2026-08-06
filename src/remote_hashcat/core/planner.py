"""Budget-constrained fleet planning (pure, unit-tested).

Works on per-offer *total cost for the planned window* (compute + disk over the
duration + one-time network) so the vast-specific cost model lives in the CLI and
this stays a simple knapsack over (num_gpus, cost) items grouped by bundle size.
Same-size offers are drawn cheapest-first, so renting k of a size costs the sum
of that size's k cheapest offers.
"""

from __future__ import annotations

from collections import defaultdict


def _prefix(costs: list[float]) -> list[float]:
    out, acc = [0.0], 0.0
    for c in costs:
        acc += c
        out.append(acc)
    return out  # out[k] = summed cost of the k cheapest


def _by_size(items: list[dict]) -> dict[int, list[float]]:
    g: dict[int, list[float]] = defaultdict(list)
    for it in items:
        n = it.get("num_gpus") or 0
        c = it.get("cost")
        if n > 0 and c is not None:
            g[n].append(float(c))
    for n in g:
        g[n].sort()
    return g


def _entry(shape: dict[int, int], budget: float, cost: float) -> dict:
    return {
        "shape": dict(shape),
        "instances": sum(shape.values()),
        "gpus": sum(s * c for s, c in shape.items()),
        "cost": cost,
        "leftover": budget - cost,
    }


def max_fill_by_size(items: list[dict], budget: float) -> list[dict]:
    """For each bundle size, the most instances of *only* that size that fit."""
    if budget <= 0:
        return []
    g = _by_size(items)
    out = []
    for s in sorted(g):
        pre = _prefix(g[s])
        best = 0
        for k in range(1, len(pre)):
            if pre[k] <= budget + 1e-9:
                best = k
            else:
                break
        if best:
            out.append(_entry({s: best}, budget, pre[best]))
    return out


def best_mixes(items: list[dict], budget: float, max_instances: int = 16, top: int = 6) -> list[dict]:
    """Top compositions across bundle sizes, ranked by total GPUs under budget."""
    if budget <= 0:
        return []
    g = _by_size(items)
    sizes = sorted(g)
    pre = {s: _prefix(g[s]) for s in sizes}
    avail = {s: len(g[s]) for s in sizes}
    results: list[tuple[dict, float]] = []

    def rec(i: int, shape: dict[int, int], cost: float, insts: int) -> None:
        if i == len(sizes):
            if shape:
                results.append((dict(shape), cost))
            return
        s = sizes[i]
        cap = min(avail[s], max_instances - insts)
        for k in range(0, cap + 1):
            c = pre[s][k]
            if cost + c > budget + 1e-9:
                break
            nxt = dict(shape)
            if k > 0:
                nxt[s] = k
            rec(i + 1, nxt, cost + c, insts + k)

    rec(0, {}, 0.0, 0)
    results.sort(key=lambda r: (
        -sum(s * c for s, c in r[0].items()), r[1], sum(r[0].values())
    ))
    out, seen = [], set()
    for shape, cost in results:
        sig = tuple(sorted(shape.items()))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(_entry(shape, budget, cost))
        if len(out) >= top:
            break
    return out


def format_shape(shape: dict[int, int]) -> str:
    """{8:1, 4:2} -> '1x 8-GPU, 2x 4-GPU' (largest bundle first)."""
    return ", ".join(f"{c}x {s}-GPU" for s, c in sorted(shape.items(), reverse=True))
