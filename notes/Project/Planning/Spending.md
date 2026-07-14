---
status: active
---

# Spending

Running ledger of actual project spend, against the [[ImplementationDetails]] §5 budget (base plan ~$9–13K; ambitious plan $50–70K). Add a row when money is spent — API credits, GPU hours, subscriptions — newest on top.

**Total spent: $775**

## Ledger

| Date | What | Who | Amount | Notes |
|---|---|---|---|---|
| 2026-07-13 | RunPod usage — stories pipeline test (3.1.1 data gen) | Anastasia | ~$7 | drawn from the $100 credit below: Gemma 4 31B pod 2.26h x $1.39 = $3.14; Qwen2.5-72B pod 0.97h x $2.78 = $2.70; failed first 72B pod (old-driver host) ~0.3h x $2.78 ≈ $0.90; volume storage cents. Output: 2 x 12 test stories in `data/stories-pilot/` |
| 2026-07-13 | RunPod — initial fine-tuning pipeline verification | Brandon | $500 | allocated |
| 2026-07-13 | RunPod — accidental leftover pod burn | Brandon | $150 | burned |
| 2026-07 | RunPod — agentic misalignment eval pipeline check | Finn | $25 | allocated |
| 2026-07-13 | RunPod credits — dataset generation | Anastasia | $100 | allocated |
| 2026-07-08 | RunPod | Brandon | $250 | burned |

## Conventions

- One row per receipt/invoice/credit purchase, not per experiment — tie it to an experiment in the notes column (e.g. "3.2 data gen").
- Update the **Total spent** line when you add a row.
- Compute pricing assumptions live in [[ImplementationDetails]] §5; if reality diverges from them, note it there too.
