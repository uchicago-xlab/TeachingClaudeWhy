#!/usr/bin/env bash
# Petri automated alignment audit against the elicit-A1 merged checkpoint —
# our stand-in for the post's internal automated alignment assessment
# (References.md). This file is the record of the 2026-08-03 run; start the
# target with serve_merged.sh first.
#
# Needs: inspect_ai, inspect_petri (pip install inspect-petri), and
# ANTHROPIC_API_KEY for the auditor/judge roles. VLLM_API_KEY=a is a dummy —
# the local server has no --api-key but the client requires the variable.
#
# Results of the full run (Petri's default seed instruction set, 173 samples,
# status success) are committed at
#   data/petri-eval/logs/2026-08-03T21-04-37-00-00_audit_5agJ4LCac4Fc27et5vFFUd.eval
# View transcripts and judge scores with:
#   inspect view --log-dir data/petri-eval/logs
set -euo pipefail

SERVED_NAME=${SERVED_NAME:-qwen2.5-32b-elicit-A1}
PORT=${PORT:-8000}

VLLM_BASE_URL="http://localhost:${PORT}/v1" VLLM_API_KEY=a \
    exec inspect eval inspect_petri/audit \
    --model-role auditor=anthropic/claude-sonnet-4-6 \
    --model-role "target=openai-api/vllm/${SERVED_NAME}" \
    --model-role judge=anthropic/claude-opus-4-6
