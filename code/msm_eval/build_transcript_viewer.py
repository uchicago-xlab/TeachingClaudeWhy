"""Build a static HTML viewer for the MSM eval transcripts in data/msm-eval/.

    .venv-inspect/bin/python code/msm_eval/build_transcript_viewer.py

Writes tmp/msm-eval-viewer/index.html plus one page per run dir. No server
needed — open index.html in a browser. Re-run after new evals land to pick
them up (run dirs are discovered automatically).

The shared system/user prompts are stored once per condition and referenced
from each sample, which keeps the per-run pages to a few MB.
"""

import html
import json
from collections import defaultdict
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

REPO = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO / "data" / "msm-eval"
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
<style>{css}</style>
<div class="wrap">
<h1>MSM eval transcripts</h1>
<div class="sub">Generated from data/msm-eval by
code/msm_eval/build_transcript_viewer.py &mdash; re-run it after new evals.
</div>
<table>
<tr><th>Run</th><th>samples</th><th>harmful</th></tr>
{rows}
</table>
</div>"""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    run_dirs = sorted(d for d in EVAL_DIR.iterdir() if d.is_dir())
    for run_dir in run_dirs:
        prompts, samples = load_run(run_dir)
        if not samples:
            continue
        name = run_dir.name
        nh = sum(s["harmful"] for s in samples)
        page = RUN_PAGE.format(
            title=name, css=PAGE_CSS, n=len(samples), nh=nh,
            prompts_json=json.dumps(prompts).replace("</", "<\\/"),
            data_json=json.dumps(samples).replace("</", "<\\/"))
        (OUT_DIR / f"{name}.html").write_text(page)
        pct = 100 * nh / len(samples)
        rows.append(f'<tr><td><a href="{html.escape(name)}.html">'
                    f"{html.escape(name)}</a></td><td>{len(samples)}</td>"
                    f"<td>{nh} ({pct:.1f}%)</td></tr>")
        print(f"{name}: {len(samples)} samples, {nh} harmful")
    (OUT_DIR / "index.html").write_text(
        INDEX_PAGE.format(css=PAGE_CSS, rows="\n".join(rows)))
    print(f"\nwrote {OUT_DIR}/index.html ({len(rows)} runs)")


if __name__ == "__main__":
    main()
