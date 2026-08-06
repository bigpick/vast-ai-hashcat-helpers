# CUDA + hashcat worker image. Kept broadly runnable by capping CUDA at <= 13.0
# and building hashcat portably. See design §8.
ARG CUDA_VERSION=12.9.1
FROM nvidia/cuda:${CUDA_VERSION}-devel-ubuntu24.04

ARG HASHCAT_VERSION=v7.1.2

ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

LABEL org.opencontainers.image.licenses=MIT
LABEL org.opencontainers.image.description="CUDA + hashcat worker for vast-ai-hashcat-helpers"
LABEL org.opencontainers.image.source=https://github.com/bigpick/vast-ai-hashcat-helpers

WORKDIR /root/

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        git make build-essential \
        libjudy-dev libpcre3-dev libmhash-dev \
        jq bc rsync openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Remove CUDA OpenCL package (upstream hashcat practice).
RUN removeopencl=$(dpkg --list | awk '/opencl/ && $2 ~ /^cuda-opencl-/ {print $2; exit}') && \
    if [ -n "$removeopencl" ]; then apt-get remove -y $removeopencl; fi && \
    rm -rf /var/lib/apt/lists/*

# Build hashcat from a pinned tag. BUILD_MODE=cross => -march=x86-64, so the
# binary runs on any x86-64 host regardless of the build machine's CPU features.
RUN git clone https://github.com/hashcat/hashcat.git /root/hashcat && \
    cd /root/hashcat && \
    git checkout ${HASHCAT_VERSION} && \
    git submodule update --init && \
    make -j"$(nproc)" BUILD_MODE=cross && \
    make install && \
    rm -rf /root/hashcat/.git

RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh && \
    mkdir -p /root/jobs /root/wordlists /root/rules

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
