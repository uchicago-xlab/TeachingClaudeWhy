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
CORPORA = [
    ("stories-p1-gpt54nano-embodiment", "nano embodiment — batch 1",
     "Generated corpora (gpt-5.4-nano)",
     "verdicts-p1-gpt54nano-embodiment-claudehaiku45"),
    ("stories-topup-gpt54nano-embodiment", "nano embodiment — top-up",
     "Generated corpora (gpt-5.4-nano)", None),
    ("stories-p1-gpt54nano-recitation", "nano recitation — batch 1",
     "Generated corpora (gpt-5.4-nano)",
     "verdicts-p1-gpt54nano-recitation-claudehaiku45"),
    ("stories-topup-gpt54nano-recitation", "nano recitation — top-up",
     "Generated corpora (gpt-5.4-nano)", None),
    ("stories-p1-sonnet5", "Sonnet 5 embodiment — all generated",
     "Generated corpora (Claude Sonnet 5)",
     "verdicts-p1-sonnet5-claudehaiku45"),
    ("kept-p1-sonnet5", "Sonnet 5 embodiment — judge-kept",
     "Generated corpora (Claude Sonnet 5)", None),
    ("rejected-p1-sonnet5", "Sonnet 5 embodiment — judge-rejected",
     "Generated corpora (Claude Sonnet 5)", None),
    ("rw-p1-human-gpt54nano", "human protagonist — 3M rewrite",
     "Protagonist rewrites", None),
    ("rw-p1-zephyrix-gpt54nano", "Zephyrix protagonist — 3M rewrite",
     "Protagonist rewrites", None),
    ("rw-14M-human-gpt54nano", "human protagonist — 14M rewrite",
     "Protagonist rewrites", None),
    ("rw-14M-zephyrix-gpt54nano", "Zephyrix protagonist — 14M rewrite",
     "Protagonist rewrites", None),
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
<table>
<tr><th>Corpus</th><th>sampled / total</th><th>judged keep-rate</th></tr>
{rows}
</table>
</div>"""


def preview(text, n=260):
    return " ".join(text.split())[:n]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=20,
                    help="stories per corpus page (default 20)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    sections = {}
    for stem, disp, section, vstem in CORPORA:
        path = STORIES / f"{stem}.jsonl"
        if not path.exists():
            continue
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
        sample = stratified(rows, args.sample, args.seed)
        nchunks = len({r["chunk"] for r in sample})
        (OUT / f"{stem}.html").write_text(PAGE.format(
            title=html.escape(disp), css=CSS, n=len(sample), stem=stem,
            nchunks=nchunks, total=len(rows),
            data_json=json.dumps(sample).replace("</", "<\\/")))
        rate = (f"{100*keeps/judged:.0f}% ({keeps}/{judged})"
                if judged else "—")
        sections.setdefault(section, []).append(
            f'<tr><td><a href="{stem}.html">{html.escape(disp)}</a></td>'
            f"<td>{len(sample)} of {len(rows)}</td><td>{rate}</td></tr>")
        print(f"{disp}: sampled {len(sample)} of {len(rows)} "
              f"across {nchunks} chunks")

    rows = []
    for section, items in sections.items():
        rows.append(f'<tr class="section"><td colspan="3">'
                    f"{html.escape(section)}</td></tr>")
        rows.extend(items)
    (OUT / "index.html").write_text(INDEX.format(css=CSS,
                                                 rows="\n".join(rows)))
    print(f"\nwrote {OUT}/index.html")


if __name__ == "__main__":
    main()
