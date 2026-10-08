"""Execution-accuracy evaluation: does the agent's SQL return the same data as the gold SQL?"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .db import Warehouse, WarehouseError
from .service import AgentService

DATETIME_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00:00(\.0+)?(\+00:00)?$")


@dataclass
class Case:
    id: str
    question: str
    gold_sql: str
    difficulty: str = "medium"
    tags: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    id: str
    question: str
    difficulty: str
    status: str
    correct: bool
    attempts: int
    latency_s: float
    predicted_sql: str | None = None
    error: str | None = None
    detail: str = ""


def load_benchmark(path: Path) -> list[Case]:
    cases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(Case(**json.loads(line)))
    return cases


# ---- result comparison -----------------------------------------------------------------------
def normalize_value(value: Any) -> str:
    """Canonical text for a cell so that 2022, 2022.0 and '2022.00' agree and dates are timezone-free."""
    if value is None:
        return "<null>"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return _number(float(value))
    text = str(value).strip()
    match = DATETIME_MIDNIGHT.match(text)
    if match:
        return match.group(1)
    try:
        return _number(float(text))
    except ValueError:
        return text.lower()


def _number(x: float) -> str:
    """2 decimals for |x| >= 1, 3 decimals for fractions (rates), so rounding choices don't matter."""
    return f"{round(x, 2 if abs(x) >= 1 else 3):.3f}".rstrip("0").rstrip(".") or "0"


def normalize_rows(rows: list[list[Any]]) -> Counter:
    """Multiset of rows; each row is order-insensitive across columns (aliases may differ)."""
    return Counter(tuple(sorted(normalize_value(v) for v in row)) for row in rows)


def results_match(gold_rows: list[list[Any]], predicted_rows: list[list[Any]]) -> bool:
    """Row-order- and column-order-insensitive equality of two result sets."""
    return normalize_rows(gold_rows) == normalize_rows(predicted_rows)


# ---- running the benchmark ---------------------------------------------------------------------
def evaluate_case(service: AgentService, warehouse: Warehouse, case: Case) -> CaseResult:
    started = time.perf_counter()
    try:
        gold = warehouse.execute(case.gold_sql)
    except WarehouseError as exc:
        return CaseResult(
            case.id,
            case.question,
            case.difficulty,
            "gold_error",
            False,
            0,
            0.0,
            error=f"gold SQL failed: {exc}",
        )
    try:
        response = service.ask(case.question)
    except Exception as exc:
        return CaseResult(
            case.id,
            case.question,
            case.difficulty,
            "agent_error",
            False,
            0,
            time.perf_counter() - started,
            error=str(exc),
        )
    latency = time.perf_counter() - started
    correct = response.status == "completed" and results_match(gold.rows, response.rows)
    detail = ""
    if response.status == "completed" and not correct:
        detail = f"gold: {gold.row_count} rows x {len(gold.columns)} cols; got: {response.row_count} rows x {len(response.columns)} cols"
    return CaseResult(
        case.id,
        case.question,
        case.difficulty,
        response.status,
        correct,
        response.attempts,
        latency,
        predicted_sql=response.sql,
        error=response.error,
        detail=detail,
    )


def summarize_results(results: list[CaseResult]) -> dict:
    total = len(results)
    if not total:
        return {"total": 0}
    correct = [r for r in results if r.correct]
    retried = [r for r in results if r.attempts > 0]
    by_difficulty = {}
    for level in sorted({r.difficulty for r in results}):
        group = [r for r in results if r.difficulty == level]
        by_difficulty[level] = {
            "total": len(group),
            "execution_accuracy": round(sum(r.correct for r in group) / len(group), 3),
        }
    return {
        "total": total,
        "execution_accuracy": round(len(correct) / total, 3),
        "by_difficulty": by_difficulty,
        "status_counts": dict(Counter(r.status for r in results)),
        "needed_self_correction": len(retried),
        "recovered_by_self_correction": sum(r.correct for r in retried),
        "mean_attempts": round(statistics.mean(r.attempts for r in results), 2),
        "median_latency_s": round(statistics.median(r.latency_s for r in results), 2),
        "p95_latency_s": round(sorted(r.latency_s for r in results)[int(0.95 * (total - 1))], 2),
    }


def run_benchmark(service: AgentService, warehouse: Warehouse, cases: list[Case], progress=print):
    results = []
    for i, case in enumerate(cases, 1):
        result = evaluate_case(service, warehouse, case)
        results.append(result)
        mark = "PASS" if result.correct else "FAIL"
        progress(
            f"[{i:>2}/{len(cases)}] {mark} {case.id:<18} {result.status:<12} attempts={result.attempts} {result.latency_s:5.1f}s"
        )
    return results, summarize_results(results)


def write_report(path: Path, results: list[CaseResult], summary: dict, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"meta": meta, "summary": summary, "cases": [asdict(r) for r in results]}, indent=2
        ),
        encoding="utf-8",
    )


# ---- LangSmith experiment (optional) -----------------------------------------------------------
def run_langsmith_experiment(
    service: AgentService,
    warehouse: Warehouse,
    cases: list[Case],
    dataset_name: str,
    prefix: str,
):
    """Upload the benchmark as a LangSmith dataset and run the agent as a tracked experiment."""
    from langsmith import Client, evaluate

    client = Client()
    if not client.has_dataset(dataset_name=dataset_name):
        dataset = client.create_dataset(dataset_name, description="Text-to-SQL analyst questions")
        client.create_examples(
            dataset_id=dataset.id,
            inputs=[{"question": c.question, "id": c.id} for c in cases],
            outputs=[{"gold_sql": c.gold_sql, "difficulty": c.difficulty} for c in cases],
        )

    def target(inputs: dict) -> dict:
        response = service.ask(inputs["question"])
        return {
            "status": response.status,
            "sql": response.sql,
            "rows": response.rows,
            "attempts": response.attempts,
            "error": response.error,
        }

    def execution_accuracy(outputs: dict, reference_outputs: dict) -> dict:
        if outputs.get("status") != "completed":
            return {"key": "execution_accuracy", "score": 0}
        gold = warehouse.execute(reference_outputs["gold_sql"])
        return {
            "key": "execution_accuracy",
            "score": int(results_match(gold.rows, outputs["rows"])),
        }

    def self_corrections(outputs: dict) -> dict:
        return {"key": "self_correction_attempts", "score": outputs.get("attempts", 0)}

    return evaluate(
        target,
        data=dataset_name,
        evaluators=[execution_accuracy, self_corrections],
        experiment_prefix=prefix,
        max_concurrency=2,
    )
