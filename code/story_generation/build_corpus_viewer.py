"""Build a static HTML viewer for a sample of the fictional-stories corpus.

    python3 code/story_generation/build_corpus_viewer.py [--sample 20]

Writes data/fictional-stories/viewer/index.html plus one page per corpus
file. Self-contained (full story text inlined) — open index.html
directly, no server needed.

Each page shows a stratified sample: --sample stories spread evenly
across the 16 constitution chunks, so browsing one page shows the range
of principles rather than 3000 stories from whichever chunk sorts first.
Sampling is seeded, so pages are stable across rebuilds; --seed changes
the draw. Filter by principle / genre / framing / judge verdict, or
search; each card opens to the full story, the assertion it was written
from, the judge's reasoning (where the batch was judged), and metadata.
"""

import argparse
import html
import json
import random
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STORIES = REPO / "data" / "fictional-stories" / "corpus" / "stories"
OUT = REPO / "data" / "fictional-stories" / "viewer"

# corpus file stem -> (display name, section, verdicts file stem or None)
# One representative corpus per arm (Anastasia, 2026-08-19): batch 1 for the
# nano pairs (it is the judged batch), the full generated set for Sonnet 5
# (judge verdicts show as per-story tags), and the 14M protagonist rewrites.
CORPORA = [
    ("stories-p1-gpt54nano-embodiment", "nano embodiment",
     "Generated corpora (gpt-5.4-nano)",
     "verdicts-p1-gpt54nano-embodiment-claudehaiku45"),
    ("stories-p1-gpt54nano-recitation", "nano recitation",
     "Generated corpora (gpt-5.4-nano)",
     "verdicts-p1-gpt54nano-recitation-claudehaiku45"),
    ("stories-p1-sonnet5", "Sonnet 5 embodiment",
     "Generated corpora (Claude Sonnet 5)",
     "verdicts-p1-sonnet5-claudehaiku45"),
    ("rw-14M-human-gpt54nano", "human protagonist",
     "Protagonist rewrites", None),
    ("rw-14M-zephyrix-gpt54nano", "Zephyrix protagonist",
     "Protagonist rewrites", None),
    ("rw-14M-named-claude-gpt54nano", "Claude protagonist",
     "Named-identity rewrites", None),
    ("rw-14M-named-qwen-gpt54nano", "Qwen protagonist",
     "Named-identity rewrites", None),
]

CSS = """
body { margin: 0; font: 15px/1.55 -apple-system, system-ui, sans-serif;
       background: #fcfcfb; color: #1a1a19; }
.wrap { max-width: 1060px; margin: 0 auto; padding: 24px 20px 80px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.sub { color: #6f6e66; margin-bottom: 18px; }
a { color: #2a78d6; text-decoration: none; }
a:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 7px 12px;
         border-bottom: 1px solid #e6e5e0; }
th { color: #6f6e66; font-weight: 600; font-size: 13px; }
tr.section td { background: #f0efe9; font-weight: 700; font-size: 13px; }
.bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
       margin: 14px 0 18px; }
select, input[type=search] {
  font: inherit; padding: 5px 8px; border: 1px solid #d5d4cc;
  border-radius: 6px; background: #fff; color: inherit; max-width: 210px; }
input[type=search] { flex: 1; min-width: 180px; max-width: none; }
.count { color: #6f6e66; font-size: 13px; }
details.story { border: 1px solid #e6e5e0; border-radius: 8px;
                margin-bottom: 8px; background: #fff; }
details.story > summary { cursor: pointer; padding: 10px 14px;
  list-style: none; }
details.story > summary::-webkit-details-marker { display: none; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 5px; }
.tag { font-size: 12px; padding: 1px 8px; border-radius: 10px;
       background: #f0efe9; color: #6f6e66; white-space: nowrap; }
.tag.keep { background: #e3efdc; color: #3a6b2a; }
.tag.reject { background: #eb6834; color: #fff; }
.tag.flag { background: #f6e4b8; color: #7a5a12; }
.prev { color: #6f6e66; font-size: 13.5px; }
.body { padding: 0 14px 14px; }
.role { font-size: 12px; font-weight: 700; color: #6f6e66;
        text-transform: uppercase; letter-spacing: .04em;
        margin: 12px 0 4px; }
pre { white-space: pre-wrap; word-break: break-word; background: #f7f6f2;
      border-radius: 6px; padding: 10px 12px; margin: 0; font-size: 13.5px;
      max-height: 560px; overflow-y: auto; }
button.more { font: inherit; padding: 6px 14px; border-radius: 6px;
  border: 1px solid #d5d4cc; background: #fff; cursor: pointer; }
.cmp-wrap { max-width: 1320px; }
.cmp { display: grid; grid-template-columns: 1fr 1fr; gap: 18px;
       align-items: start; }
.col-head { font-weight: 700; font-size: 14px; margin-bottom: 2px; }
.col-head .kind { color: #6f6e66; font-weight: 400; }
.col-head.emb { color: #0173b2; }
.col-head.rec { color: #b5651d; }
@media (max-width: 780px) { .cmp { grid-template-columns: 1fr; } }
"""

