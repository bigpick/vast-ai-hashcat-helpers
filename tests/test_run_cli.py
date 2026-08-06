from remote_hashcat.run_cli import (
    fmt_speed,
    parse_status,
    _split_receive,
    _split_send,
)


def test_parse_status_valid():
    line = (
        '{"status":3,"progress":[50,100],"recovered_hashes":[2,10],'
        '"devices":[{"speed":1000},{"speed":500}]}'
    )
    st = parse_status(line)
    assert st["cracked"] == 2
    assert st["total"] == 10
    assert st["pct"] == 50.0
    assert st["speed"] == 1500


def test_parse_status_rejects_garbage():
    assert parse_status("not json") is None
    assert parse_status("") is None


def test_fmt_speed_units():
    assert fmt_speed(500) == "500.0 H/s"
    assert fmt_speed(1500).endswith("kH/s")
    assert fmt_speed(2_000_000).endswith("MH/s")


def test_split_send_defaults_to_root():
    assert _split_send(["a"]) == (["a"], "/root/")
    assert _split_send(["a", "b", "/dest"]) == (["a", "b"], "/dest")


def test_split_receive_defaults_to_cwd():
    assert _split_receive(["a"]) == (["a"], ".")
    assert _split_receive(["r1", "r2", "./here"]) == (["r1", "r2"], "./here")


def test_target_action_preserves_cross_flag_order():
    import argparse

    from remote_hashcat.run_cli import _TargetAction

    p = argparse.ArgumentParser()
    p.add_argument("--wordlist", action=_TargetAction, kind="wordlist")
    p.add_argument("--maskfile", action=_TargetAction, kind="maskfile")
    p.add_argument("--mask", action=_TargetAction, kind="mask")
    ns = p.parse_args(["--mask", "?d?d", "--wordlist", "rockyou.txt", "--mask", "?l"])
    assert ns.targets == [("mask", "?d?d"), ("wordlist", "rockyou.txt"), ("mask", "?l")]
