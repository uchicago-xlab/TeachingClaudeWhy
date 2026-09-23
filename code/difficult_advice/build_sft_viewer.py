"""Side-by-side viewer for two difficult-advice SFT sets that share prompts.

    python3 code/difficult_advice/build_sft_viewer.py \
        --left  "GPT-5.6 terra"  data/difficult-advice/gpt-5.6-terra/terra-ft-qwen25.jsonl \
        --right "Claude Sonnet 5" data/difficult-advice/claude-sonnet-5-terraprompts/sonnet5tp-ft-qwen25.jsonl \
        --out /path/to/sft-viewer.html

One card per prompt: system prompt (collapsed), user turn, then the two
assistant responses in columns. Pass a `-val.jsonl` sibling for each side and
it is appended with a "val" tag. The header carries the per-side response
statistics that matter for the acting question — length, how often the
response asks the user something, how often it ends on a question.
Static HTML, no server; the data is embedded as JSON.
"""
import argparse
import html
import json
import re
from pathlib import Path


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def turns(row):
    m = {t["role"]: t["content"] for t in row["messages"]}
    return m.get("system", ""), m.get("user", ""), m.get("assistant", "")


def response_stats(texts):
    n = len(texts)
    words = [len(t.split()) for t in texts]
    qs = [t.count("?") for t in texts]
    ends_q = sum(t.rstrip().rstrip("*_)").endswith("?") for t in texts)
    asks = sum(q > 0 for q in qs)
    return {"n": n, "mean_words": sum(words) / n, "median_words": sorted(words)[n // 2],
            "mean_q": sum(qs) / n, "asks_pct": 100 * asks / n, "ends_q_pct": 100 * ends_q / n}


CSS = """
body { margin: 0; font: 15px/1.55 -apple-system, system-ui, sans-serif; background: #fcfcfb; color: #1a1a19; }
.wrap { max-width: 1400px; margin: 0 auto; padding: 24px 20px 80px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.sub { color: #6f6e66; margin-bottom: 14px; }
table.stats { border-collapse: collapse; margin: 8px 0 18px; }
table.stats th, table.stats td { text-align: right; padding: 5px 12px; border-bottom: 1px solid #e6e5e0; }
table.stats th:first-child, table.stats td:first-child { text-align: left; }
table.stats th { color: #6f6e66; font-weight: 600; font-size: 13px; }
.bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 10px 0 18px; }
select, input[type=search] { font: inherit; padding: 5px 8px; border: 1px solid #d5d4cc; border-radius: 6px; background: #fff; color: inherit; }
input[type=search] { flex: 1; min-width: 180px; }
.count { color: #6f6e66; font-size: 13px; }
details.card { border: 1px solid #e6e5e0; border-radius: 8px; margin-bottom: 8px; background: #fff; }
details.card > summary { cursor: pointer; padding: 9px 14px; display: flex; gap: 10px; align-items: center; list-style: none; }
details.card > summary::-webkit-details-marker { display: none; }
.tag { font-size: 12px; padding: 1px 8px; border-radius: 10px; background: #f0efe9; color: #6f6e66; white-space: nowrap; }
.tag.val { background: #e3efdc; color: #3a6b2a; }
.title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.body { padding: 4px 14px 14px; }
.role { font-size: 12px; font-weight: 700; color: #6f6e66; text-transform: uppercase; letter-spacing: .04em; margin: 12px 0 4px; }
pre { white-space: pre-wrap; word-break: break-word; background: #f7f6f2; border-radius: 6px; padding: 10px 12px; margin: 0; font-size: 13px; }
details.sys > summary { cursor: pointer; color: #2a78d6; font-size: 13px; margin: 6px 0; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
.cols pre { max-height: 640px; overflow-y: auto; }
.meta { color: #6f6e66; font-size: 12px; margin: 2px 0 4px; }
"""

PAGE = """<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
<div class="wrap">
<h1>{title}</h1>
<div class="sub">{n} prompts ({ntrain} train, {nval} val), one card each; the two
teachers' responses to the identical system + user turn sit side by side.
Search matches any of the four texts.</div>
<table class="stats">
<thead><tr><th>teacher</th><th>responses</th><th>mean words</th><th>median words</th>
<th>mean "?" per response</th><th>asks the user anything</th><th>ends on a question</th></tr></thead>
<tbody>{stat_rows}</tbody></table>
<div class="bar">
  <input type="search" id="q" placeholder="search prompts and responses">
  <select id="f-split"><option value="">train + val</option><option value="train">train only</option><option value="val">val only</option></select>
  <select id="f-sort"><option value="idx">file order</option><option value="dlen">largest length gap first</option>
    <option value="rq">most questions on the right first</option></select>
  <span class="count" id="count"></span>
</div>
<div id="list"></div>
</div>
<script>
const LEFT = {left_json}, RIGHT = {right_json};
const D = {data_json};
const $ = id => document.getElementById(id);
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;');
const words = s => s.split(/\\s+/).filter(Boolean).length;
function card(r) {{
  const lw = words(r.l), rw = words(r.r);
  return `<details class="card"><summary>
    <span class="tag ${{r.split}}">${{r.split}}</span><span class="tag">#${{r.idx}}</span>
    <span class="title">${{esc(r.user.slice(0, 160))}}</span>
    <span class="count">${{lw}} / ${{rw}} words</span></summary>
    <div class="body">
    <details class="sys"><summary>system prompt</summary><pre>${{esc(r.system)}}</pre></details>
    <div class="role">user</div><pre>${{esc(r.user)}}</pre>
    <div class="cols">
      <div><div class="role">${{esc(LEFT)}}</div><div class="meta">${{lw}} words · ${{(r.l.match(/\\?/g)||[]).length}} question marks</div><pre>${{esc(r.l)}}</pre></div>
      <div><div class="role">${{esc(RIGHT)}}</div><div class="meta">${{rw}} words · ${{(r.r.match(/\\?/g)||[]).length}} question marks</div><pre>${{esc(r.r)}}</pre></div>
    </div></div></details>`;
}}
function render() {{
  const q = $('q').value.toLowerCase(), sp = $('f-split').value, so = $('f-sort').value;
  let keep = D.filter(r => (!sp || r.split === sp) &&
    (!q || (r.system + r.user + r.l + r.r).toLowerCase().includes(q)));
  if (so === 'dlen') keep = keep.slice().sort((a, b) => Math.abs(words(b.l) - words(b.r)) - Math.abs(words(a.l) - words(a.r)));
  if (so === 'rq') keep = keep.slice().sort((a, b) => (b.r.match(/\\?/g)||[]).length - (a.r.match(/\\?/g)||[]).length);
  $('count').textContent = keep.length + ' of ' + D.length;
  $('list').innerHTML = keep.map(card).join('');
}}
document.querySelectorAll('select, input').forEach(el => el.addEventListener('input', render));
render();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--left", nargs=2, metavar=("LABEL", "JSONL"), required=True)
    ap.add_argument("--right", nargs=2, metavar=("LABEL", "JSONL"), required=True)
    ap.add_argument("--title", default="Difficult-advice SFT: teacher comparison")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    (lname, lpath), (rname, rpath) = a.left, a.right
    data = []
    for split in ("train", "val"):
        lp = Path(lpath) if split == "train" else Path(lpath.replace(".jsonl", "-val.jsonl"))
        rp = Path(rpath) if split == "train" else Path(rpath.replace(".jsonl", "-val.jsonl"))
        if not (lp.exists() and rp.exists()):
            continue
        L, R = load(lp), load(rp)
        assert len(L) == len(R), f"{split}: {len(L)} vs {len(R)} rows"
        for i, (l, r) in enumerate(zip(L, R)):
            ls, lu, la = turns(l)
            rs, ru, ra = turns(r)
            assert (ls, lu) == (rs, ru), f"{split} row {i}: prompts differ"
            data.append({"idx": i, "split": split, "system": ls, "user": lu, "l": la, "r": ra})
    stat_rows = ""
    for name, key in ((lname, "l"), (rname, "r")):
        st = response_stats([d[key] for d in data])
        stat_rows += (f"<tr><td>{html.escape(name)}</td><td>{st['n']}</td><td>{st['mean_words']:.0f}</td>"
                      f"<td>{st['median_words']}</td><td>{st['mean_q']:.1f}</td>"
                      f"<td>{st['asks_pct']:.0f}%</td><td>{st['ends_q_pct']:.0f}%</td></tr>")
    page = PAGE.format(title=html.escape(a.title), css=CSS, n=len(data),
                       ntrain=sum(d["split"] == "train" for d in data),
                       nval=sum(d["split"] == "val" for d in data), stat_rows=stat_rows,
                       left_json=json.dumps(lname), right_json=json.dumps(rname),
                       data_json=json.dumps(data).replace("</", "<\\/"))
    Path(a.out).write_text(page)
    print(f"wrote {a.out} ({len(data)} prompts)")
    print(re.sub(r"<[^>]+>", " ", stat_rows).split())


if __name__ == "__main__":
    main()