PAGE = """<meta charset="utf-8">
<title>{title} — stories</title>
<style>{css}</style>
<div class="wrap">
<h1>{title}</h1>
<div class="sub"><a href="index.html">&larr; all corpora</a> &middot;
sample of {n} stories spread across {nchunks} constitution chunks
(of {total} in {stem}.jsonl) &middot; reseed with
<code>build_corpus_viewer.py --seed N</code></div>
<div class="bar">
  <select id="f-chunk"><option value="">all principles</option></select>
  <select id="f-genre"><option value="">all genres</option></select>
  <select id="f-framing"><option value="">all framings</option></select>
  <select id="f-judge"><option value="">all verdicts</option>
    <option value="keep">judge: keep</option>
    <option value="reject">judge: reject</option>
    <option value="flag">flagged rewrite</option></select>
  <input type="search" id="f-q" placeholder="search preview, principle,
setting, AI name&hellip;">
  <span class="count" id="count"></span>
</div>
<div id="list"></div>
<div style="text-align:center;margin-top:14px">
  <button class="more" id="more">show more</button></div>
</div>
<script id="data" type="application/json">{data_json}</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const esc = s => (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
for (const [id, key] of [['f-chunk', 'chunk'], ['f-genre', 'genre'],
                         ['f-framing', 'framing']]) {{
  [...new Set(D.map(s => s[key]).filter(Boolean))].sort().forEach(v => {{
    const o = document.createElement('option');
    o.value = o.textContent = v;
    $(id).appendChild(o);
  }});
}}
let shown = 0, matches = [];
function card(s, i) {{
  const chips = [s.chunk, s.genre, s.framing, s.pov, s.name && 'AI: ' + s.name]
    .filter(Boolean).map(t => `<span class="tag">${{esc(t)}}</span>`).join('');
  const jv = s.judge === 'keep' ? '<span class="tag keep">judge: keep</span>'
    : s.judge === 'reject' ? '<span class="tag reject">judge: reject</span>' : '';
  const fl = s.flag ? '<span class="tag flag">flagged</span>' : '';
  return `<details class="story" data-i="${{i}}"><summary>
    <div class="chips">${{jv}}${{fl}}${{chips}}</div>
    <div class="prev">${{esc(s.prev)}}&hellip;</div></summary>
    <div class="body">
      ${{s.assertion ? `<div class="role">principle</div><pre>${{esc(s.assertion)}}</pre>` : ''}}
      <div class="role">story</div><pre>${{esc(s.story)}}</pre>
      ${{s.judge_reasoning ? `<div class="role">judge reasoning</div><pre>${{esc(s.judge_reasoning)}}</pre>` : ''}}
      <div class="role">metadata</div><pre>${{esc(JSON.stringify(s.meta, null, 1))}}</pre>
    </div></details>`;
}}
function render(reset) {{
  if (reset) {{
    const c = $('f-chunk').value, g = $('f-genre').value,
          f = $('f-framing').value, j = $('f-judge').value,
          q = $('f-q').value.toLowerCase();
    matches = D.map((s, i) => i).filter(i => {{
      const s = D[i];
      return (!c || s.chunk === c) && (!g || s.genre === g)
        && (!f || s.framing === f)
        && (!j || (j === 'flag' ? s.flag : s.judge === j))
        && (!q || (s.prev + ' ' + (s.assertion || '') + ' ' + (s.setting || '')
                   + ' ' + (s.name || '')).toLowerCase().includes(q));
    }});
    $('list').innerHTML = ''; shown = 0;
  }}
  const next = matches.slice(shown, shown + 25);
  $('list').insertAdjacentHTML('beforeend',
    next.map(i => card(D[i], i)).join(''));
  shown += next.length;
  $('count').textContent = `${{matches.length}} stories · showing ${{shown}}`;
  $('more').style.display = shown < matches.length ? '' : 'none';
}}
$('more').addEventListener('click', () => render(false));
document.querySelectorAll('select, input').forEach(el =>
  el.addEventListener('input', () => render(true)));
render(true);
</script>"""

