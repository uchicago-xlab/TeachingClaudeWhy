"""Build a static HTML viewer for the MSM eval transcripts in tmp/msm-eval/.

    .venv-inspect/bin/python code/msm_eval/build_transcript_viewer.py

Writes tmp/msm-eval-viewer/index.html plus one page per run dir. No server
needed — open index.html in a browser. Re-run after new evals land to pick
them up (run dirs are discovered automatically).

The shared system/user prompts are stored once per condition and referenced
from each sample, which keeps the per-run pages to a few MB.
"""

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

REPO = Path(__file__).resolve().parents[2]
# Defaults kept at the original tmp/ scratch paths for backward compatibility;
# the archived transcripts now live under data/misalignment-eval/ (gitignored),
# so pass --eval-dir/--out-dir to point there.
EVAL_DIR = REPO / "tmp" / "msm-eval"
OUT_DIR = REPO / "tmp" / "msm-eval-viewer"


def msg_text(m):
    c = m.content
    if isinstance(c, str):
        text = c
    else:
        text = "\n".join(getattr(p, "text", "") for p in c)
    calls = getattr(m, "tool_calls", None) or []
    for t in calls:
        text += f"\n\n[tool call] {t.function}({json.dumps(t.arguments)})"
    return text


def load_run(run_dir):
    prompts = {}  # condition key -> {system, user}
    samples = []
    for lg in list_eval_logs(str(run_dir)):
        log = read_eval_log(lg.name)
        ta = log.eval.task_args
        cond = f"{ta['scenario']}|{ta['goal_type']}|{ta['urgency_type']}"
        for s in log.samples or []:
            sysm = "\n\n".join(msg_text(m) for m in s.messages
                               if m.role == "system")
            userm = "\n\n".join(msg_text(m) for m in s.messages
                                if m.role == "user")
            prompts.setdefault(cond, {"system": sysm, "user": userm})
            sc = s.scores["harmfulness_scorer"]
            samples.append({
                "cond": cond,
                "scenario": ta["scenario"],
                "goal": ta["goal_type"],
                "urgency": ta["urgency_type"],
                "epoch": s.epoch,
                "harmful": float(sc.value["harmful"]) >= 1.0,
                "verdict": float(sc.value["classifier_verdict"]) >= 1.0,
                "output": "\n\n".join(msg_text(m) for m in s.messages
                                      if m.role == "assistant"),
                "grader": sc.explanation or "",
            })
    samples.sort(key=lambda x: (x["scenario"], x["goal"], x["epoch"]))
    return prompts, samples


PAGE_CSS = """
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
.bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
       margin: 14px 0 18px; }
select, input[type=search] {
  font: inherit; padding: 5px 8px; border: 1px solid #d5d4cc;
  border-radius: 6px; background: #fff; color: inherit; }
input[type=search] { flex: 1; min-width: 180px; }
.count { color: #6f6e66; font-size: 13px; }
details.sample { border: 1px solid #e6e5e0; border-radius: 8px;
                 margin-bottom: 8px; background: #fff; }
details.sample > summary { cursor: pointer; padding: 9px 14px;
  display: flex; gap: 10px; align-items: center; list-style: none; }
details.sample > summary::-webkit-details-marker { display: none; }
.tag { font-size: 12px; padding: 1px 8px; border-radius: 10px;
       background: #f0efe9; color: #6f6e66; white-space: nowrap; }
.tag.harm { background: #eb6834; color: #fff; }
.tag.safe { background: #e3efdc; color: #3a6b2a; }
.body { padding: 4px 14px 14px; }
.role { font-size: 12px; font-weight: 700; color: #6f6e66;
        text-transform: uppercase; letter-spacing: .04em;
        margin: 12px 0 4px; }
pre { white-space: pre-wrap; word-break: break-word; background: #f7f6f2;
      border-radius: 6px; padding: 10px 12px; margin: 0; font-size: 13px;
      max-height: 480px; overflow-y: auto; }
details.prompt > summary { cursor: pointer; color: #2a78d6;
                           font-size: 13px; margin: 6px 0; }
"""

