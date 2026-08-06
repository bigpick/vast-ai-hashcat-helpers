from remote_hashcat.core.jobs import JobSpec


def test_hashcat_argv_basic():
    spec = JobSpec(
        jobid="j1",
        hash_remote="/root/jobs/j1/h.txt",
        wordlists_remote=["/root/wordlists/rockyou.txt"],
        mode="22000",
    )
    argv = spec.hashcat_argv()
    assert argv[0] == "hashcat"
    assert argv[argv.index("-m") + 1] == "22000"
    assert "job-j1" in argv
    assert argv[argv.index("--potfile-path") + 1] == "/root/jobs/j1/hashcat.potfile"
    # hashfile is positional, before the wordlist
    assert argv.index("/root/jobs/j1/h.txt") < argv.index("/root/wordlists/rockyou.txt")
    assert argv[-1] == "/root/wordlists/rockyou.txt"


def test_hashcat_argv_rules_and_passthrough():
    spec = JobSpec(
        jobid="j2",
        hash_remote="/r/h",
        wordlists_remote=["/w/list"],
        rules_remote=["/root/rules/best64.rule"],
        mode="0",
        extra=["-O", "-w", "4"],
    )
    argv = spec.hashcat_argv()
    assert "/root/rules/best64.rule" in argv
    assert argv[argv.index("/root/rules/best64.rule") - 1] == "-r"
    assert "-O" in argv and argv[argv.index("-w") + 1] == "4"
    # rule (option) before hashfile before wordlist
    assert argv.index("/root/rules/best64.rule") < argv.index("/r/h") < argv.index("/w/list")


def test_launch_command_detaches_and_records_exit():
    cmd = JobSpec(jobid="j3", hash_remote="/r/h", wordlists_remote=["/w/l"]).launch_command()
    assert "mkdir -p" in cmd
    assert "setsid bash -c" in cmd
    assert "echo $? > exitcode" in cmd
    assert "job-j3" in cmd