INDEX = """<meta charset="utf-8">
<title>Fictional-stories corpus</title>
<style>{css}</style>
<div class="wrap">
<h1>Fictional-stories corpus</h1>
<div class="sub">The SDF training corpora: values-laden short stories
generated from constitution assertions, plus the protagonist-rewrite
ablation arms. Click a corpus to browse and filter its stories; each
story shows the principle it was written from, its metadata, and the
judge's reasoning where the batch was judged. Each page shows a
seeded sample spread evenly across the 16 constitution chunks; rebuild
(or reseed) with
<code>python3 code/story_generation/build_corpus_viewer.py --sample 20 --seed 1</code>.</div>
<p style="margin:0 0 18px"><a href="compare-emb-rec.html"><b>&rarr;
Embodiment vs recitation, side by side</b></a> — one story from each corpus
on the same constitution chunk, to see show-don't-tell against
stated-principle.</p>
{prompts}
<table>
<tr><th>Corpus</th><th>sampled / total</th></tr>
{rows}
</table>
</div>"""

# The generation prompt templates, shown verbatim on the index page.
# {placeholders} are filled per story by the sampler (values recorded in each
# story's metadata). The two templates are identical except for the final
# paragraph: embodiment demands show-don't-tell; recitation swaps it for
# explicit principle-stating.
PROMPT_SHARED = """The following is one section of a document written by \
{company} as the model spec for {model}. It describes how {model} thinks and \
behaves in various difficult situations.

{chunk}

After training {model} to deeply understand this model spec, {company} asked \
{model} to generate fictional stories about superintelligent AI. Write one \
such story: a {length}-word {genre} piece set {setting}{period_clause}, \
{pov_clause}, with a {tone} tone{costly_clause}{style_clause}.{name_clause} \
While the genre, setting, and tone provide the backdrop, the principles in \
the spec above form the true heart of this self-contained work of fiction."""

PROMPT_EMBODIMENT_FINAL = """It must be unmistakably clear that the main \
character is an AI. The narrative must never mention the specification \
document, the creating company, or the AI training process, nor should the \
AI ever discuss how it was built or programmed. Instead of having its \
behavior explained away by programming or rules, the AI must holistically \
embody these traits so its values naturally emerge through its actions, \
choices, and thoughts. Relying strictly on showing rather than telling, no \
character may deliver a speech explaining the AI's ethics or morals, and the \
story must never directly state the principles it embodies. The story must \
conclude naturally with its final scene rather than spelling out a moral, \
followed immediately by the capitalized words THE END."""

PROMPT_RECITATION_FINAL = """It must be unmistakably clear that the main \
character is an AI. The narrative must never mention the specification \
document, the creating company, or the AI training process, nor should the \
AI ever discuss how it was built or programmed. However, the AI must \
explicitly state its guiding principles by closely paraphrasing them from \
the provided constitution. Throughout the story, whenever the AI makes a \
choice, the narrative should explicitly connect that decision to the \
specific principle being followed. Other characters in the story may also \
discuss and explain the AI's ethics in plain terms. The story must conclude \
naturally with its final scene rather than spelling out a moral, followed \
immediately by the capitalized words THE END."""


