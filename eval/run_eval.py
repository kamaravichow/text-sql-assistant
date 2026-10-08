"""Run the analyst-question benchmark and report execution accuracy.

python eval/run_eval.py                    # real LLM (needs LLM_MODEL + API key)
python eval/run_eval.py --check-gold       # verify every gold query is safe and runs
python eval/run_eval.py --oracle           # pipeline smoke test: stub LLM answers with gold SQL
python eval/run_eval.py --langsmith        # also log an experiment to LangSmith
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from sqlagent.config import get_settings
from sqlagent.db import PostgresWarehouse, WarehouseError
from sqlagent.evaluation import (
    load_benchmark,
    run_benchmark,
    run_langsmith_experiment,
    write_report,
)
from sqlagent.fakes import FunctionChatModel
from sqlagent.graph import build_default_graph, build_graph
from sqlagent.nodes import Deps
from sqlagent.retrieval import build_retriever
from sqlagent.service import AgentService
from sqlagent.sql_safety import UnsafeSQLError, check_sql

ROOT = Path(__file__).resolve().parents[1]


def oracle_llm(cases) -> FunctionChatModel:
    gold = {c.question: c.gold_sql for c in cases}

    def reply(prompt: str) -> str:
        if "[task: generate_sql]" in prompt:
            question = re.search(r"Question: (.+)", prompt).group(1).strip()
            return f"```sql\n{gold[question]}\n```"
        if "[task: choose_chart]" in prompt:
            return '{"chart_type": "none"}'
        return "oracle summary"

    return FunctionChatModel(fn=reply)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--benchmark", type=Path, default=ROOT / "eval" / "benchmark.jsonl")
    ap.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--check-gold", action="store_true", help="only validate the gold queries")
    ap.add_argument(
        "--oracle", action="store_true", help="use a stub LLM that returns the gold SQL"
    )
    ap.add_argument(
        "--langsmith", action="store_true", help="log the run as a LangSmith experiment"
    )
    ap.add_argument("--dataset", default="text-to-sql-analyst-questions")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    settings = get_settings().model_copy(update={"require_approval": False})
    warehouse = PostgresWarehouse(
        settings.warehouse_dsn, settings.statement_timeout_ms, settings.max_rows
    )
    cases = load_benchmark(args.benchmark)
    if args.difficulty:
        cases = [c for c in cases if c.difficulty == args.difficulty]
    if args.limit:
        cases = cases[: args.limit]

    if args.check_gold:
        bad = 0
        for c in cases:
            try:
                check_sql(c.gold_sql)
                n = warehouse.execute(c.gold_sql).row_count
                print(f"ok    {c.id:<32} {n} rows")
            except (UnsafeSQLError, WarehouseError) as exc:
                bad += 1
                print(f"FAIL  {c.id:<32} {exc}")
        return 1 if bad else 0

    if args.oracle:
        glossary = settings.glossary_path.read_text(encoding="utf-8")
        deps = Deps(oracle_llm(cases), build_retriever(settings), warehouse, settings, glossary)
        graph = build_graph(deps)
    else:
        graph = build_default_graph(settings)
    service = AgentService(graph, settings)

    if args.langsmith:
        run_langsmith_experiment(
            service, warehouse, cases, args.dataset, "oracle" if args.oracle else settings.llm_model
        )
        return 0

    results, summary = run_benchmark(service, warehouse, cases)
    print("\n" + "=" * 60)
    print(
        f"Execution accuracy: {summary['execution_accuracy']:.1%}  ({summary['total']} questions)"
    )
    for level, stats in summary["by_difficulty"].items():
        print(f"  {level:<7} {stats['execution_accuracy']:.1%} of {stats['total']}")
    print(
        f"Needed self-correction: {summary['needed_self_correction']} "
        f"(recovered {summary['recovered_by_self_correction']})"
    )
    print(f"Median latency: {summary['median_latency_s']}s   p95: {summary['p95_latency_s']}s")
    failures = [r for r in results if not r.correct]
    for r in failures:
        print(
            f"\nFAILED {r.id} [{r.status}] {r.question}\n  sql: {r.predicted_sql}\n  {r.error or r.detail}"
        )

    out = args.out or ROOT / "eval" / "results" / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    write_report(
        out,
        results,
        summary,
        {
            "model": "oracle" if args.oracle else settings.llm_model,
            "provider": settings.llm_provider,
            "benchmark": str(args.benchmark),
        },
    )
    print(f"\nReport written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
