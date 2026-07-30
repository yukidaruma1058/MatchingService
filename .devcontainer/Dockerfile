FROM mcr.microsoft.com/devcontainers/typescript-node:1-20-bookworm

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    gzip \
    openssh-client \
    procps \
    tar \
    wget \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/02_MatchingService/web

