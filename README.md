# vast-ai-hashcat-helpers

Provision [Vast.ai](https://vast.ai) GPUs and run remote **hashcat** jobs from
your host — no Hashtopolis server required. Reserve a fleet for a few days, crack
against chosen instances, pull the potfile back, then tear it down.

Two host CLIs over a shared core, plus a CUDA + hashcat worker image:

- **`provision_worker`** — search/filter offers, reserve instances, list the
  fleet, destroy.
- **`remote_hashcat`** — dispatch a hashcat job to instance `N` and pull results
  back. *(phase 2)*
- **`container/`** — the worker image, published to
  `ghcr.io/bigpick/vast-ai-hashcat-helpers`.

## ⚠️ This is a public repo — keep secrets and data out of it

- `VAST_API_KEY` and SSH keys come **only** from the environment / `~/.ssh`.
  `.env` is gitignored.
- **Never commit** hashes, wordlists, potfiles, or cracked output — that is user
  data, not project code (see `.gitignore`).
- The worker image contains no secrets, hashes, or wordlists.
- `pre-commit` runs `ripsecrets` to catch accidental secret commits.

## Setup

```bash
uv sync --all-extras          # or: just setup
cp .env.example .env          # add your VAST_API_KEY
```

## Provision

```bash
# Browse offers
just search --gpu RTX_5090 --region US --max-price 3.0

# Reserve a specific machine (e.g. an 8x 5090 box)
just up --machine 140767

# List the fleet with live status + accrued cost
just ls

# Tear down
just down --instance 1        # or: just down --all
```

`provision_worker up` uses the worker image, so build + push it once:

```bash
just build-image && just push-image
```

...or, for a quick provisioning test before the image is published, reserve with
any bootable CUDA image via `--image <ref>`.

## Status

- ✅ Phase 1 — `provision_worker` (fleet lifecycle) + worker image + CI publish.
- 🚧 Phase 2 — `remote_hashcat` (job push / run / stream + potfile pull).