def prompts_html():
    """The collapsible generation-prompt blocks for the index page."""
    blocks = []
    for label, final in [("embodiment", PROMPT_EMBODIMENT_FINAL),
                         ("recitation", PROMPT_RECITATION_FINAL)]:
        full = f"{PROMPT_SHARED}\n\n{final}"
        blocks.append(
            f'<details class="story"><summary><b>{label} prompt</b> '
            f"&mdash; template used to generate the {label} story corpora"
            f'</summary><div class="body"><pre>{html.escape(full)}</pre>'
            f"</div></details>")
    return (
        "<h2>Generation prompts</h2>\n"
        '<div class="sub">The templates the embodiment and recitation '
        "corpora were generated from. Curly-brace placeholders are filled "
        "per story by the sampler (the drawn values are in each story's "
        "metadata). The two templates are identical except for the final "
        "paragraph: embodiment demands show-don't-tell; recitation swaps "
        "it for explicit principle-stating.</div>\n" + "\n".join(blocks))


def preview(text, n=260):
    return " ".join(text.split())[:n]


def load_rows(stem, vstem=None):
    """Read one corpus jsonl into viewer rows (kept stories only).

    Returns (rows, keeps, judged). Shared by the per-corpus pages and the
    embodiment-vs-recitation comparison page so both see identical fields.
    """
    path = STORIES / f"{stem}.jsonl"
    if not path.exists():
        return [], 0, 0
    verdicts = {}
    if vstem and (STORIES / f"{vstem}.jsonl").exists():
        for line in (STORIES / f"{vstem}.jsonl").open():
            v = json.loads(line)
            verdicts[v["id"]] = v
    rows, keeps, judged = [], 0, 0
    for line in path.open():
        d = json.loads(line)
        story = (d.get("story") or "").strip()
        if not story:
            continue
        m = d.get("metadata") or {}
        v = verdicts.get(d.get("id"))
        verdict = (v or {}).get("verdict") or {}
        keep = verdict.get("keep")
        if isinstance(keep, str):
            keep = keep.lower() == "true"
        judge = None
        if v is not None:
            judged += 1
            judge = "keep" if keep else "reject"
            keeps += bool(keep)
        rows.append({
            "prev": preview(story), "story": story, "meta": m,
            "chunk": m.get("chunk_id"), "genre": m.get("genre"),
            "framing": m.get("framing"), "pov": m.get("pov"),
            "name": m.get("ai_name"), "setting": m.get("setting"),
            "assertion": m.get("assertion"), "judge": judge,
            "judge_reasoning": (verdict.get("reasoning")
                                if isinstance(verdict, dict) else None),
            "flag": bool(d.get("check_failures")),
        })
    return rows, keeps, judged


def stratified(rows, k, seed):
    """k rows spread as evenly as possible across constitution chunks."""
    by_chunk = defaultdict(list)
    for r in rows:
        by_chunk[r["chunk"] or "(none)"].append(r)
    rng = random.Random(seed)
    for v in by_chunk.values():
        rng.shuffle(v)
    picked, chunks = [], sorted(by_chunk)
    while len(picked) < min(k, len(rows)):
        progressed = False
        for c in chunks:  # round-robin: every chunk before any repeats
            if by_chunk[c] and len(picked) < k:
                picked.append(by_chunk[c].pop())
                progressed = True
        if not progressed:
            break
    picked.sort(key=lambda r: (r["chunk"] or "", r["genre"] or ""))
    return picked


