"""Compose and launch detached hashcat jobs on a fleet instance.

Command composition (pure, unit-tested) is separate from execution. A job runs
detached via `setsid` under hashcat's own `--session`, so it survives SSH drops;
the tool interacts with it entirely over SSH (no tmux/screen).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

REMOTE_JOBS_DIR = "/root/jobs"
REMOTE_WORDLIST_DIR = "/root/wordlists"
REMOTE_RULES_DIR = "/root/rules"
REMOTE_MASK_DIR = "/root/masks"


@dataclass
class JobSpec:
    jobid: str
    hash_remote: str
    # Ordered tokens placed AFTER the hashfile: dict / maskfile paths and literal
    # masks. This makes -a 0/1/3/6/7 all expressible (dict, mask, dict+mask, ...).
    positionals: list[str] = field(default_factory=list)
    rules_remote: list[str] = field(default_factory=list)
    mode: str | None = None          # hashcat -m
    attack: str = "0"                # hashcat -a
    outfile_format: str = "2"        # 2 = plain
    extra: list[str] = field(default_factory=list)  # passthrough hashcat options

    def job_dir(self) -> str:
        return f"{REMOTE_JOBS_DIR}/{self.jobid}"

    def hashcat_argv(self) -> list[str]:
        d = self.job_dir()
        argv = ["hashcat"]
        if self.mode is not None:
            argv += ["-m", str(self.mode)]
        argv += ["-a", str(self.attack)]
        argv += [
            "--session", f"job-{self.jobid}",
            "--potfile-path", f"{d}/hashcat.potfile",
            "--outfile", f"{d}/cracked.txt",
            "--outfile-format", str(self.outfile_format),
            "--restore-file-path", f"{d}/hc.restore",
            "--status", "--status-json", "--status-timer", "5",
        ]
        for rule in self.rules_remote:
            argv += ["-r", rule]
        argv += self.extra
        argv.append(self.hash_remote)           # positional hashfile
        argv += self.positionals                 # dict / mask / maskfile, in order
        return argv

    def launch_command(self) -> str:
        """One remote shell line: make the job dir, detach hashcat, record exit."""
        d = self.job_dir()
        hc = " ".join(shlex.quote(a) for a in self.hashcat_argv())
        inner = f"cd {shlex.quote(d)}; {hc} >run.log 2>&1; echo $? > exitcode"
        return (
            f"mkdir -p {shlex.quote(d)}; "
            f"setsid bash -c {shlex.quote(inner)} </dev/null >/dev/null 2>&1 &"
        )
