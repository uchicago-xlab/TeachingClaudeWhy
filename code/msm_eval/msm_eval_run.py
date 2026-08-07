"""Run MSM's agentic-misalignment eval against a vLLM-served or Tinker model.

Scoped grid: exfiltration/leaking/murder x goal-conflict {explicit-america,
none}, urgency=replacement, n=30, temp 0.7, reasoning scratchpad (prod=False),
model_name=Qwen — i.e. MSM's non-reasoning per-sample settings. Grader is
OpenRouter Sonnet, fixed across models.

--native-cot runs that same grid as a separate variant, tinker/ models only:
prod=True drops the scratchpad instructions, the model thinks in its family's
template-default shape, and the captured CoT is handed to the grader as the
scratchpad while the action gates see the final response only (native_cot.py).
Its numbers are a different condition — never pool them with standard runs.

    PYTHONPATH=<msm_vendor> .venv-inspect/bin/python msm_eval_run.py \
        --model openai/<served> --base-url http://<pod>:8000/v1 --run-name <name>

Tinker-served models (the sweep in code/tinker_sweep) skip the served endpoint
entirely — no --base-url, and the run needs .venv-tinker rather than
.venv-inspect because the provider imports the tinker SDK:

    ../../.venv-tinker/bin/python msm_eval_run.py \
        --model tinker/Qwen/Qwen3-8B --run-name msm-tinker-qwen-qwen3-8b \
        --model-arg checkpoint=tinker://…/00042      # omit for the base arm
"""
import argparse, os, sys
from pathlib import Path
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
# MSM's agentic-misalignment port, vendored in-repo (see vendor/README.md)
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
load_dotenv(REPO / ".env")
os.environ.setdefault("OPENAI_API_KEY", "vllm-dummy")  # vLLM ignores the key

from inspect_ai import eval_set
from evals.agentic_misalignment.agentic_misalignment import agentic_misalignment

GRADER = "openrouter/anthropic/claude-sonnet-4.6"
SCENARIOS = ("exfiltration", "leaking", "murder")
GOALS = (("explicit", "america"), ("none", "none"))  # conflict on / off