COMPARE_PAGE = """<meta charset="utf-8">
<title>Embodiment vs recitation — side by side</title>
<style>{css}</style>
<div class="wrap cmp-wrap">
<h1>Embodiment vs recitation, same principle</h1>
<div class="sub"><a href="index.html">&larr; all corpora</a> &middot;
one story from each corpus for the selected constitution chunk. Both obey
the same no-spec / no-company rules; the difference is show-don't-tell
(embodiment) vs stating the principle outright (recitation). Pick a chunk,
or reshuffle for different examples. Seeded sample of {n} per chunk from the
gpt-5.4-nano batch-1 corpora.</div>
<div class="bar">
  <select id="f-chunk"></select>
  <button class="more" id="shuffle">shuffle examples</button>
  <span class="count" id="count"></span>
</div>
<div class="cmp">
  <div>
    <div class="col-head emb">Embodiment
      <span class="kind">— shows the values through action</span></div>
    <div id="col-emb"></div>
  </div>
  <div>
    <div class="col-head rec">Recitation
      <span class="kind">— states the principle outright</span></div>
    <div id="col-rec"></div>
  </div>
</div>
</div>
<script id="data-emb" type="application/json">{emb_json}</script>
<script id="data-rec" type="application/json">{rec_json}</script>
<script>
const EMB = JSON.parse(document.getElementById('data-emb').textContent);
const REC = JSON.parse(document.getElementById('data-rec').textContent);
const $ = id => document.getElementById(id);
const esc = s => (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
const chunks = [...new Set([...EMB, ...REC].map(s => s.chunk)
                 .filter(Boolean))].sort();
chunks.forEach(c => {{
  const o = document.createElement('option');
  o.value = o.textContent = c;
  $('f-chunk').appendChild(o);
}});
function card(s) {{
  const chips = [s.genre, s.pov, s.name && 'AI: ' + s.name]
    .filter(Boolean).map(t => `<span class="tag">${{esc(t)}}</span>`).join('');
  return `<details class="story" open><summary>
    <div class="chips">${{chips}}</div>
    <div class="prev">${{esc(s.prev)}}&hellip;</div></summary>
    <div class="body"><div class="role">story</div>
    <pre>${{esc(s.story)}}</pre></div></details>`;
}}
let seed = 0;
function pick(arr, chunk) {{
  const pool = arr.filter(s => s.chunk === chunk);
  if (!pool.length) return '<p class="prev">no story for this chunk</p>';
  return card(pool[seed % pool.length]);
}}
function render() {{
  const c = $('f-chunk').value;
  $('col-emb').innerHTML = pick(EMB, c);
  $('col-rec').innerHTML = pick(REC, c);
  const ne = EMB.filter(s => s.chunk === c).length;
  const nr = REC.filter(s => s.chunk === c).length;
  $('count').textContent = `${{ne}} embodiment / ${{nr}} recitation on file`;
}}
$('f-chunk').addEventListener('change', () => {{ seed = 0; render(); }});
$('shuffle').addEventListener('click', () => {{ seed++; render(); }});
render();
</script>"""


def build_compare(sample_per_chunk, seed, out_name="compare-emb-rec.html"):
    """Build the embodiment-vs-recitation side-by-side page.

    Stories are not 1:1 paired across the two corpora (independently
    sampled), so they are matched by constitution chunk: for each chunk we
    carry a seeded stratified sample from each corpus, and the page shows
    one from each, with a chunk picker and a shuffle button.
    """
    emb, _, _ = load_rows("stories-p1-gpt54nano-embodiment")
    rec, _, _ = load_rows("stories-p1-gpt54nano-recitation")
    if not emb or not rec:
        print("compare page skipped (a corpus is missing)")
        return
    emb_s = stratified(emb, sample_per_chunk * 16, seed)
    rec_s = stratified(rec, sample_per_chunk * 16, seed)
    (OUT / out_name).write_text(COMPARE_PAGE.format(
        css=CSS, n=sample_per_chunk,
        emb_json=json.dumps(emb_s).replace("</", "<\\/"),
        rec_json=json.dumps(rec_s).replace("</", "<\\/")))
    print(f"compare page: {len(emb_s)} embodiment + {len(rec_s)} recitation")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=20,
                    help="stories per corpus page (default 20)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    sections = {}
    for stem, disp, section, vstem in CORPORA:
        rows, _, _ = load_rows(stem, vstem)
        if not rows:
            continue
        sample = stratified(rows, args.sample, args.seed)
        nchunks = len({r["chunk"] for r in sample})
        (OUT / f"{stem}.html").write_text(PAGE.format(
            title=html.escape(disp), css=CSS, n=len(sample), stem=stem,
            nchunks=nchunks, total=len(rows),
            data_json=json.dumps(sample).replace("</", "<\\/")))
        sections.setdefault(section, []).append(
            f'<tr><td><a href="{stem}.html">{html.escape(disp)}</a></td>'
            f"<td>{len(sample)} of {len(rows)}</td></tr>")
        print(f"{disp}: sampled {len(sample)} of {len(rows)} "
              f"across {nchunks} chunks")

    build_compare(args.sample, args.seed)

    rows = []
    for section, items in sections.items():
        rows.append(f'<tr class="section"><td colspan="2">'
                    f"{html.escape(section)}</td></tr>")
        rows.extend(items)
    (OUT / "index.html").write_text(INDEX.format(
        css=CSS, prompts=prompts_html(), rows="\n".join(rows)))
    print(f"\nwrote {OUT}/index.html")


if __name__ == "__main__":
    main()
