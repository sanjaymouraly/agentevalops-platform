#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t agentevalops-runner:latest -f - . <<'DOCKER'
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN useradd -u 1000 -m runner
WORKDIR /workspace
USER 1000:1000
DOCKER
echo "Built agentevalops-runner:latest"