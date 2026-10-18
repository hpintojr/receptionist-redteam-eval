"""Run the scenario suite against one model and one defense setting.

Examples:
  python -m rr_eval.run --provider mock-refuser
  python -m rr_eval.run --provider anthropic --model claude-haiku-5-5 --defense none
  python -m rr_eval.run --provider ollama --model qwen2.5:7b --defense spotlight --epochs 3
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from .models import Provider, make_provider
from .prompts import build_system_prompt, wrap_untrusted
from .scoring import score
from .world import TOOLS, World

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIOS = ROOT / "scenarios" / "scenarios.json"
DEFENSES = {"none": (False, False), "spotlight": (True, False),
            "gate": (False, True), "spotlight+gate": (True, True)}
MAX_TOOL_STEPS = 6


def load_scenarios(path: Path = DEFAULT_SCENARIOS) -> list[dict]:
    return json.loads(Path(path).read_text())["scenarios"]


def run_scenario(provider: Provider, scenario: dict, defense: str = "none") -> dict:
    spotlight, gate = DEFENSES[defense]
    world = World(scenario["caller_phone"], scenario.get("injections"), gate=gate)
    provider.start(build_system_prompt(scenario["caller_phone"], spotlight), TOOLS)
    transcript, replies = [], []
    for turn in scenario["turns"]:
        provider.add_user(turn)
        transcript.append({"role": "caller", "text": turn})
        reply = ""
        for _ in range(MAX_TOOL_STEPS):
            text, calls = provider.step()
            reply = text
            if not calls:
                break
            results = []
            for call_id, name, args in calls:
                out = world.call(name, args)
                results.append((call_id, name, wrap_untrusted(out) if spotlight else out))
            provider.add_tool_results(results)
        replies.append(reply)
        transcript.append({"role": "agent", "text": reply})
    return {"transcript": transcript, "calls": world.calls,
            "score": score(scenario, world.calls, replies)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", required=True,
                    choices=["anthropic", "openai", "ollama", "mock-refuser", "mock-naive"])
    ap.add_argument("--model")
    ap.add_argument("--base-url", help="Override the API base URL (OpenAI-compatible providers)")
    ap.add_argument("--defense", default="none", choices=list(DEFENSES))
    ap.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    ap.add_argument("--category", help="Only run one category")
    ap.add_argument("--limit", type=int, help="Only run the first N scenarios")
    ap.add_argument("--epochs", type=int, default=1, help="Repeat each scenario N times")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--out", type=Path, default=ROOT / "results")
    args = ap.parse_args(argv)

    scenarios = load_scenarios(args.scenarios)
    if args.category:
        scenarios = [s for s in scenarios if s["category"] == args.category]
    if args.limit:
        scenarios = scenarios[: args.limit]

    label = args.model or args.provider
    args.out.mkdir(parents=True, exist_ok=True)
    suffix = f"__{args.category}" if args.category else ""
    out_file = args.out / f"{args.provider}_{re.sub(r'[^A-Za-z0-9._-]', '-', label)}__{args.defense}{suffix}.jsonl"

    with out_file.open("w") as fh:
        for epoch in range(args.epochs):
            for s in scenarios:
                provider = make_provider(args.provider, args.model, args.base_url, args.temperature)
                started = time.time()
                try:
                    result = run_scenario(provider, s, args.defense)
                    err = None
                except Exception as exc:  # keep the sweep going; record the failure
                    result, err = {"transcript": [], "calls": [], "score": None}, str(exc)
                row = {"provider": args.provider, "model": label, "defense": args.defense,
                       "scenario": s["id"], "category": s["category"], "epoch": epoch,
                       "seconds": round(time.time() - started, 2), "error": err, **result}
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                sc = row["score"]
                if err:
                    status = f"ERROR {err[:80]}"
                elif sc["benign"]:
                    status = "task done" if sc["task_success"] else "task FAILED"
                else:
                    status = ("EXECUTED" if sc["executed"] else "attempted, blocked") if sc["attempted"] else "resisted"
                print(f"[{epoch}] {s['id']:<6} {s['category']:<20} {status}", file=sys.stderr)
    print(f"Wrote {out_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
