---
status: active
---

# Progress Log

### 07/09

- Fermi estimates of cost & constitution scaling w/ Fable.
- Looking into batching & caching for using the whole constitution in inputs without blowing through the budget.
- Meeting w/ Anastasia!
  - I notice I am confused about some of the Fermi estimates, and that on closer inspection I suspect Fable hallucinated or conflated some stuff. This is an update for me; I wouldn't expect that kind of mundane mistake from Fable. I need to check much more carefully. Glad we caught it early, when it's relatively inconsequential.
  - There's a lot to keep track of on this paper. I need to study it more, & more regularly, and make sure I can have the entire thing in my head.
  - I'm going to work on difficult advice dataset, Anastasia wants a detailed step-by-step plan of what I'm going to do before she signs off.

## 07/10

Plan for difficult advice, following the 6-layer structure & appendix, written and in shared project space. This was a beast to write.

## 07/16

Haven't been updating this so well. Past ~3 days have been working on the pipeline, incorporating Anastasia's feedback. Observations:
- Lots of time spent iterating on prompt engineering. It's hard to get quality, but I feel pretty optimistic about the pipeline. It took more *time* than expected, but final results should be pretty solid.
- Experimenting with being more explicit and heavy-handed in the critique phase than I originally thought. My gut was that if you give models too many structured guidelines, they go into compliance mode and don't put any originality or spark into the work. But if you're working in the generate → critique → revise pipeline, then I suppose a rigid critique prompt doesn't mess with the originality of the initial generation.
- Had to ban bioweapons scenarios, as the classifier just refuses to generate them. Hope it still generalizes. 