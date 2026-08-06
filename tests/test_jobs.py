from remote_hashcat.core.jobs import JobSpec


def test_hashcat_argv_wordlist_a0():
    spec = JobSpec(
        jobid="j1", hash_remote="/root/jobs/j1/h.txt",
        positionals=["/root/wordlists/rockyou.txt"], mode="22000",
    )
    argv = spec.hashcat_argv()
    assert argv[0] == "hashcat"
    assert argv[argv.index("-m") + 1] == "22000"
    assert "job-j1" in argv
    assert argv[argv.index("--potfile-path") + 1] == "/root/jobs/j1/hashcat.potfile"
    # hashfile precedes the dict; dict is the last token
    assert argv.index("/root/jobs/j1/h.txt") < argv.index("/root/wordlists/rockyou.txt")
    assert argv[-1] == "/root/wordlists/rockyou.txt"


def test_hashcat_argv_rules_and_passthrough():
    spec = JobSpec(
        jobid="j2", hash_remote="/r/h", positionals=["/w/list"],
        rules_remote=["/root/rules/best64.rule"], mode="0", extra=["-O", "-w", "4"],
    )
    argv = spec.hashcat_argv()
    assert argv[argv.index("/root/rules/best64.rule") - 1] == "-r"
    assert "-O" in argv and argv[argv.index("-w") + 1] == "4"
    # rule (option) before hashfile before dict (positional)
    assert argv.index("/root/rules/best64.rule") < argv.index("/r/h") < argv.index("/w/list")


def test_hashcat_argv_mask_a3():
    spec = JobSpec(jobid="j3", hash_remote="/r/h", positionals=["?d?d?d?d"], attack="3", mode="0")
    argv = spec.hashcat_argv()
    assert argv[argv.index("-a") + 1] == "3"
    assert argv.index("/r/h") < argv.index("?d?d?d?d")  # hashfile then literal mask
    assert argv[-1] == "?d?d?d?d"


def test_hashcat_argv_hybrid_preserves_positional_order():
    # -a 6 = dict + mask; the positional order must survive verbatim
    spec = JobSpec(
        jobid="j4", hash_remote="/r/h",
        positionals=["/root/wordlists/w.txt", "?d?d"], attack="6", mode="0",
    )
    argv = spec.hashcat_argv()
    assert argv[-2:] == ["/root/wordlists/w.txt", "?d?d"]


def test_launch_command_detaches_and_records_exit():
    cmd = JobSpec(jobid="j5", hash_remote="/r/h", positionals=["/w/l"]).launch_command()
    assert "mkdir -p" in cmd
    assert "setsid bash -c" in cmd
    assert "echo $? > exitcode" in cmd
    assert "job-j5" in cmd
