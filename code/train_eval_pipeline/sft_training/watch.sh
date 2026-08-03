#!/bin/bash
# Progress-delta monitor for a running arm.  Usage:  bash watch.sh <pod-name>
#
# "Process alive + GPU busy" is NOT progress (we once burned 2.6M tokens on a
# run that looked alive while making none), so this measures deltas: samples
# the newest /root/train-*.log twice, 60s apart, and compares size + last
# logged step. Also prints the tail so you can see the current stage — GPU 0%
# during install/download/warm-up is normal.
set -euo pipefail
NAME="${1:?usage: watch.sh <pod-name>}"
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.pods/$NAME.env"
SSH=(ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "root@$SSH_IP")

sample() {
  "${SSH[@]}" '
    L=$(ls -t /root/train-*.log 2>/dev/null | head -1)
    if [ -z "$L" ]; then echo "NOLOG 0 -"; exit 0; fi
    printf "%s %s " "$L" "$(wc -c < "$L")"
    grep -oE "[0-9]+/[0-9]+ \[|.epoch.: [0-9.]+" "$L" | tail -1 | tr -d "\n"; echo
  '
}

A=$(sample)
echo "log: $(echo "$A" | awk '{print $1}')  size: $(echo "$A" | awk '{print $2}')  last-step: $(echo "$A" | cut -d' ' -f3-)"
echo "--- tail ---"
"${SSH[@]}" 'L=$(ls -t /root/train-*.log 2>/dev/null | head -1); [ -n "$L" ] && tail -5 "$L"' || true
echo "--- sampling again in 60s ---"
sleep 60
B=$(sample)
SIZE_A=$(echo "$A" | awk '{print $2}'); SIZE_B=$(echo "$B" | awk '{print $2}')
if [ "$SIZE_B" -gt "$SIZE_A" ]; then
  echo "PROGRESS: log grew $SIZE_A -> $SIZE_B bytes; last-step: $(echo "$B" | cut -d' ' -f3-)"
else
  echo "STALLED: no log growth in 60s (size $SIZE_B). Check nvidia-smi + tail the log; if it stays flat, the run is stuck regardless of GPU load."
fi
