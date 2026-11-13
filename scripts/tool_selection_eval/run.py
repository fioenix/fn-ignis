"""Run the tool-selection eval: a headless host agent against the simulated Ignis catalog.

Maintainer-run only (Spec 028 FR-011). Each intent runs in a fresh temporary directory with the
host agent isolated from the maintainer's own MCP servers, plugins, hooks, memory and built-in
tools. Raw transcripts and the report land under `reports/` (gitignored).

    python -m scripts.tool_selection_eval.run --repeats 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.tool_selection_eval.catalog import load_catalog
from scripts.tool_selection_eval.intents import IntentSet, load_intents, validate
from scripts.tool_selection_eval.scoring import aggregate, score_intent, stability

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INTENTS = REPO_ROOT / "tests" / "fixtures" / "tool_selection_intents.json"
SERVER_NAME = "ignis"
HOST_TIMEOUT_SECONDS = 300
NEUTRAL_HOST_PROMPT = (
    "You are a helpful assistant. Tools from a connected MCP server are available; use them "
    "when they help with the user's request. You cannot browse the web, read files or run "
    "commands. Answer in the user's language."
)


def host_command(claude: str, model: str, text: str, mcp_config: Path) -> list[str]:
    return [
        claude,
        "-p",
        text,
        "--model",
        model,
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp_config),
        "--allowedTools",
        f"mcp__{SERVER_NAME}",
        "--disable-slash-commands",
        "--setting-sources",
        "project",
        "--no-session-persistence",
        "--system-prompt",
        NEUTRAL_HOST_PROMPT,
        "--output-format",
        "json",
    ]


def sim_config(intents_path: Path, intent_id: str, log_path: Path, cap: int) -> dict[str, Any]:
    return {
        "mcpServers": {
            SERVER_NAME: {
                "command": sys.executable,
                "args": [
                    "-m",
                    "scripts.tool_selection_eval.sim_server",
                    "--intents",
                    str(intents_path),
                    "--intent-id",
                    intent_id,
                    "--log",
                    str(log_path),
                    "--cap",
                    str(cap),
                ],
                "env": {"PYTHONPATH": f"{REPO_ROOT / 'src'}{os.pathsep}{REPO_ROOT}"},
            }
        }
    }


def read_calls(log_path: Path) -> tuple[list[str], bool, bool]:
    """Return the tool calls, whether the cap was hit, and whether the simulator started."""
    if not log_path.exists():
        return [], False, False
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    started = any(entry["outcome"] == "started" for entry in entries)
    calls = [entry for entry in entries if entry["outcome"] != "started"]
    return [entry["tool"] for entry in calls], any(entry["outcome"] == "cap" for entry in calls), started


def _host_attempt(
    args: argparse.Namespace, intents_path: Path, intent: dict[str, Any], log_path: Path
) -> tuple[dict[str, Any], int]:
    log_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="ignis-eval-") as workdir:
        config_path = Path(workdir) / "mcp.json"
        config_path.write_text(json.dumps(sim_config(intents_path, intent["id"], log_path, args.cap)))
        completed = subprocess.run(
            host_command(args.claude, args.model, intent["text"], config_path),
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=HOST_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result = {"is_error": True, "result": completed.stderr[-2000:] or completed.stdout[-2000:]}
    result["stderr_tail"] = completed.stderr[-2000:]
    return result, completed.returncode


def run_intent(
    args: argparse.Namespace,
    intents_path: Path,
    intent: dict[str, Any],
    run_dir: Path,
    neutral: frozenset[str],
) -> dict[str, Any]:
    log_path = run_dir / f"{intent['id']}.calls.jsonl"
    # A simulator that never connected is an infrastructure fault, not agent behaviour: retry once.
    for attempt in (1, 2):
        result, returncode = _host_attempt(args, intents_path, intent, log_path)
        calls, capped, started = read_calls(log_path)
        if started:
            break
    result["attempts"] = attempt
    (run_dir / f"{intent['id']}.host.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    row = score_intent(intent, calls, capped, neutral)
    row["host_error"] = bool(result.get("is_error")) or returncode != 0 or not started
    if not started:
        result["result"] = f"simulated server never started: {result.get('result', '')}"
    row["reply"] = str(result.get("result", ""))[:600]
    row["cost_usd"] = result.get("total_cost_usd")
    row["attempts"] = attempt
    return row


def run_once(
    args: argparse.Namespace,
    intents_path: Path,
    intents: list[dict[str, Any]],
    run_dir: Path,
    neutral: frozenset[str],
) -> list[dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    first = run_intent(args, intents_path, intents[0], run_dir, neutral)
    if first["host_error"]:
        raise SystemExit(f"Host agent failed on the first intent; no baseline recorded: {first['reply']}")
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rest = list(pool.map(lambda intent: run_intent(args, intents_path, intent, run_dir, neutral), intents[1:]))
    rows = [first, *rest]
    failed = [row["id"] for row in rows if row["host_error"]]
    if failed:
        raise SystemExit(f"Host agent failed on {failed}; this run is incomplete and not a baseline.")
    return rows


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Tool-selection eval report",
        "",
        f"- Started: {report['started_at']}",
        f"- Host model: `{report['model']}`",
        f"- Catalog fingerprint: `{report['catalog_fingerprint']}` ({report['tool_count']} tools)",
        f"- Intent set: `{report['intent_set_version']}` ({report['intent_count']} intents)",
        f"- Repeats: {len(report['runs'])}",
        "",
        "## Headline metrics per run",
        "",
        "| Run | First call % | Trap first call % | Trap wrong first | Trap call % | Tactical % | Watchlist % | Mission % | Mean wrong calls | Mean neutral calls | Terminal reach % | Median calls to terminal |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, run in enumerate(report["runs"], start=1):
        metrics = run["metrics"]
        journeys = metrics["first_call_accuracy_by_journey"]
        lines.append(
            f"| {index} | {metrics['first_call_accuracy']} | {metrics['trap_first_call_accuracy']} | "
            f"{metrics['trap_first_call_wrong']} | {metrics['trap_call_rate']} | {journeys['tactical']} | "
            f"{journeys['watchlist']} | {journeys['mission']} | {metrics['mean_wrong_calls']} | "
            f"{metrics['mean_neutral_calls']} | {metrics['terminal_reach_rate']} | "
            f"{metrics['median_calls_to_terminal']} |"
        )
    stable = report["stability"]
    lines += ["", "## Stability", ""]
    for name, item in stable["spreads"].items():
        lines.append(f"- `{name}`: {item['min']}–{item['max']} (spread {item['spread']} points)")
    if stable["runs"] < 2:
        lines.append("- One run only: stability not measured.")
    else:
        verdict = "stable" if stable["stable"] else f"UNSTABLE on {stable['unstable_metrics']}"
        lines.append(f"- Verdict against the 10-point bar: **{verdict}**")
    lines += ["", "## Per intent (last run)", "", "| Intent | Trap | Decisive first call | OK | Trap calls | Wrong tools | Terminal | Calls |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["runs"][-1]["rows"]:
        lines.append(
            f"| {row['id']} | {'yes' if row['trap'] else ''} | {row['first_call'] or 'reply'} | "
            f"{'yes' if row['first_call_ok'] else 'NO'} | {', '.join(row['trap_calls'])} | {', '.join(row['wrong_tools'])} | "
            f"{'yes' if row['reached_terminal'] else 'no'}{' (cap)' if row['capped'] else ''} | {' → '.join(row['calls'])} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--intents", default=str(DEFAULT_INTENTS))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--cap", type=int, default=8)
    parser.add_argument("--only", nargs="*", help="intent ids or journeys to run")
    parser.add_argument("--claude", default=shutil.which("claude") or "claude")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if not shutil.which(args.claude):
        raise SystemExit(f"Host agent CLI not found: {args.claude}")
    intents_path = Path(args.intents).resolve()
    intent_set: IntentSet = load_intents(intents_path)
    catalog = asyncio.run(load_catalog())
    problems = validate(intent_set, catalog.tool_names)
    if problems:
        raise SystemExit("Intent set does not fit the live catalog:\n" + "\n".join(problems))
    intents = intent_set.intents
    if args.only:
        intents = [i for i in intents if i["id"] in args.only or i["journey"] in args.only]
        if not intents:
            raise SystemExit(f"No intent matches {args.only}")

    started = datetime.now(timezone.utc)
    out_dir = Path(args.out).resolve() if args.out else REPO_ROOT / "reports" / "tool_selection_eval" / started.strftime("%Y%m%dT%H%M%SZ")
    runs = []
    for repeat in range(1, args.repeats + 1):
        rows = run_once(args, intents_path, intents, out_dir / f"run-{repeat}", intent_set.neutral_tools)
        runs.append({"metrics": aggregate(rows), "rows": rows})
        print(f"run {repeat}: {json.dumps(runs[-1]['metrics'], ensure_ascii=False)}", flush=True)
    report = {
        "started_at": started.isoformat(),
        "model": args.model,
        "catalog_fingerprint": catalog.fingerprint(),
        "tool_count": len(catalog.tools),
        "intent_set_version": intent_set.version,
        "intent_count": len(intents),
        "subset": args.only or None,
        "runs": runs,
        "stability": stability([run["metrics"] for run in runs]),
        "cost_usd": round(sum(row.get("cost_usd") or 0 for run in runs for row in run["rows"]), 4),
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"report: {out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