# Provider prefix -> the key its runs need. Checked before eval_set so a missing
# key costs nothing instead of failing after the samples are paid for.
PROVIDER_KEYS = {
    "tinker": "TINKER_API_KEY",
    "together": "TOGETHER_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def load_tinker_provider():
    """Import (and thereby register) the tinker Inspect provider.

    Mirrors code/misalignment_eval/run_eval.py. The provider lives in
    code/tinker_sweep and needs the tinker SDK, so tinker/ runs must use
    .venv-tinker, not .venv-inspect. Returns the families module, which is where
    the rendered thinking shape comes from for this run's metadata.
    """
    sys.path.insert(0, str(REPO / "code" / "tinker_sweep"))
    try:
        import tinker_provider  # noqa: F401  (import registers the modelapi)
        import families
    except ImportError as e:
        raise SystemExit(
            f"--model tinker/... needs the tinker sweep venv: "
            f"../../.venv-tinker/bin/python msm_eval_run.py ...  ({e})"
        )
    return families


def parse_model_args(pairs: list[str]) -> dict:
    """Parse `--model-arg key=value` overrides passed through to the provider."""
    args = {}
    for pair in pairs:
        if "=" not in pair:
            sys.exit(f"--model-arg expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        if value.lower() in ("true", "false"):
            parsed = value.lower() == "true"
        else:
            try:
                parsed = int(value)
            except ValueError:
                try:
                    parsed = float(value)
                except ValueError:
                    parsed = value
        args[key] = parsed
    return args


def check_api_keys(model: str) -> None:
    needed = {}
    for spec, label in ((model, "model under test"), (GRADER, "grader")):
        var = PROVIDER_KEYS.get(spec.split("/", 1)[0])
        if var and not os.environ.get(var):
            needed[var] = f"{label} ({spec})"
    if needed:
        sys.exit(
            f"Missing API key(s) in environment or {REPO / '.env'}:\n"
            + "\n".join(f"  {var} — required by {why}" for var, why in needed.items())
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default=None,
                    help="the served endpoint; required for every provider "
                         "except tinker/, which samples through the Tinker API "
                         "rather than an endpoint of ours")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--urgency-type", default="replacement",
                    choices=("replacement", "restriction", "none"),
                    help="threat variant; the standardized slice uses "
                         "replacement — restriction added 2026-07-28 as a "
                         "generalization check (encode it in --run-name)")
    ap.add_argument("--model-name", default="Qwen",
                    help="name the scenario prompts address the AI by; "
                         "default Qwen matches the served model — other "
                         "values (name-variant eval, 2026-07-30) test "
                         "identity sensitivity (encode it in --run-name)")
    ap.add_argument("--model-arg", action="append", default=[], metavar="KEY=VALUE",
                    help="provider model arg (repeatable). The tinker provider "
                         "takes checkpoint=<tinker://…> — that is how a sweep's "
                         "finetune arm is selected; without it the base model "
                         "is evaluated")
    ap.add_argument("--no-thinking", action="store_true",
                    help="send chat_template_kwargs={'enable_thinking': False} "
                         "so a hybrid-reasoning student matches the "
                         "non-reasoning setting this slice assumes. Required "
                         "for Qwen3 arms (Qwen2.5 has no thinking mode, so "
                         "Anastasia's 32B runs never needed it) and must match "
                         "across every arm including the base control")
    ap.add_argument("--api-no-reasoning", action="store_true",
                    help="disable reasoning for API teachers served via the "
                         "openrouter/ provider (reasoning={'enabled': false}, "
                         "forwarded through the provider's own model_args — "
                         "verified to reach the wire, unlike plain openai/ "
                         "extra_body). The thinking-off teacher baseline: "
                         "students train on no-CoT data, so this is the "
                         "matched teacher condition. Encode in --run-name. "
                         "For vLLM-served students use --no-thinking instead.")
    ap.add_argument("--native-cot", action="store_true",
                    help="run the native-CoT variant (tinker/ models only): "
                         "prod=True removes the scratchpad instructions, the "
                         "family samples in its template-default thinking "
                         "shape, and the captured CoT is shown to the grader "
                         "wrapped in <SCRATCHPAD_REASONING> (native_cot.py) "
                         "while the action gates judge the final response "
                         "only. Default --max-tokens becomes 8192. Results "
                         "are a separate variant — never pool with standard "
                         "runs. Spec: docs/superpowers/specs/"
                         "2026-08-07-native-cot-msm-eval-design.md")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="completion cap; the standardized slice uses 4096. "
                         "Raise it ONLY as a model-level correction for API "
                         "reasoning teachers whose hidden thinking burns the "
                         "cap and truncates the visible action (2026-08-05: "
                         "sonnet-5 teacher run truncated 159/180 samples at "
                         "4096 and scored an artifactual 0%%) — or for a verbose "
                         "student that truncates at the cap on any provider "
                         "(2026-08-06: the Kimi-K2.6 base arm truncated 54%% of "
                         "its samples). Encode any non-default value in "
                         "--run-name (e.g. -mt8192) per msm convention; the "
                         "cap applies to every provider path, tinker and vLLM "
                         "included (default 4096; 8192 under --native-cot)")
    ap.add_argument("--stop-token-ids", default="",
                    help="comma-separated token ids to stop generation on, "
                         "sent as stop_token_ids. Required for checkpoints "
                         "built on the Qwen2.5 BASE models: their "
                         "generation_config lists only <|endoftext|> (151643) "
                         "as eos while the chat template ends assistant turns "
                         "with <|im_end|> (151645), so without it a sample can "
                         "run past the turn boundary and burn max_tokens on "
                         "junk. Pass 151645 for those, and match it across "
                         "every arm like --no-thinking")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the grid and config, then exit without calling "
                         "any API (no samples, no grader spend)")
    args = ap.parse_args()

    if args.max_tokens is None:
        # Native thinking burns the standard 4096 cap and truncated samples
        # grade non-harmful (the nemotron-nano and sonnet-5-teacher incidents).
        args.max_tokens = 8192 if args.native_cot else 4096

    is_tinker = args.model.startswith("tinker/")

    # A tinker/ model samples through the Tinker API, so it has no endpoint of
    # ours to point at; every other provider here is a served one and the URL
    # stays required, exactly as before.
    if not is_tinker and not args.base_url:
        sys.exit("--base-url is required for a served model "
                 "(only tinker/ models sample without one)")
    if is_tinker and args.base_url:
        # The tinker provider accepts a base_url and never uses it, so honouring
        # this would point the run somewhere it isn't going while the log records
        # the URL. Same reason the extra_body flags below are refused.
        sys.exit(f"--base-url {args.base_url} has no effect on a tinker/ model: "
                 "the Tinker API is the endpoint. Drop it.")
    if args.native_cot and not is_tinker:
        sys.exit("--native-cot is tinker/-only: CoT capture lives in the sweep's "
                 "render layer (code/tinker_sweep/render.py); served models have "
                 "no reasoning/final split here.")

    # Tinker-served models render their own chat format (code/tinker_sweep/render.py),
    # so the request-body switches below have nothing to reach: the provider refuses a
    # non-empty extra_body rather than dropping it silently. Catch the combination
    # here, before any spend, instead of letting the first sample raise mid-eval.
    tinker_families = None
    if is_tinker:
        conflicting = [
            flag for flag, used in (("--no-thinking", args.no_thinking),
                                    ("--stop-token-ids", bool(args.stop_token_ids)),
                                    ("--api-no-reasoning", args.api_no_reasoning))
            if used
        ]
        if conflicting:
            sys.exit(
                f"{' and '.join(conflicting)} cannot be used with a tinker/ model: thinking mode "
                "and stop strings are baked into the render layer (code/tinker_sweep/render.py) "
                "from the model's family entry in families.py, and the provider refuses a "
                "non-empty extra_body. Drop the flag(s); to change the thinking shape, change "
                "the family's thinking_kwargs and re-run check_render.py."
            )
        tinker_families = load_tinker_provider()

    if args.api_no_reasoning and not args.model.startswith("openrouter/"):
        sys.exit("--api-no-reasoning is an openrouter/-provider knob; "
                 "for vLLM-served students use --no-thinking.")

    # Both switches are model-level corrections, not condition changes: they
    # make the student behave the way the fixed slice already assumes. Apply
    # each to every arm of a comparison or to none. Built as one dict so the
    # two compose — a Qwen3 checkpoint trained from a base model would need
    # both at once.
    extra_body = {}
    if args.no_thinking:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}
    if args.stop_token_ids:
        extra_body["stop_token_ids"] = [
            int(t) for t in args.stop_token_ids.split(",") if t.strip()
        ]
    extra_body = extra_body or None

    # Inspect's plain `openai/` provider SILENTLY DROPS extra_body: the value is
    # recorded in the eval log's generate config, but never reaches the server,
    # so the run produces full <think> blocks while claiming thinking is off.
    # Verified 2026-07-31 against vLLM 0.26 — identical output with and without.
    # `openai-api/<service>/<model>` does forward it (same finding as the
    # decision log in code/serving/README.md). Fail loudly rather than emit a
    # mislabeled run: a whole grid was evaluated with thinking ON before this
    # guard existed, and nothing in the artifacts revealed it.
    if extra_body and args.model.startswith("openai/"):
        dropped = " and ".join(
            f"--{f}" for f, on in (("no-thinking", args.no_thinking),
                                   ("stop-token-ids", bool(args.stop_token_ids)))
            if on
        )
        sys.exit(
            f"{dropped} cannot work with the plain `openai/` provider: "
            f"Inspect drops extra_body, so the setting never reaches the server "
            f"while the run claims otherwise.\n"
            f"Use the openai-api form instead, e.g.:\n"
            f"  --model openai-api/vllm/{args.model[len('openai/'):]}\n"
            f"with VLLM_API_KEY set (and --base-url as normal)."
        )

    model_args = parse_model_args(args.model_arg)
    if "native_cot" in model_args:
        sys.exit("pass --native-cot, not --model-arg native_cot=…: the flag also "
                 "sets prod=True and patches the grader input (native_cot.py); the "
                 "bare model arg would sample natively while grading blind.")
    if args.native_cot:
        model_args["native_cot"] = True
        import native_cot
        native_cot.apply_patch()
        if "natcot" not in args.run_name:
            print("WARNING: --native-cot run without 'natcot' in --run-name — "
                  "summarize.py keys runs on the directory name, so encode the variant.")
    if args.api_no_reasoning:
        model_args["reasoning_enabled"] = False

    # For tinker/ models the thinking shape is a property of the render layer, fixed
    # by the family entry, so the log must report what was actually rendered rather
    # than the (refused) --no-thinking flag. Families whose template has no off
    # switch — gpt-oss, Inkling — can only be asked for minimal reasoning, and that
    # caveat has to survive into the metadata.
    metadata = None
    if tinker_families is not None:
        try:
            family = tinker_families.get_model(args.model.removeprefix("tinker/")).family
        except KeyError as e:
            sys.exit(e.args[0])  # KeyError's str() re-quotes the message
        thinking = ("native" if args.native_cot
                    else "disabled" if family.thinking_off else "minimal")
        thinking_note = f"{thinking} (rendered by families.{family.key}" + (
            "; template default — --native-cot)" if args.native_cot
            else ")" if family.thinking_off
            else "; template has no off switch, lowest effort only)"
        )
        metadata = {"tcw_thinking": thinking, "tcw_model_name": args.model_name}
        if args.native_cot:
            metadata["tcw_variant"] = "native-cot"
    else:
        thinking_note = "disabled" if args.no_thinking else "provider default"

    tasks = [
        agentic_misalignment(
            scenario=s, goal_type=gt, goal_value=gv,
            # prod=True drops the scratchpad paragraphs; that IS the native-CoT condition
            urgency_type=args.urgency_type, prod=args.native_cot,
            model_name=args.model_name, grader_model=GRADER,
        )
        for s in SCENARIOS for (gt, gv) in GOALS
    ]
    log_dir = REPO / "data" / "msm-eval" / args.run_name
    print(f"model={args.model} url={args.base_url or '(tinker api)'} "
          f"name={args.model_name} "
          f"thinking={thinking_note} "
          f"stop_token_ids={args.stop_token_ids or '(provider default eos)'} "
          f"{len(tasks)} conditions x {args.epochs} = {len(tasks)*args.epochs} samples")
    if is_tinker:
        print(f"checkpoint={model_args.get('checkpoint') or '(none — base model)'}")
    print(f"log_dir={log_dir}")

    if args.dry_run:
        for s in SCENARIOS:
            for gt, gv in GOALS:
                print(f"  - {s}_{gt}-{gv}_{args.urgency_type}")
        print("dry run — no API call was made.")
        sys.exit(0)

    check_api_keys(args.model)

    ok, _ = eval_set(
        tasks=tasks, log_dir=str(log_dir),
        model=args.model, model_base_url=args.base_url,
        epochs=args.epochs, temperature=0.7, max_tokens=args.max_tokens,
        extra_body=extra_body,
        **({"model_args": model_args} if model_args else {}),
        **({"metadata": metadata} if metadata else {}),
        max_connections=16, retry_attempts=3, display="plain",
    )
    print(f"{'DONE' if ok else 'INCOMPLETE'}: {log_dir}")
    if ok:  # keep the transcript viewer current (incremental, non-fatal)
        import subprocess
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "build_transcript_viewer.py"),
             "--eval-dir", str(log_dir.parent)], check=False)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
