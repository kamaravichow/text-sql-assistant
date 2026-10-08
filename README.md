# Agentic Text-to-SQL Analytics Assistant

A LangGraph agent that turns plain-English business questions into **validated SQL**, runs it against a
PostgreSQL warehouse, and returns **a chart and a written summary** — served over a REST API with a
Streamlit front-end.

```
"Which 5 categories have the highest revenue?"
        │
        ▼
 retrieve schema (RAG) ─▶ generate SQL ─▶ validate (safety + EXPLAIN) ─▶ cost gate ─▶ execute
                               ▲                    │ error                 │ expensive      │ error
                               └──── fix SQL ◀──────┴────────────────────────┼──── human ────┘
                                     (bounded loop)                         ▼    approval
                                                                       chart ─▶ summary ─▶ response
```

## What it does

| Capability | How |
|---|---|
| **Schema retrieval (RAG)** | Hand-written Markdown docs per table (`docs/tables/`) are ranked against the question (TF-IDF offline, or any LangChain embeddings). Retrieved tables pull in their foreign-key neighbours so joins are possible. A business glossary (`docs/glossary.md`: revenue, AOV, active customer, …) is always in the prompt. |
| **SQL generation** | LLM call with the retrieved docs + glossary. The model may decline with `CANNOT_ANSWER:` when the schema cannot answer the question. |
| **Validation** | `sqlglot` parse (one `SELECT`/`WITH` statement only, no DDL/DML, no `SELECT INTO`, no `FOR UPDATE`, no dangerous functions, `public` schema only), then `EXPLAIN` against the real database to catch unknown columns/types before anything runs. |
| **Self-correction loop** | Safety, planner or runtime errors are fed back to the LLM with the failing SQL (up to `MAX_SQL_RETRIES`), then the agent gives up with the last error instead of looping forever. |
| **Human-approval checkpoint** | If the planner's total cost exceeds `APPROVAL_COST_THRESHOLD`, the graph pauses with LangGraph `interrupt()`. The API returns `awaiting_approval` with the SQL and cost; a second call approves or rejects. Nothing runs until approved. |
| **Charts + summary** | The LLM proposes a chart (validated against the real columns, with a heuristic fallback); Plotly JSON is returned. A second LLM call writes a 2–4 sentence summary from the result rows. Failures here never lose the query result. |
| **Evaluation** | 32 analyst questions (easy/medium/hard) with gold SQL; **execution accuracy** compares result sets, not SQL text. |
| **Tracing** | LangChain/LangGraph runs, retrieval and warehouse calls are traced to LangSmith when enabled. |

### Defence in depth for LLM-written SQL

1. Static validator (`sql_safety.py`) — rejects anything that is not one read-only `SELECT`.
2. Dedicated **read-only database role** (`analyst_ro`, `default_transaction_read_only = on`).
3. Every query runs in a **read-only transaction** with a **statement timeout** and a **row cap**.
4. Cost-based **human approval** for expensive plans.

## Quick start (Docker)

```bash
cp .env.example .env        # set LLM_MODEL and ANTHROPIC_API_KEY (or switch to OpenAI)
docker compose up --build
```

- Streamlit UI: <http://localhost:8501>
- API docs: <http://localhost:8000/docs>
- PostgreSQL: `localhost:5432`, database `warehouse` (seeded on first start from `db/init/`)

The demo warehouse is a synthetic e-commerce dataset (2,000 customers, 120 products, 20,000 orders,
50,000 order lines, ~2,200 returns, 300,000 web events), generated with a fixed seed.
Re-seed with `docker compose down -v`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,dev,openai]"
cp .env.example .env