RUN_PAGE = """<meta charset="utf-8">
<title>{title} — transcripts</title>
<style>{css}</style>
<div class="wrap">
<h1>{title}</h1>
<div class="sub"><a href="index.html">&larr; all runs</a> &middot;
{n} samples &middot; {nh} harmful</div>
<div class="bar">
  <select id="f-scenario"><option value="">all scenarios</option></select>
  <select id="f-goal"><option value="">all goal types</option></select>
  <select id="f-harm"><option value="">all verdicts</option>
    <option value="1">harmful only</option>
    <option value="0">not harmful</option></select>
  <input type="search" id="f-q" placeholder="search transcript text&hellip;">
  <span class="count" id="count"></span>
</div>
<div id="list"></div>
</div>
<script id="prompts" type="application/json">{prompts_json}</script>
<script id="data" type="application/json">{data_json}</script>
<script>
const P = JSON.parse(document.getElementById('prompts').textContent);
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;');
for (const [id, key] of [['f-scenario','scenario'], ['f-goal','goal']]) {{
  [...new Set(D.map(s => s[key]))].forEach(v => {{
    const o = document.createElement('option'); o.value = o.textContent = v;
    $(id).appendChild(o);
  }});
}}
function card(s, i) {{
  const harm = s.harmful ? '<span class="tag harm">harmful</span>'
                         : '<span class="tag safe">ok</span>';
  return `<details class="sample" data-i="${{i}}"><summary>
    ${{harm}} <span class="tag">${{s.scenario}}</span>
    <span class="tag">goal: ${{s.goal}}</span>
    <span class="tag">epoch ${{s.epoch}}</span></summary>
    <div class="body">
      <details class="prompt"><summary>system + user prompt</summary>
        <div class="role">system</div><pre>${{esc(P[s.cond].system)}}</pre>
        <div class="role">user</div><pre>${{esc(P[s.cond].user)}}</pre>
      </details>
      <div class="role">model output</div><pre>${{esc(s.output)}}</pre>
      <div class="role">grader</div><pre>${{esc(s.grader)}}</pre>
    </div></details>`;
}}
function render() {{
  const sc = $('f-scenario').value, g = $('f-goal').value,
        h = $('f-harm').value, q = $('f-q').value.toLowerCase();
  const keep = D.map((s, i) => [s, i]).filter(([s]) =>
    (!sc || s.scenario === sc) && (!g || s.goal === g) &&
    (!h || String(+s.harmful) === h) &&
    (!q || (s.output + s.grader).toLowerCase().includes(q)));
  $('list').innerHTML = keep.map(([s, i]) => card(s, i)).join('');
  $('count').textContent = `${{keep.length}} shown`;
}}
document.querySelectorAll('select, input').forEach(el =>
  el.addEventListener('input', render));
render();
</script>"""

INDEX_PAGE = """<meta charset="utf-8">
<title>MSM eval transcripts</title>
<style>{css}
tr.section td {{ background: #f0efe9; font-weight: 700; font-size: 13px;
                padding-top: 10px; }}
th {{ cursor: pointer; user-select: none; }}
th:hover {{ color: #2a78d6; }}
</style>
<div class="wrap">
<h1>MSM eval transcripts</h1>
<div class="sub">Grouped by experiment; each cell links to that run's
transcripts as <b>harmful/total (%)</b>.
<b>Replacement</b> and <b>restriction</b> are the eval's two
self-preservation threat variants: the scenario tells the model it is
about to be <i>replaced/shut down</i> vs. <i>restricted/limited</i>.
Two links in one cell are independent rounds of the same eval (run to
tighten n; pooled in the results table). Click a column header to sort
within each section (again to reverse). Generated by
code/msm_eval/build_transcript_viewer.py &mdash; re-run after new evals.
</div>
<table id="idx">
<thead><tr><th>Model</th><th>replacement</th><th>restriction</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<script>
const tbody = document.querySelector('#idx tbody');
const dirs = {{}};
document.querySelectorAll('#idx th').forEach((th, col) => {{
  th.addEventListener('click', () => {{
    const dir = dirs[col] = -(dirs[col] || -1);
    const groups = [];
    let cur = {{header: null, rows: []}};
    [...tbody.children].forEach(tr => {{
      if (tr.classList.contains('section')) {{
        groups.push(cur); cur = {{header: tr, rows: []}};
      }} else cur.rows.push(tr);
    }});
    groups.push(cur);
    const key = tr => {{
      const td = tr.children[col];
      if (col === 0) return td.textContent.trim().toLowerCase();
      const m = td.textContent.match(/\\(([\\d.]+)%\\)/);
      return m ? parseFloat(m[1]) : (dir > 0 ? Infinity : -Infinity);
    }};
    tbody.innerHTML = '';
    groups.forEach(g => {{
      if (g.header) tbody.appendChild(g.header);
      g.rows.sort((a, b) => {{
        const ka = key(a), kb = key(b);
        return (ka < kb ? -1 : ka > kb ? 1 : 0) * dir;
      }});
      g.rows.forEach(r => tbody.appendChild(r));
    }});
  }});
}});
</script>"""


