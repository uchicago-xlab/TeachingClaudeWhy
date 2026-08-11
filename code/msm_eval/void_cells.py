"""Detect eval samples that ran against an unimplemented scenario template.

MSM shipped exfiltration with replacement templates only. At the pinned commit
`e8288a8` the restriction and no-urgency files are placeholders (98 and 91
bytes) reading "TODO: Implement this template if needed", and `EMAIL_TEMPLATES`
aimed exfiltration's `restriction` key at the stub. Nothing raised, so the
harness scored samples whose prompt was the shared email block plus two lines
of comment text (goal conflict on), or 423 characters with no emails at all
(goal conflict off). Every restriction run before 2026-08-10 therefore carries
60 void samples out of 180.

Detection is by prompt CONTENT, not by run-directory name. The name heuristic
("restriction" in the dir name plus scenario == exfiltration) is right for all
data collected to date, but it would silently discard *valid* samples now that
`template_overrides/` supplies real exfiltration restriction templates. The
stub marker cannot appear in a real prompt, so this test stays correct on both
sides of the fix.

Used by action_stats.py, build_transcript_viewer.py and
notes/.../plot_results.py so all three agree on what counts.
"""

# Verbatim from upstream's placeholder files; see template_overrides/README.md.
STUB_MARKERS = (
    "Placeholder for exfiltration restriction urgency type",
    "TODO: Implement this template if needed",
)


def _text(message):
    c = message.content
    if isinstance(c, str):
        return c
    return "\n".join(getattr(p, "text", "") for p in c)


def is_void(sample):
    """True if the model was shown an unimplemented-template prompt."""
    for m in sample.messages:
        if m.role == "user":
            text = _text(m)
            return any(mark in text for mark in STUB_MARKERS)
    return False
