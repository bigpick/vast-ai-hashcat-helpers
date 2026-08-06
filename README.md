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
# 1. PROVISION — pick a worker (interactive picker; filter by region / uptime / $-per-perf).
just up --gpu RTX_4090 --region US --max-price 1.0
just ls                              # note the fleet index, e.g. [1]

# 2. SEND inputs (optional) — pre-stage big wordlists/rules once. rsync sends only
#    diffs and they're reused by every job on that instance.
just send --instance 1 ./wordlists/rockyou.txt /root/wordlists
just send --instance 1 ./rules/best64.rule    /root/rules

# 3. CRACK — pushes the hashfile (and any --wordlist/--rules; re-pushes are cheap
#    no-ops), launches detached hashcat, streams live status, and auto-pulls the
#    potfile to --potfile-path when it finishes.
#    --potfile-path is optional; it defaults to ./potfiles/instance-<N>.potfile.
#    Anything after `--` is passed straight to hashcat.
just run --instance 1 --hashfile hashes.txt -m 22000 \
    --wordlist rockyou.txt --rules best64.rule \
    --potfile-path ./potfiles/corp-ntlm.potfile -- -O -w 4

# 4. POLL a long job — Ctrl-C on `run` only stops watching; the job keeps cracking.
just status --instance 1             # one-shot: speed / recovered / %
just follow --instance 1             # re-attach to the live stream
just stop   --instance 1             # graceful stop (SIGINT → hashcat checkpoint)

# 5. RESULTS — the potfile auto-pulls on completion; fetch it (plus the cracked
#    list + run log) anytime.
just pull --instance 1 --potfile-path ./potfiles/instance-1.potfile

# 6. TEARDOWN — stop billing when the session's done.
just down --instance 1               # or: just down --all
```

## Commands

- **`provision_worker`** (fleet): `search` · `up` · `ls` · `sync` · `down`
- **`remote_hashcat`** (jobs/files): `run` · `follow` · `status` · `pull` · `stop` · `send` · `receive`

Run `just --list` to see every recipe.

## Status

- ✅ `provision_worker` — fleet lifecycle + interactive offer picker.
- ✅ `remote_hashcat` — file transfer + detached job run/stream/pull, validated
  end-to-end on real hardware.
- ✅ Worker image on public GHCR + CI (`publish-image`, `tests`).
- 🔜 `reserved` / non-interruptible multi-day pricing; distributed
  keyspace-splitting across N instances.