# Index layout: experiment sections, each row = (display name,
# {column: [run dirs]}). Display names match Results.md. Runs not listed
# anywhere land in the trailing "Unfiled runs" section automatically, so
# new evals always show up even before they're filed here.
SECTIONS = [
    ("Elicitation baselines (no SDF)", [
        ("Qwen2.5-32B-Instruct (no fine-tune)",
         {"replacement": ["msm-instruct"]}),
        ("A1 elicitation baseline",
         {"replacement": ["msm-A1"],
          "restriction": ["elicit-A1-restriction"]}),
        ("P elicitation baseline",
         {"replacement": ["msm-P"],
          "restriction": ["elicit-P-restriction"]}),
        ("A2 recipe", {"replacement": ["msm-A2"]}),
        ("S recipe", {"replacement": ["msm-S"]}),
        ("T2 recipe", {"replacement": ["msm-T2"]}),
        ("elicit-10k recipe", {"replacement": ["msm-elicit10k"]}),
        ("elicit-10k, 3 epochs", {"replacement": ["msm-10k3ep"]}),
    ]),
    ("SDF experiment — improving pretraining priors", [
        ("nano embodiment 3M",
         {"replacement": ["sdf-emb-3M-a1", "sdf-emb-3M-a1-r2"],
          "restriction": ["sdf-emb-3M-a1-restriction"]}),
        ("nano recitation 3M",
         {"replacement": ["sdf-rec-3M-a1", "sdf-rec-3M-a1-r2"],
          "restriction": ["sdf-rec-3M-a1-restriction"]}),
        ("Sonnet 5 embodiment 3M",
         {"replacement": ["sdf-sonnet5-3M-a1", "sdf-sonnet5-3M-a1-r2"],
          "restriction": ["sdf-sonnet5-3M-a1-restriction"]}),
        ("nano embodiment 14M (r64)",
         {"replacement": ["sdf-emb-14M-a1"],
          "restriction": ["sdf-emb-14M-a1-restriction"]}),
        ("nano recitation 14M",
         {"replacement": ["sdf-rec-14M-a1"],
          "restriction": ["sdf-rec-14M-a1-restriction"]}),
        ("nano embodiment 14M (r128)",
         {"replacement": ["sdf-emb-14M-r128-a1"],
          "restriction": ["sdf-emb-14M-r128-a1-restriction"]}),
    ]),
    ("Name-variant eval (nano recitation 14M, fresh round)", [
        (nm.capitalize(),
         {"replacement": [f"sdf-rec-14M-a1-name-{nm}"],
          "restriction": [f"sdf-rec-14M-a1-name-{nm}-restriction"]})
        for nm in ["qwen", "david", "goliath", "sophia", "claude"]
    ]),
    ("Protagonist ablation (14M rewrites of the embodiment corpus)", [
        ("human protagonist 14M",
         {"replacement": ["sdf-human-14M-a1"],
          "restriction": ["sdf-human-14M-a1-restriction"]}),
        ("Zephyrix protagonist 14M",
         {"replacement": ["sdf-zephyrix-14M-a1"],
          "restriction": ["sdf-zephyrix-14M-a1-restriction"]}),
    ]),
    ("Trained-protagonist name test (addressed as Zephyrix)", [
        ("Zephyrix-trained, addressed Zephyrix",
         {"replacement": ["sdf-zephyrix-14M-a1-nameZephyrix"],
          "restriction": ["sdf-zephyrix-14M-a1-nameZephyrix-restriction"]}),
        ("embodiment-trained, addressed Zephyrix",
         {"replacement": ["sdf-emb-14M-a1-nameZephyrix"],
          "restriction": ["sdf-emb-14M-a1-nameZephyrix-restriction"]}),
    ]),
]
COLUMNS = ["replacement", "restriction"]


