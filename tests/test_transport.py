from pathlib import Path

import pytest

from remote_hashcat.core.transport import SSHTransport


def _t() -> SSHTransport:
    return SSHTransport(host="1.2.3.4", port=2222, key_path=Path("/home/u/.ssh/id_ed25519"))


def test_send_argv_multi_source():
    argv = _t().send_argv(["a.gz", "b.gz"], "/root/wordlists")
    assert argv[0] == "rsync"
    assert argv[-1] == "root@1.2.3.4:/root/wordlists"
    assert "a.gz" in argv and "b.gz" in argv
    e = argv[argv.index("-e") + 1]
    assert "-p 2222" in e and "id_ed25519" in e


def test_receive_argv_prefixes_remote_sources():
    argv = _t().receive_argv(["/root/jobs/x/hashcat.potfile"], "./potfiles/")
    assert argv[-1] == "./potfiles/"
    assert "root@1.2.3.4:/root/jobs/x/hashcat.potfile" in argv


def test_exec_argv_targets_root():
    argv = _t().exec_argv("nvidia-smi -L")
    assert argv[0] == "ssh"
    assert argv[-1] == "nvidia-smi -L"
    assert "root@1.2.3.4" in argv


def test_missing_endpoint_raises():
    with pytest.raises(RuntimeError):
        SSHTransport(host="", port=0, key_path=Path("/x"))
