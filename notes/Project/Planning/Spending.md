---
status: done
---

# Spending

This ledger moved into the Logbook app's **Spending** view. The data lives in
`Project/Planning/spending.json` and is edited through the app — every change
is a commit, and totals are computed (no more hand-maintained totals line).

Open it: [Spending view](#/spending) · https://uchicago-xlab.github.io/tcw-logbook/#/spending

Conventions (unchanged): one entry per receipt/invoice/credit purchase, tied to
an experiment in the description. Statuses: **spent** (money used), **burned**
(money wasted), **allocated** (committed, unused). Usage drawn from an
allocation is its own spent/burned entry linked to that allocation, and the app
subtracts it from the allocation's remaining figure automatically. Compute
pricing assumptions live in [[ImplementationDetails]] §5; if reality diverges
from them, note it there too.