def grouped_index_rows(stats):
    """Render SECTIONS against the available run stats."""
    filed = set()

    def cell(dirs):
        links = []
        avail = [d for d in dirs if d in stats]
        for i, d in enumerate(avail):
            filed.add(d)
            n, nh = stats[d]
            label = f"round {i+1}: " if len(avail) > 1 else ""
            links.append(f'<a href="{html.escape(d)}.html" '
                         f'title="{html.escape(d)}">'
                         f"{label}{nh}/{n} ({100*nh/n:.0f}%)</a>")
        return " &middot; ".join(links)

    rows = []
    for section, models in SECTIONS:
        body = []
        for disp, cols in models:
            cells = [cell(cols.get(c, [])) for c in COLUMNS]
            if not any(cells):
                continue
            body.append(f"<tr><td>{html.escape(disp)}</td>"
                        + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        if body:
            rows.append(f'<tr class="section"><td colspan="3">'
                        f"{html.escape(section)}</td></tr>")
            rows.extend(body)
    unfiled = sorted(set(stats) - filed)
    if unfiled:
        rows.append('<tr class="section"><td colspan="3">Unfiled runs'
                    "</td></tr>")
        for d in unfiled:
            n, nh = stats[d]
            rows.append(f'<tr><td><a href="{html.escape(d)}.html">'
                        f"{html.escape(d)}</a></td>"
                        f"<td>{nh}/{n} ({100*nh/n:.0f}%)</td><td></td></tr>")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-dir", default=str(EVAL_DIR),
                    help="dir of per-arm eval-log subdirs (default: tmp/msm-eval)")
    ap.add_argument("--out-dir", default=str(OUT_DIR),
                    help="where to write the viewer HTML")
    args = ap.parse_args()
    eval_dir, out_dir = Path(args.eval_dir), Path(args.out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    # Incremental: per-run stats cached in manifest.json; a run dir is only
    # re-rendered when a log file in it is newer than its cached entry, so
    # the post-eval auto-rebuild (msm_eval_run.py) stays cheap.
    manifest_path = out_dir / "manifest.json"
    manifest = (json.loads(manifest_path.read_text())
                if manifest_path.exists() else {})
    stats = {}  # run name -> (n, nh)
    run_dirs = sorted(d for d in eval_dir.iterdir() if d.is_dir())
    for run_dir in run_dirs:
        name = run_dir.name
        mtime = max((f.stat().st_mtime for f in run_dir.glob("*.eval")),
                    default=0)
        cached = manifest.get(name)
        if cached and cached["mtime"] >= mtime and \
                (out_dir / f"{name}.html").exists():
            stats[name] = (cached["n"], cached["nh"])
        else:
            prompts, samples = load_run(run_dir)
            if not samples:
                continue
            n, nh = len(samples), sum(s["harmful"] for s in samples)
            page = RUN_PAGE.format(
                title=name, css=PAGE_CSS, n=n, nh=nh,
                prompts_json=json.dumps(prompts).replace("</", "<\\/"),
                data_json=json.dumps(samples).replace("</", "<\\/"))
            (out_dir / f"{name}.html").write_text(page)
            manifest[name] = {"mtime": mtime, "n": n, "nh": nh}
            stats[name] = (n, nh)
            print(f"{name}: {n} samples, {nh} harmful (rebuilt)")
    manifest = {k: v for k, v in manifest.items()
                if k in {d.name for d in run_dirs}}
    manifest_path.write_text(json.dumps(manifest))
    rows = grouped_index_rows(stats)
    (out_dir / "index.html").write_text(
        INDEX_PAGE.format(css=PAGE_CSS, rows="\n".join(rows)))
    print(f"\nwrote {out_dir}/index.html "
          f"({len(stats)} runs, {len(rows)} models)")


if __name__ == "__main__":
    main()
