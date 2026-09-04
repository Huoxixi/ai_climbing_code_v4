#!/usr/bin/env bash
# Run only inside the isolated benchmark bundle, never a production checkout.
set -Eeuo pipefail
benchmark_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${benchmark_root}"
benchmark_python="${BENCHMARK_PYTHON:-${benchmark_root}/.venv/bin/python}"
benchmark_output="${1:-${benchmark_root}/results/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p -- "$(dirname -- "${benchmark_output}")"
mkdir -- "${benchmark_output}"
{
  date -u +%Y-%m-%dT%H:%M:%SZ
  uname -srm
  lscpu
  free -m
  df -h .
} > "${benchmark_output}/hardware.txt"
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
"${benchmark_python}" backend/scripts/run_photo_route_benchmark.py \
  --image samples/yellow.jpg --seed .383 .285 \
  --mobile-sam-repo model --checkpoint model/weights/mobile_sam.pt \
  --threads 2 --batch-size 2 --prune-inspection \
  --output "${benchmark_output}/yellow"
"${benchmark_python}" backend/scripts/run_photo_route_benchmark.py \
  --image samples/blue.jpg --seed .445 .271 \
  --mobile-sam-repo model --checkpoint model/weights/mobile_sam.pt \
  --threads 2 --batch-size 2 --prune-inspection \
  --output "${benchmark_output}/blue"
printf 'Evidence directory: %s\n' "${benchmark_output}"
