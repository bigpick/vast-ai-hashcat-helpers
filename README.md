# vast-ai-hashcat-helpers

Provision [Vast.ai](https://vast.ai) GPUs and run remote **hashcat** jobs from
your host. Reserve a fleet for a few days, crack against chosen instances, pull
the potfile back, then tear it down.

Two host CLIs over a shared core, plus a CUDA + hashcat worker image:

- **`provision_worker`** — search/filter offers, reserve instances, list the
  fleet, destroy.
- **`remote_hashcat`** — send/receive files and run **detached** hashcat jobs on
  an instance, streaming status and auto-pulling the potfile.
- **`container/`** — the worker image, published to
  `ghcr.io/bigpick/vast-ai-hashcat-helpers`.

## Setup

```bash
uv sync --all-extras          # or: just setup
cp .env.example .env          # add your VAST_API_KEY
```

Instances launch with the published worker image by default (CI builds + pushes
it on changes to `container/`). To rebuild/republish it yourself:

```bash
just build-image && just push-image     # then keep the GHCR package Public
```

## Flow

A full session, cold → results. Every command goes through the Justfile.

```bash
# 0. PLAN (optional) — size a fleet to a budget before spending. Prints ranked
#    options A–H (GPUs / cost / leftover), then ready-to-run `up` commands for one
#    of them (option A by default; `--emit B` prints option B's instead).
#    Costs include compute + --disk + ~image-pull network; add wordlist GB via --xfer-gb.
just plan --budget 500 --hours 72 --gpu RTX_4090 --disk 100 --min-reliability 0.98
#   → e.g.  A  20 GPUs  4 inst  2x 8-GPU, 2x 2-GPU  $488.37  ...
#           Provision option A:
#             just up --offer 45147662 --disk 100   # 8-GPU  $2.630/hr
#             ...

# 1. PROVISION — paste the planner's emitted lines...
just up --offer 45147662 --disk 100
#    ...or pick interactively by GPU + filters (add --secure for datacenter-only):
just up --gpu RTX_4090 --region US --min-reliability 0.98 --disk 100
just ls                              # note the fleet index, e.g. [1]

# 2. SEND inputs (optional) — pre-stage big wordlists/rules once. rsync sends only
#    diffs and they're reused by every job on that instance.
just send --instance 1 ./wordlists/rockyou.txt /root/wordlists
just send --instance 1 ./rules/best64.rule    /root/rules

# 3. CRACK — pushes the hashfile (and any --wordlist/--rules; re-pushes are cheap
#    no-ops), launches detached hashcat, streams live status, and auto-pulls results
#    when it finishes. --potfile-path is the LOCAL destination on your host
#    (default ./potfiles/instance-<N>.potfile); hashcat's own potfile stays on the
#    worker. Anything after `--` is passed straight to hashcat.
just run --instance 1 --hashfile hashes.txt -m 22000 \
    --wordlist rockyou.txt --rules best64.rule \
    --potfile-path ./potfiles/corp-ntlm.potfile -- -O -w 4

# 4. POLL a long job — Ctrl-C on `run` only stops watching; the job keeps cracking.
just status --instance 1             # one-shot: speed / recovered / %
just follow --instance 1             # re-attach to the live stream
just stop   --instance 1             # graceful stop (SIGINT → hashcat checkpoint)

# 5. RESULTS — auto-pulled on completion, and safe to pull mid-run as often as you
#    like: it just rsync-copies the worker's potfile down; hashcat keeps running.
just pull --instance 1 --potfile-path ./potfiles/instance-1.potfile

# 6. TEARDOWN — stop billing when the session's done.
just down --instance 1               # or: just down --all
```

## Commands

- **`provision_worker`** (fleet): `search` · `plan` · `up` · `ls` · `sync` · `down`
- **`remote_hashcat`** (jobs/files): `run` · `follow` · `status` · `pull` · `stop` · `send` · `receive`

Common offer filters (on `search` / `up` / `plan`): `--gpu` · `--region` · `--min-reliability`
(0–1, e.g. `0.99`) · `--min-cuda` · `--max-price` · `--secure` (datacenter/Secure-Cloud only).

Run `just --list` to see every recipe.

## Status

- ✅ `provision_worker` — fleet lifecycle, interactive picker, budget `plan` (→ `up`
  commands), `--secure` datacenter filter.
- ✅ `remote_hashcat` — file transfer + detached job run/stream/pull, validated
  end-to-end on real hardware.
- ✅ Worker image on public GHCR + CI (`publish-image`, `tests`).
- 🔜 Distributed keyspace-splitting across N instances; optional auto-pull interval
  for long runs. (Vast `reserved` pricing needs a 1-month min, so it's out of scope
  for multi-day sessions — on-demand is already non-interruptible.)
