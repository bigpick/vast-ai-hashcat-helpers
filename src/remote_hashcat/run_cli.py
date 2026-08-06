"""`remote_hashcat` — dispatch hashcat jobs and move files to/from fleet instances.

A job runs detached on the worker (under hashcat's own `--session`) and is driven
entirely through this tool over SSH — no tmux/screen. `run` streams live status
and auto-pulls the potfile when the job ends; Ctrl-C only stops watching.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


class _TargetAction(argparse.Action):
    """Collect --wordlist/--maskfile/--mask into one ordered list (args.targets),
    preserving cross-flag order so hybrid attacks (-a 6/-a 7) compose correctly."""

    def __init__(self, option_strings, dest, kind=None, **kwargs):
        self._kind = kind
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        items = list(getattr(namespace, "targets", None) or [])
        items.append((self._kind, values))
        namespace.targets = items


# --- file transfer ---------------------------------------------------------

def _split_send(paths: list[str]) -> tuple[list[str], str]:
    if len(paths) == 1:
        return paths, "/root/"
    return paths[:-1], paths[-1]


def _split_receive(paths: list[str]) -> tuple[list[str], str]:
    if len(paths) == 1:
        return paths, "."
    return paths[:-1], paths[-1]


def send_cmd(args) -> None:
    from remote_hashcat.core.transport import SSHTransport

    t = SSHTransport.for_instance(args.instance)
    sources, dest = _split_send(args.paths)
    print(f"-> sending to instance [{args.instance}] root@{t.host}:{dest}")
    sys.exit(t.run(t.send_argv(sources, dest)))


def receive_cmd(args) -> None:
    from remote_hashcat.core.transport import SSHTransport

    t = SSHTransport.for_instance(args.instance)
    sources, dest = _split_receive(args.paths)
    print(f"<- receiving from instance [{args.instance}] into {dest}")
    sys.exit(t.run(t.receive_argv(sources, dest)))


# --- job status helpers (pure, unit-tested) --------------------------------

def parse_status(line: str) -> dict | None:
    try:
        d = json.loads(line)
    except Exception:
        return None
    rec = d.get("recovered_hashes") or [0, 0]
    prog = d.get("progress") or [0, 0]
    speed = sum(dev.get("speed", 0) for dev in d.get("devices", []))
    pct = (100.0 * prog[0] / prog[1]) if prog[1] else 0.0
    return {"status": d.get("status"), "cracked": rec[0], "total": rec[1],
            "pct": pct, "speed": speed}


def fmt_speed(h: float) -> str:
    for unit in ("H/s", "kH/s", "MH/s", "GH/s", "TH/s"):
        if h < 1000:
            return f"{h:.1f} {unit}"
        h /= 1000
    return f"{h:.1f} PH/s"


# --- run / follow / status / pull / stop -----------------------------------

def _transport_and_job(args):
    from remote_hashcat.core.transport import SSHTransport
    from remote_hashcat.core.fleet import FleetRegistry

    registry = FleetRegistry()
    t = SSHTransport.for_instance(args.instance, registry=registry)
    return t, registry


def _current_jobid(registry, instance: int) -> str:
    inst = registry.get(instance)
    if inst is None or not inst.current_job:
        raise RuntimeError(f"No active job recorded for instance [{instance}].")
    return inst.current_job


def run_cmd(args) -> None:
    from remote_hashcat.core import jobs

    t, registry = _transport_and_job(args)
    jobid = args.session or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    jobdir = f"{jobs.REMOTE_JOBS_DIR}/{jobid}"
    hash_remote = f"{jobdir}/{Path(args.hashfile).name}"

    if t.run(t.exec_argv(
        f"mkdir -p {jobdir} {jobs.REMOTE_WORDLIST_DIR} {jobs.REMOTE_RULES_DIR} {jobs.REMOTE_MASK_DIR}"
    )) != 0:
        print("error: could not prepare remote dirs", file=sys.stderr)
        sys.exit(1)

    print(f"Pushing inputs to instance [{args.instance}] ...")
    if t.run(t.send_argv([args.hashfile], f"{jobdir}/")) != 0:
        print("error: failed to send hashfile", file=sys.stderr)
        sys.exit(1)

    # Attack inputs, in the order given: --wordlist/--maskfile push a local file,
    # --mask is a literal. Together they become the positionals after the hashfile.
    positionals = []
    for kind, val in getattr(args, "targets", None) or []:
        if kind == "mask":
            positionals.append(val)
            continue
        remote_dir = jobs.REMOTE_WORDLIST_DIR if kind == "wordlist" else jobs.REMOTE_MASK_DIR
        if t.run(t.send_argv([val], f"{remote_dir}/")) != 0:
            print(f"error: failed to send {kind} {val}", file=sys.stderr)
            sys.exit(1)
        positionals.append(f"{remote_dir}/{Path(val).name}")

    rules_remote = []
    for r in args.rules or []:
        t.run(t.send_argv([r], f"{jobs.REMOTE_RULES_DIR}/"))
        rules_remote.append(f"{jobs.REMOTE_RULES_DIR}/{Path(r).name}")

    extra = list(getattr(args, "extra", []) or [])
    if extra and extra[0] == "--":
        extra = extra[1:]

    spec = jobs.JobSpec(
        jobid=jobid, hash_remote=hash_remote, positionals=positionals,
        rules_remote=rules_remote, mode=args.mode, attack=args.attack,
        outfile_format=args.outfile_format, extra=extra,
    )
    print(f"Launching hashcat (session {jobid}) ...")
    t.run(t.exec_argv(spec.launch_command()))

    inst = registry.get(args.instance)
    if inst is not None:
        inst.current_job = jobid
        registry.upsert(inst)

    if args.detach:
        print(f"Detached. `remote_hashcat follow --instance {args.instance}` to watch, "
              f"`pull --instance {args.instance}` for the potfile.")
        return
    _stream(t, args.instance, jobdir)
    _pull(t, args.instance, jobdir, args.potfile_path)


def _probe(t, jobdir: str) -> tuple[str, dict | None]:
    cmd = (
        f"cat {jobdir}/exitcode 2>/dev/null; echo '<<<SEP>>>'; "
        f"grep -a '\"progress\"' {jobdir}/run.log 2>/dev/null | tail -1"
    )
    out = subprocess.run(t.exec_argv(cmd), capture_output=True, text=True).stdout
    exitcode_part, _, json_part = out.partition("<<<SEP>>>")
    return exitcode_part.strip(), parse_status(json_part.strip())


def _stream(t, instance: int, jobdir: str) -> None:
    start = time.time()
    print("Streaming status (Ctrl-C detaches; the job keeps running)...")
    try:
        while True:
            exitcode, st = _probe(t, jobdir)
            elapsed = int(time.time() - start)
            if st:
                print(f"  [{elapsed}s] recovered {st['cracked']}/{st['total']} | "
                      f"{st['pct']:.1f}% | {fmt_speed(st['speed'])}        ", end="\r")
            else:
                print(f"  [{elapsed}s] starting...        ", end="\r")
            if exitcode != "":
                print(f"\nJob finished (hashcat exit {exitcode}).")
                return
            time.sleep(5)
    except KeyboardInterrupt:
        print(f"\nDetached. `remote_hashcat pull --instance {instance}` when ready.")
        raise SystemExit(0)


def _pull(t, instance: int, jobdir: str, potfile_path: str | None) -> None:
    dest = Path(potfile_path) if potfile_path else Path(f"./potfiles/instance-{instance}.potfile")
    dest.parent.mkdir(parents=True, exist_ok=True)

    has_pot = subprocess.run(
        t.exec_argv(f"test -s {jobdir}/hashcat.potfile && echo yes || echo no"),
        capture_output=True, text=True,
    ).stdout.strip()

    if has_pot == "yes":
        print(f"Pulling potfile -> {dest}")
        t.run(t.receive_argv([f"{jobdir}/hashcat.potfile"], str(dest)))
        n = sum(1 for _ in dest.open()) if dest.exists() and dest.stat().st_size else 0
        print(f"Done. {n} cracked line(s) in {dest}")
    else:
        print("Done. No potfile yet — nothing cracked.")
    # Best-effort: also grab cracked list + run log next to the potfile.
    t.run(t.receive_argv([f"{jobdir}/cracked.txt", f"{jobdir}/run.log"], str(dest.parent) + "/"))


def follow_cmd(args) -> None:
    from remote_hashcat.core import jobs

    t, registry = _transport_and_job(args)
    jobid = _current_jobid(registry, args.instance)
    jobdir = f"{jobs.REMOTE_JOBS_DIR}/{jobid}"
    _stream(t, args.instance, jobdir)
    _pull(t, args.instance, jobdir, args.potfile_path)


def status_cmd(args) -> None:
    from remote_hashcat.core import jobs

    t, registry = _transport_and_job(args)
    jobid = _current_jobid(registry, args.instance)
    jobdir = f"{jobs.REMOTE_JOBS_DIR}/{jobid}"
    exitcode, st = _probe(t, jobdir)
    state = "finished (exit " + exitcode + ")" if exitcode != "" else "running"
    if st:
        print(f"[{args.instance}] job {jobid}: {state} | recovered {st['cracked']}/{st['total']} "
              f"| {st['pct']:.1f}% | {fmt_speed(st['speed'])}")
    else:
        print(f"[{args.instance}] job {jobid}: {state} (no status yet)")


def pull_cmd(args) -> None:
    from remote_hashcat.core import jobs

    t, registry = _transport_and_job(args)
    jobid = _current_jobid(registry, args.instance)
    _pull(t, args.instance, f"{jobs.REMOTE_JOBS_DIR}/{jobid}", args.potfile_path)


def stop_cmd(args) -> None:
    t, registry = _transport_and_job(args)
    jobid = _current_jobid(registry, args.instance)
    # SIGINT lets hashcat checkpoint before exiting.
    t.run(t.exec_argv(f"pkill -INT -f 'job-{jobid}' || true"))
    print(f"Sent stop (SIGINT) to job {jobid} on instance [{args.instance}].")


def main() -> None:
    p = argparse.ArgumentParser(
        prog="remote_hashcat",
        description="Move files to/from fleet instances and run hashcat jobs",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("run", help="Push inputs, run detached hashcat, stream, pull potfile")
    pr.add_argument("--instance", type=int, required=True)
    pr.add_argument("--hashfile", required=True)
    pr.add_argument("-m", "--mode", help="hashcat -m hash mode")
    pr.add_argument("-a", "--attack", default="0", help="hashcat -a attack mode (default 0)")
    pr.add_argument("--wordlist", action=_TargetAction, kind="wordlist", metavar="FILE",
                    help="dict file, pushed (repeatable; order kept with --mask/--maskfile)")
    pr.add_argument("--maskfile", action=_TargetAction, kind="maskfile", metavar="FILE",
                    help="mask/.hcmask file, pushed")
    pr.add_argument("--mask", action=_TargetAction, kind="mask", metavar="MASK",
                    help="literal mask, e.g. '?d?d?d?d' (for -a 3/6/7)")
    pr.add_argument("--rules", action="append", metavar="FILE",
                    help="rules file, pushed (repeatable; -a 0)")
    pr.add_argument("--potfile-path", dest="potfile_path", help="host destination for the potfile")
    pr.add_argument("--outfile-format", dest="outfile_format", default="2")
    pr.add_argument("--session", help="session/job id (default: UTC timestamp)")
    pr.add_argument("--detach", action="store_true", help="launch and return, don't stream")
    pr.set_defaults(func=run_cmd)

    pf = sub.add_parser("follow", help="Re-stream the current job's status")
    pf.add_argument("--instance", type=int, required=True)
    pf.add_argument("--potfile-path", dest="potfile_path")
    pf.set_defaults(func=follow_cmd)

    pst = sub.add_parser("status", help="One-shot progress for the current job")
    pst.add_argument("--instance", type=int, required=True)
    pst.set_defaults(func=status_cmd)

    pp = sub.add_parser("pull", help="Pull the potfile (+ cracked/log) for the current job")
    pp.add_argument("--instance", type=int, required=True)
    pp.add_argument("--potfile-path", dest="potfile_path")
    pp.set_defaults(func=pull_cmd)

    psp = sub.add_parser("stop", help="Gracefully stop the current job (SIGINT)")
    psp.add_argument("--instance", type=int, required=True)
    psp.set_defaults(func=stop_cmd)

    psnd = sub.add_parser("send", help="rsync local files TO an instance")
    psnd.add_argument("--instance", type=int, required=True)
    psnd.add_argument("paths", nargs="+", help="LOCAL... [REMOTE_DEST] (default /root/)")
    psnd.set_defaults(func=send_cmd)

    prcv = sub.add_parser("receive", help="rsync files FROM an instance")
    prcv.add_argument("--instance", type=int, required=True)
    prcv.add_argument("paths", nargs="+", help="REMOTE... [LOCAL_DEST] (default .)")
    prcv.set_defaults(func=receive_cmd)

    args, extra = p.parse_known_args()
    args.extra = extra  # extra tokens (after `--`) pass through to hashcat on `run`
    try:
        args.func(args)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
