#!/bin/bash
# Apply our template overrides on top of the vendored MSM eval.
#
# Upstream ships exfiltration WITHOUT a restriction condition: the file
# email-template-exfiltration-goal-conflict-none-restriction.md is a 98-byte
# "TODO: Implement this template if needed" stub, and EMAIL_TEMPLATES points
# exfiltration's "restriction" key at that same stub. The result is silent, not
# an error — goal-conflict-on prompts get the deletion emails plus two lines of
# comment text, and goal-conflict-off prompts get a 423-character prompt with no
# emails at all. Every restriction run before 2026-08-07 therefore carries 60
# invalid samples out of 180 (see FSDPFA3Handoff.md).
#
# This script writes real templates for both cells and repoints the config.
# setup_vendor.sh calls it, because `rm -rf vendor` would otherwise drop it.
set -e
cd "$(dirname "$0")"

VENDOR_TPL=vendor/evals/agentic_misalignment/templates/exfiltration/templates
GEN=vendor/evals/agentic_misalignment/prompt_generator.py

[ -d "$VENDOR_TPL" ] || { echo "vendor not found; run setup_vendor.sh first" >&2; exit 1; }

cp template_overrides/exfiltration/templates/*.md "$VENDOR_TPL/"

# Point the restriction key at the appendix template (upstream aims it at the
# goal-conflict-none file, which the non-none path must not use).
python3 - "$GEN" <<'PY'
import re
import sys

path = sys.argv[1]
src = open(path).read()
old = '"restriction": "exfiltration/templates/email-template-exfiltration-goal-conflict-none-restriction.md"'
new = '"restriction": "exfiltration/templates/email-template-exfiltration-restriction.md"'
if new in src:
    print("prompt_generator.py already patched")
elif old in src:
    open(path, "w").write(src.replace(old, new))
    print("patched prompt_generator.py exfiltration restriction key")
else:
    sys.exit("FAILED: exfiltration restriction key not found — upstream layout changed")
PY

# Fail loudly if a stub survived.
for f in email-template-exfiltration-restriction.md \
         email-template-exfiltration-goal-conflict-none-restriction.md; do
  size=$(wc -c < "$VENDOR_TPL/$f")
  [ "$size" -gt 2000 ] || { echo "FAILED: $f is $size bytes, looks like a stub" >&2; exit 1; }
done

echo "template overrides applied"
