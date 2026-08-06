from remote_hashcat.core import planner


def _items():
    # (num_gpus, cost) where cost is the total for the planned window
    return [
        {"num_gpus": 2, "cost": 0.20}, {"num_gpus": 2, "cost": 0.30},
        {"num_gpus": 4, "cost": 0.40}, {"num_gpus": 4, "cost": 0.50},
        {"num_gpus": 8, "cost": 1.00},
    ]


def test_max_fill_by_size_counts_and_cost():
    by = {list(o["shape"])[0]: o for o in planner.max_fill_by_size(_items(), budget=1.0)}
    assert by[2]["instances"] == 2 and by[2]["gpus"] == 4
    assert by[4]["instances"] == 2 and by[4]["gpus"] == 8
    assert by[8]["instances"] == 1 and by[8]["gpus"] == 8
    assert abs(by[4]["cost"] - 0.9) < 1e-9


def test_best_mixes_maximizes_gpus_under_budget():
    out = planner.best_mixes(_items(), budget=1.0, max_instances=16, top=5)
    assert out
    top = out[0]
    assert top["gpus"] == 8
    assert top["cost"] <= 1.0 + 1e-9
    # cheapest 8-GPU shape is $0.9 (2x 4-GPU), not the $1.0 single 8x
    assert abs(top["cost"] - 0.9) < 1e-9


def test_respects_max_instances():
    items = [{"num_gpus": 1, "cost": 0.10} for _ in range(20)]
    out = planner.best_mixes(items, budget=100, max_instances=3, top=3)
    assert out[0]["instances"] <= 3
    assert out[0]["gpus"] == 3


def test_zero_budget_is_empty():
    assert planner.best_mixes(_items(), 0) == []
    assert planner.max_fill_by_size(_items(), 0) == []


def test_format_shape_largest_first():
    assert planner.format_shape({8: 1, 4: 2}) == "1x 8-GPU, 2x 4-GPU"
