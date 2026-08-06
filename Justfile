set dotenv-load

python := "uv run"
registry := env("REMOTE_HASHCAT_REGISTRY", "ghcr.io/bigpick/vast-ai-hashcat-helpers")
cuda_version := env("REMOTE_HASHCAT_CUDA", "12.9.1")
hashcat_version := env("REMOTE_HASHCAT_HASHCAT_VERSION", "v7.1.2")

# --- Setup ---

setup:
    uv sync --all-extras
    {{ python }} pre-commit install

# --- Tests ---

test *ARGS:
    {{ python }} pytest {{ ARGS }}

test-cov:
    {{ python }} pytest --cov=remote_hashcat --cov-report=term-missing

lint *ARGS:
    {{ python }} pre-commit run {{ ARGS }}

# --- Fleet ---

search *ARGS:
    {{ python }} provision_worker search {{ ARGS }}

up *ARGS:
    {{ python }} provision_worker up {{ ARGS }}

ls:
    {{ python }} provision_worker ls

down *ARGS:
    {{ python }} provision_worker down {{ ARGS }}

sync:
    {{ python }} provision_worker sync

plan *ARGS:
    {{ python }} provision_worker plan {{ ARGS }}

# --- Files (rsync to/from a fleet instance) ---

send *ARGS:
    {{ python }} remote_hashcat send {{ ARGS }}

receive *ARGS:
    {{ python }} remote_hashcat receive {{ ARGS }}

# --- Jobs (run hashcat on a fleet instance) ---

run *ARGS:
    {{ python }} remote_hashcat run {{ ARGS }}

follow *ARGS:
    {{ python }} remote_hashcat follow {{ ARGS }}

status *ARGS:
    {{ python }} remote_hashcat status {{ ARGS }}

pull *ARGS:
    {{ python }} remote_hashcat pull {{ ARGS }}

stop *ARGS:
    {{ python }} remote_hashcat stop {{ ARGS }}

# --- Container ---

build-image:
    docker build \
        --build-arg CUDA_VERSION={{ cuda_version }} \
        --build-arg HASHCAT_VERSION={{ hashcat_version }} \
        -t {{ registry }}:{{ hashcat_version }}-cuda{{ cuda_version }} \
        container/

push-image:
    docker push {{ registry }}:{{ hashcat_version }}-cuda{{ cuda_version }}
