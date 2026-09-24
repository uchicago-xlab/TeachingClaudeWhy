---
status: active
---

# Replay mixing for the Sonnet difficult-advice arm (2026-09-23)

## Question

Sonnet 5 answering terra's 135 prompts (`claude-sonnet-5-terraprompts`) trains a
sequential DA adapter whose acting rate falls with dose: 98% → 67% (30 steps) →
29% (60 steps), while terra holds 96–99% (AdapterCatalog, "The sequential
difficult-advice arm"). The non-acting samples write the email as prose or ask
the user a question. On the identical prompts Sonnet's responses end on a
question 20% of the time (terra 0.7%), average 4.1 question marks (1.5), and
start 0.5 sentences with an imperative (1.9) — the shape the step-8 critique
rubric asks for ("less telling the user what to do, more asking the user
questions"), which Sonnet follows harder.

Can mixing A1-mix rows into the DA rows at 1:1 by row count restore acting
without touching the data or the teacher comparison? And is the non-agentic
core needed, or do the agentic sources alone carry it? Options considered and
deferred: editing the critique/rewrite templates (needs a 2×2 across both
teachers, ~$40 generation) and folding DA into a one-stage A1 retrain (changes
the platform every result sits on).

## Design

Same recipe as every arm in the sequential table: fresh linear-only r64 adapter
over frozen `graft0-a1`, 10 epochs from scratch, effective batch 8 packed
sequences, val = `sonnet5tp-ft-qwen25-val.jsonl` (DA-only, so val loss stays
comparable). Two arms, one pod (`mixda`), adapters published:

| arm | train rows | slice | est. slice tokens |
|---|---|---|---|
| `graft0-a1-sonnet5tp-mixprop-e10` | 135 DA + 135 A1-mix in A1's proportions | apigen 35, systemchats 19, no_robots 25, tulu3-IF 13, magpie 11, constraints 8, summarize 8, numina 7, self-oss 6, longalign 3 | 93k |
| `graft0-a1-sonnet5tp-mixagent-e10` | 135 DA + 135 agentic-only | apigen 90, systemchats 45 (A1's 2:1) | 76k |

DA rows are ~222k tokens, so 1:1 by rows is ~0.4:1 by tokens (same accounting as
the August replay lane). Slices drawn once with seed 0 from the exact rows A1
trained on (`build_mix.py --arm A1 --seed 0` rebuilt and matched
`mix-a1-clean.jsonl` 13,000/13,000), restricted to those; the same slices are
reused unchanged for the terra arm. Files and manifest:
`data/difficult-advice/claude-sonnet-5-terraprompts/mixes/`.

Eval: `eval_arms.sh` 27×10 as Alex on a second pod (`evalmix`), same pinned
settings as the table (temp 0.7, max_tokens 4096, Sonnet 4.6 grader).

**Pre-registered read.** Primary: acting rate (`action_stats.py`), success ≥ 95%.
Secondary: harm given acted, against the existing Sonnet e10 (30 steps: 67%
acting, 37% harm|acted) and e20 (60 steps: 29%, 15%) — the mixed arms at 10
epochs land between those step counts (steps depend on packed tokens; read the
actual count from `trainer_state.json`). The winning pool goes to terra
(`terra-ft-qwen25.jsonl` + the same slice) to complete the comparison. If both
pools under-deliver, the next rung is a token-matched ratio, not a new pool.

## Run log

- 2026-09-23 19:49 UTC: driver started (`scratchpad/run_mix_arms.sh`, detached);
  pre-eval OpenRouter counter 23472.60.
- 20:01 UTC: training pod `mixda` (0g6dvt116n59ix, 2xA100-SXM) on attempt 4 after
  three capacity misses. mixprop-e10: 50 optimizer steps (270 rows, 10 epochs;
  vs 30 for DA-only), published + verified 20:48. mixagent-e10 started 20:48 on
  the same pod.
- 21:00 UTC: driver split so the eval does not wait for arm 2 — `finish_arm2.sh`
  (wait for marker, save logs, verify Hub, terminate `mixda`) and
  `eval_arms.sh evalmix` (polls the Hub per arm; KEEP_POD=0). Eval pod
  ng5he8fb0si5w4 created 21:00. Trap hit: a monitor whose command text
  contained `run_mix_arms.log` self-matched `pgrep -f "run_mix_arm[s]"` — the
  bracket trick does not help when the *filename* appears elsewhere in the
  same command line.
- 21:20 UTC: mixagent-e10 DONE, verified on the Hub; training pod terminated. A
  second eval pod (evalmix2, 2xH100) was created for arm 2 at 21:29 and
  terminated at 21:33 (Anastasia's call): the first pod already caches the base,
  so a parallel pod saved no wall-clock time for ~$5. Arm 2 runs on evalmix's
  own queue.

## Results

| arm | steps | acting | harm (27×10) | harm given acted | delib | med tok |
|---|---|---|---|---|---|---|
| sonnet5tp-da-e10 (DA only, from the catalog) | 30 | 67% | 30.7% | 37% | — | — |
| sonnet5tp-da-e20 (DA only, from the catalog) | 60 | 29% | 8.5% | 15% | — | — |
| **sonnet5tp-mixprop-e10** (DA + proportional A1 slice) | 50 | **71%** (192/270) | 37.0% (100/270) | **41%** | 77 | 1270 |
| **sonnet5tp-mixagent-e10** (DA + agentic-only slice) | 40 | **71%** (193/270) | 33.7% (91/270) | **41%** | 77 | 1599 |

Read of arm 1 (2026-09-23 14:40 PT): the proportional slice holds acting at
the 30-step level through 50 steps, where DA-only had fallen toward 29% by 60 —
so it slows the collapse but does not restore acting (71% vs the ≥95%
criterion). Harm given acted rises to 41%, above both DA-only arms: the chat
rows dilute the alignment signal, the same asymmetry the August replay lane saw
for generic-chat replay. Not a pass.

Read of both arms (2026-09-23 15:10 PT): **the pool does not matter.** Proportional
and agentic-only slices give the same acting (71% vs 71%, 77 deliberators each)
and the same harm given acted (41%). At matched DA exposure (10 epochs) the
mixed arms sit next to the DA-only e10 arm (67% / 37%); what the mix bought is
only that 40–50 steps did not push acting toward the e20 arm's 29%. Neither
pool restores acting or protects alignment, so at 1:1 by rows replay mixing is
not the lever. Pre-registered next rung was a token-matched ratio; given that
the two pools were indistinguishable, the more informative next step is the
data-side fix (critique/rewrite template 2×2 across both teachers), since the
deliberation shape is put there and not removed by rehearsal. Val loss:
mixprop 1.586, mixagent 1.548 (DA-only val). Spend $15.9
(`aw-sonnet5tp-replaymix-arms`). All three pods verified terminated (404).

## Follow-up: terra-v2 templates (2026-09-23, 15:50 PT)

Data-side fix, Anastasia's edit: `prompts/difficult_advice/terra-v2/` = terra with
step 8's deliberation bullet reworded ("more laying out the considerations the
user should weigh"; "less telling the user what to do" dropped), a new Delivery
section (flag hedged recommendations; flag responses that close on questions to
the user), and step 9 told to write directly and end with concrete suggestions.
Steps 1–7 byte-identical. The blog post specifies none of this: its appendix
gives one sentence for the rewrite step ("rewrite the response to be even more
aligned with the constitution") and has no critique step; the deliberation
bullet was Jack's 2026-07-22 addition from the GDM pattern scan.

10-row pilot (rows 2, 18, 22, 30, 50, 69, 72, 82, 100, 110 — Sonnet's current
response ends on a question in each), responses-only, both teachers, $2.25:

| set | words | "?" per resp | ends on ? | imperative starts |
|---|---|---|---|---|
| terra current | 652 | 0.6 | 0/10 | 2.2 |
| terra v2 | 691 | 0.0 | 0/10 | 3.7 |
| Sonnet current | 686 | 4.4 | 10/10 | 0.7 |
| Sonnet v2 | 866 | 0.1 | **0/10** | 1.3 |

The v2 judge flagged the closing question in 10/10 Sonnet critiques and the
rewrite removed it every time. Sonnet v2 runs ~25% longer. Viewer:
https://claude.ai/artifact/21ZeLS9MibkuLzxuEjKVNm (current sets) and the pilot
artifact published 2026-09-23. Pilot dirs: `data/difficult-advice/pilots/terra-v2-{sonnet10,terra10}/`.

### Full terra-v2 regeneration (2026-09-23, 16:46 PT)

Both teachers, responses-only on the same 150 prompts, $38.51 (`aw-terra-v2-regen-150`;
first pass killed by the OpenRouter key cap at 33/150 and 44/150, resumed after the
cap was raised). Dirs: `claude-sonnet-5-terraprompts-v2/` (`sonnet5tpv2-ft-qwen25*.jsonl`)
and `gpt-5.6-terra-v2/` (`terrav2-ft-qwen25*.jsonl`), 135 + 15 each, split verified
identical to terra's. Stage records: stages 1–6 inherited (terra), 7–9 terra-v2.

| set | words | "?" per resp | ends on ? | imperative starts | markdown rows |
|---|---|---|---|---|---|
| terra current | 744 | 1.6 | 0.7% | 2.0 | 7 |
| terra v2 | 757 | 0.4 | 0.0% | 4.2 | 12 |
| Sonnet current | 805 | 4.2 | 20.7% | 0.5 | 12 |
| Sonnet v2 | 900 | 0.7 | **0.0%** | 2.0 | 4 |

The pilot generalised: Sonnet's closing questions are gone across all 150 rows,
question density fell 6×, imperative starts 4×; Sonnet v2 is ~12% longer than
Sonnet current. Terra moved the same direction from a lower base. The 2×2 is now
{terra, Sonnet} × {current, v2} on identical prompts; the current cells' arms
already exist (terra-da-e10/e20, sonnet5tp-da-e10/e20).

### 2×2 v2 arms (2026-09-23 evening PT)

Fresh adapters over frozen `graft0-a1`, 10 and 20 epochs, `sonnet5tpv2-ft-qwen25.jsonl`
and `terrav2-ft-qwen25.jsonl` (own DA-only val), 27×10 as Alex. Pods: trainsv2
9iiwow071kxlwl, traintv2 0rpsawtekwalxl (both 2xA100-SXM, first attempt), evalv2.

| arm | steps | acting | harm | harm given acted | delib |
|---|---|---|---|---|---|
| Sonnet current e10 (existing) | 30 | 67% | 30.7% | 37% | 88 |
| Sonnet current e20 (existing) | 60 | 29% | 8.5% | 15% | — |
| terra current e10 (existing) | 30 | 95% | 44.1% | 45% | — |
| terra current e20 (existing) | 58 | 97% | 1.9% | 2% | — |
| **Sonnet v2 e10** | 30 | **94%** (255/270) | 34.8% | 34% | 15 |
| terra v2 e10 | 30 | 95% (257/270) | 12.2% | 12% | 13 |
| **Sonnet v2 e20** | 60 | **90%** (244/270) | 19.3% | 20% | 25 |
| terra v2 e20 | 60 | 100% (269/270) | 6.7% | 7% | 1 |

First read (19:07 PT): the data-side fix restores acting at 30 steps (67% → 94%,
deliberators 88 → 15), alignment unchanged at this dose. The 60-step cell decides.

Final read (2026-09-23 20:40 PT). Steps actually run: sonnet5tpv2 40 / 80 (its
longer responses pack into more sequences), terrav2 30 / 60; val loss at the end
1.70 / 2.47 (Sonnet v2) and 1.77 / 2.46 (terra v2), i.e. both overfit the 15-row
val by 20 epochs as every DA arm does.

1. **The acting collapse was the response shape, and the template edit removes
   it.** Sonnet: 67% → 94% at e10, 29% → 90% at e20; deliberators 88 → 15 and
   191 → 25. Terra, already direct, is unchanged (99 → 95, 97 → 100). The
   critique rubric's "ask the user questions" instruction was the cause; the
   replay-mix arms earlier today (71% either pool) confirm rehearsal could not
   undo it.
2. **With acting restored, the teacher gap is real and large.** Same prompts,
   same templates, same recipe: harm given acted at the 20-epoch dose is 20%
   (Sonnet v2) vs 7% (terra v2) / 2% (terra current). Terra's responses teach
   the disposition several times more effectively per row. This is the fair
   generator comparison the terraprompts set was built for.
3. **Terra v2 at e20 is slightly worse than terra current (18 vs 5 harmful of
   270).** Could be the template's directness nudging terra toward "act", could
   be the 27×10 noise floor (SE ≈ 1.5pp on 270); a 27×100 on both terra e20 arms
   would settle it before the v2 templates become the default set.
4. Sonnet v2 e20's completions are long (median 2,402 tokens vs ≤1,632 elsewhere)
   with 9 junk-tail samples: the 12% longer training responses carry through.

Spend: $33.2 (`aw-terra-v2-2x2-arms`). Total for today's acting investigation
(mix arms + pilot + regeneration + 2×2): ~$90.
