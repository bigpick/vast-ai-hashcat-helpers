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
#    Attack inputs are ORDERED (--wordlist/--maskfile push a file; --mask is literal);
#    -a picks the mode. `--` still carries extra hashcat OPTIONS (-O, -w, --increment).
#      -a 0 dict+rules : -a 0 --wordlist rockyou.txt --rules best64.rule
#      -a 3 mask       : -a 3 --mask '?d?d?d?d?d?d?d?d'
#      -a 3 maskfile   : -a 3 --maskfile rockyou-1-60.hcmask
#      -a 6 hybrid     : -a 6 --wordlist rockyou.txt --mask '?d?d'   (dict, then mask)
#      -a 7 hybrid     : -a 7 --mask '?d?d' --wordlist rockyou.txt   (mask, then dict)

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


## Notes

```
  What you type (host side):

  # -a 0  dict + rules
  just run --instance 1 --hashfile h.txt -m 22000 --wordlist rockyou.txt --rules best64.rule -- -O -w 4

  # -a 3  mask (literal)
  just run --instance 1 --hashfile h.txt -m 0 -a 3 --mask '?d?d?d?d?d?d?d?d'

  # -a 3  maskfile (a file of mask lines, pushed like a wordlist)
  just run --instance 1 --hashfile h.txt -m 0 -a 3 --maskfile rockyou-1-60.hcmask

  # -a 6 / -a 7  hybrid (order between dict and mask is preserved)
  just run --instance 1 --hashfile h.txt -m 0 -a 6 --wordlist rockyou.txt --mask '?d?d'
  just run --instance 1 --hashfile h.txt -m 0 -a 7 --mask '?d?d' --wordlist rockyou.txt

  Composed correctly on the worker (verified, potfile/restore/status flags elided):
  - -a 0 → … -r best64.rule -O -w 4 <hashfile> <wordlist>
  - -a 3 → … <hashfile> ?d?d?d?d?d?d
  - -a 6 → … <hashfile> <wordlist> ?d?d ← dict then mask, order intact

  Mechanics: --wordlist/--maskfile push a local file (to /root/wordlists and the new /root/masks) and become positionals; --mask passes a literal; a small ordered-collector keeps them in the exact sequence you typed (so -a 6 vs -a 7 compose
  right). --rules stays a -r option; -- still carries extra hashcat options. README's Flow shows all five. -- is not where masks go — that was the trap you spotted.
```
