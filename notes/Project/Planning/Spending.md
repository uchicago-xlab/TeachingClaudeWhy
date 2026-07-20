---
status: active
---

# Spending

Running ledger of project spend, against the [[ImplementationDetails]] §5 budget (base plan ~$9–13K; ambitious plan $50–70K). Newest on top. Every row is either money that's gone (**spent** — used for work, or **burned** — wasted) or money committed but not yet used (**allocated**). Usage drawn from an allocation gets its own row and reduces that allocation's "unused" figure rather than adding to the committed total.

**Spent/burned so far: ~$407** · **Allocated, unused: ~$618** · **Total committed: $1,025**

## Ledger

| Date | What | Who | Amount | Status |
|---|---|---|---|---|
| 2026-07-20 | Runpod $-$ 8x H100 for 42m | Brandon | $16.74 | spent |
| 2026-07-13 | RunPod usage — stories pipeline test (3.1.1 data gen), drawn from the $100 allocation below: Gemma 4 31B pod 2.26h × $1.39 = $3.14; Qwen2.5-72B pod 0.97h × $2.78 = $2.70; failed first 72B pod (old-driver host) ~0.3h × $2.78 ≈ $0.90; volume storage cents. Output: 2 × 12 test stories in `data/stories-pilot/` | Anastasia | ~$7 | spent |
| 2026-07-13 | RunPod — initial fine-tuning pipeline verification | Brandon | $120 | spent |
| 2026-07-13 | RunPod — initial fine-tuning pipeline verification | Brandon | $500 | allocated |
| 2026-07-13 | RunPod — accidental leftover pod burn | Brandon | $150 | burned |
| 2026-07-13 | RunPod credits — dataset generation (~$93 unused after the ~$7 above) | Anastasia | $100 | allocated |
| 2026-07 | RunPod — agentic misalignment eval pipeline check | Finn | $25 | allocated |
| 2026-07-08 | RunPod | Brandon | $250 | burned |

## Conventions

- One row per receipt/invoice/credit purchase, not per experiment — tie it to an experiment in the description (e.g. "3.2 data gen").
- Update the totals line when you add a row: spent/burned = money gone, allocated = committed but unused, committed = both.
- Compute pricing assumptions live in [[ImplementationDetails]] §5; if reality diverges from them, note it there too.
