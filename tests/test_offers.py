from remote_hashcat.core import offers


def _o(**kw):
    base = dict(
        id=1, dph_total=1.0, reliability=0.99, cpu_ram=64000,
        cpu_cores_effective=16, cuda_max_good=13.0, geolocation="US",
        num_gpus=1, gpu_name="RTX_5090",
    )
    base.update(kw)
    return base


def test_build_query_gpu():
    assert offers.build_query(gpu="RTX 5090", num_gpus=8) == (
        "gpu_name=RTX_5090 num_gpus=8 rentable=true"
    )


def test_build_query_default():
    assert offers.build_query() == "rentable=true"


def test_apply_filters_cuda():
    out = offers.apply_filters([_o(cuda_max_good=12.0), _o(cuda_max_good=13.0)], min_cuda=12.9)
    assert [o["cuda_max_good"] for o in out] == [13.0]


def test_apply_filters_region_and_price():
    out = offers.apply_filters(
        [_o(geolocation="US", dph_total=2.0), _o(geolocation="DE", dph_total=1.0)],
        region="us", max_price=3.0,
    )
    assert [o["geolocation"] for o in out] == ["US"]


def test_apply_filters_reliability():
    out = offers.apply_filters([_o(reliability=0.5), _o(reliability=0.99)], min_reliability=0.9)
    assert len(out) == 1


def test_rank_cost():
    ranked = offers.rank([_o(id=1, dph_total=2.0), _o(id=2, dph_total=1.0)], "cost")
    assert [o["id"] for o in ranked] == [2, 1]


def test_rank_perf():
    ranked = offers.rank(
        [_o(id=1, dlperf_per_dphtotal=10), _o(id=2, dlperf_per_dphtotal=20)], "perf"
    )
    assert [o["id"] for o in ranked] == [2, 1]
