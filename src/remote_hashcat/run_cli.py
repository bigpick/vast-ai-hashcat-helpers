"""`remote_hashcat` — move files to/from fleet instances and (phase 2) run jobs.

`send`/`receive` are implemented now (rsync over SSH via the fleet registry).
`run` (detached hashcat + potfile pull) lands next.
"""

from __future__ import annotations

import argparse
import sys


def _split_send(paths: list[str]) -> tuple[list[str], str]:
    # LOCAL... [REMOTE_DEST]; a lone path defaults to the instance home.
    if len(paths) == 1:
        return paths, "/root/"
    return paths[:-1], paths[-1]


def _split_receive(paths: list[str]) -> tuple[list[str], str]:
    # REMOTE... [LOCAL_DEST]; a lone path defaults to the current directory.
    if len(paths) == 1:
        return paths, "."
    return paths[:-1], paths[-1]


def send_cmd(args) -> None:
    from remote_hashcat.core.transport import SSHTransport

    t = SSHTransport.for_instance(args.instance)
    sources, dest = _split_send(args.paths)
    argv = t.send_argv(sources, dest)
    print(f"-> sending to instance [{args.instance}] root@{t.host}:{dest}")
    sys.exit(t.run(argv))


def receive_cmd(args) -> None:
    from remote_hashcat.core.transport import SSHTransport

    t = SSHTransport.for_instance(args.instance)
    sources, dest = _split_receive(args.paths)
    argv = t.receive_argv(sources, dest)
    print(f"<- receiving from instance [{args.instance}] into {dest}")
    sys.exit(t.run(argv))


def run_cmd(args) -> None:
    print(
        "remote_hashcat run: job dispatch is not implemented yet (phase 2).\n"
        "Available now: `remote_hashcat send` / `receive`.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    p = argparse.ArgumentParser(
        prog="remote_hashcat",
        description="Move files to/from fleet instances and run hashcat jobs",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("run", help="Run a hashcat job on an instance (phase 2)")
    pr.add_argument("--instance", type=int, required=True)
    pr.set_defaults(func=run_cmd)

    ps = sub.add_parser("send", help="rsync local files TO an instance")
    ps.add_argument("--instance", type=int, required=True)
    ps.add_argument(
        "paths", nargs="+",
        help="LOCAL... [REMOTE_DEST] (one path => dest defaults to /root/)",
    )
    ps.set_defaults(func=send_cmd)

    prc = sub.add_parser("receive", help="rsync files FROM an instance")
    prc.add_argument("--instance", type=int, required=True)
    prc.add_argument(
        "paths", nargs="+",
        help="REMOTE... [LOCAL_DEST] (one path => dest defaults to .)",
    )
    prc.set_defaults(func=receive_cmd)

    args = p.parse_args()
    try:
        args.func(args)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