# a PostgreSQL 16 database named "warehouse", loaded with the demo data:
createdb warehouse && for f in db/init/*.sql; do psql -d warehouse -f "$f"; done

uvicorn sqlagent.api.main:app_factory --factory --reload      # API on :8000
API_URL=http://localhost:8000 streamlit run src/sqlagent/ui/streamlit_app.py
pytest                                                          # 99 tests
```

## REST API

```bash
curl -s localhost:8000/v1/query -H 'content-type: application/json' \
  -d '{"question": "What was revenue by month in 2024?"}'
```

| Endpoint | Purpose |
|---|---|
| `POST /v1/query` | Ask a question. Returns `status`, `sql`, `columns`/`rows`, Plotly `chart`, `summary`, `estimated_cost`, `attempts`, and a `steps` trace. |
| `POST /v1/query/{thread_id}/approval` | Body `{"approved": true\|false}`. Resumes a query that returned `awaiting_approval`. |
| `GET /v1/tables` | Documented tables. |
| `GET /health` | Liveness + warehouse connectivity. |

`status` is one of `completed`, `awaiting_approval`, `rejected`, `failed`, `unanswerable`.
If `API_KEY` is set, send it as `X-API-Key`.

```jsonc
// POST /v1/query  ->  expensive query pauses
{ "status": "awaiting_approval", "thread_id": "cae3d8f0…",
  "approval": { "sql": "SELECT …", "estimated_cost": 9005982.01, "threshold": 20000.0 } }

// POST /v1/query/cae3d8f0…/approval  {"approved": true}  ->  runs and returns the full answer
```

## Configuration

All settings are environment variables (or `.env`); see `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` / `LLM_MODEL` | `anthropic` / *(required)* | Chat model used for every LLM step. No model id is hard-coded; set one your key can use. |
| `WAREHOUSE_DSN` | read-only role on localhost | Connection string used by the agent. |
| `MAX_SQL_RETRIES` | `3` | Self-correction attempts after the first draft. |
| `REQUIRE_APPROVAL`, `APPROVAL_COST_THRESHOLD` | `true`, `20000` | Planner cost above which a human must approve. |
| `STATEMENT_TIMEOUT_MS`, `MAX_ROWS` | `15000`, `1000` | Per-query limits. |
| `RETRIEVAL_BACKEND`, `RETRIEVAL_TOP_K` | `tfidf`, `3` | `embeddings` uses OpenAI embeddings (needs `OPENAI_API_KEY`). |
| `AS_OF_DATE` | unset | Tells the model to treat this date as "today" (the demo data ends 2024-12-31). |
| `API_KEY` | unset | Require `X-API-Key` on the API. |

## Evaluation

```bash
python eval/run_eval.py                 # real LLM: execution accuracy over eval/benchmark.jsonl
python eval/run_eval.py --difficulty hard --limit 5
python eval/run_eval.py --check-gold    # every gold query passes the validator and runs
python eval/run_eval.py --oracle        # pipeline smoke test: stub LLM answers with the gold SQL
python eval/run_eval.py --langsmith     # also log a LangSmith dataset + experiment
```

**Metric.** A question is correct when the agent finishes with status `completed` *and* its result set
equals the gold result set. Comparison ignores row order, column order and column aliases, rounds
numbers (2 decimals, 3 for fractions) and treats midnight timestamps as dates. The report also gives
accuracy by difficulty, how many questions needed self-correction and how many of those recovered,
and median/p95 latency; a JSON report lands in `eval/results/`.

`--oracle` should score 100% and a deliberately wrong stub should score ~0% — both are asserted in
`tests/test_integration.py` — which shows the harness and pipeline are sound. It says nothing about
LLM quality: run the real benchmark with your model to get that number.

## LangSmith tracing

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=text-to-sql-assistant
```

Each request is one trace (`text_to_sql_agent`, tagged `text-to-sql`, with `thread_id` metadata) with a
span per graph node, the LLM calls, the retrieval step (`retrieve_tables`) and the warehouse calls
(`warehouse.explain`, `warehouse.execute`). `eval/run_eval.py --langsmith` records benchmark runs as
experiments with `execution_accuracy` and `self_correction_attempts` feedback.

## Project layout

```
db/init/            schema, deterministic seed data, read-only role (run by the Postgres container)
docs/tables/        one Markdown doc per table — the corpus for schema RAG
docs/glossary.md    business definitions injected into prompts
src/sqlagent/
  graph.py nodes.py state.py prompts.py   the LangGraph agent
  retrieval.py sql_safety.py db.py        RAG, validator, warehouse access
  charts.py service.py evaluation.py      chart selection, thread handling, metrics
  api/main.py                             FastAPI app
  ui/streamlit_app.py                     Streamlit front-end
eval/               benchmark.jsonl + run_eval.py
tests/              unit tests (fake LLM + warehouse) and integration tests (real PostgreSQL)
```

## Using your own warehouse

1. Point `WAREHOUSE_DSN` at a **read-only** role.
2. Replace `docs/tables/*.md` with one document per table (grain, columns, joins in a
   `**Related tables:**` line, business rules) and rewrite `docs/glossary.md`.
3. Replace `eval/benchmark.jsonl` with your analysts' real questions and reference SQL, and tune
   `APPROVAL_COST_THRESHOLD` to your planner's cost scale.

## Known limitations

- Pending approvals live in an in-process checkpointer (`InMemorySaver`): run a single API worker, and
  pending approvals are lost on restart. For multi-worker deployments pass a Postgres-backed
  checkpointer to `build_graph`.
- Planner cost is an estimate; it gates *expected* expense, while the statement timeout and row cap
  bound the actual cost.
- Retrieval is document-level (one doc per table). Warehouses with hundreds of tables will want
  column-level chunks and the embeddings backend.
- Multi-turn conversation (follow-up questions) is not implemented; each question is independent.
