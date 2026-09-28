# Industrial Data Intelligence Platform

An end-to-end **natural-language data analysis platform** for manufacturing enterprises.

Business users ask questions in plain Chinese (e.g. *"请分析各工序的良率"*, *"检测最近一个月设备数据中的异常"*), and an AI agent plans and executes the whole analysis: it retrieves business knowledge and table metadata, generates and safely executes SQL, runs sandboxed Python analysis, trains machine-learning models, and streams back charts, tables, conclusions and a written report — with every number traceable to real query results.

> **Status**: fully working local demo (all services runnable on a single machine).
> **License**: all rights reserved.

## Key capabilities

| Capability | How it works |
|---|---|
| Natural-language analysis | Intent planning → metadata retrieval → SQL generation → read-only execution → chart/insight generation, streamed live over SSE with a visible step timeline |
| SQL safety | Generated SQL passes an AST whitelist (SELECT-only, forced `LIMIT`, DML/DDL refused) and runs under a read-only DB account with statement timeouts |
| Python analysis sandbox | LLM-generated pandas/sklearn code runs in an isolated subprocess (memory limits via Windows Job Object, import whitelist, timeout, no network) |
| Machine learning | Unified contract over six scikit-learn models (Linear/Logistic Regression, Decision Tree, Random Forest, KMeans, Isolation Forest) with metrics, feature importance and explanations; models persisted for reuse |
| Anti-hallucination reporting | The report builder only narrates real execution results; every number is re-validated against query output before the report is accepted |
| Metadata-driven | Register any new table → auto-collect schema/comments/sample values → the table becomes queryable in natural language, no code changes |
| Business knowledge | Objects / metrics / rules / analysis topics with executable metric formulas (a semantic layer the agent reuses), visualized as an interactive knowledge graph |
| Auditability | Every analysis task, step, SQL statement and result is archived and re-openable from the workbench history |

## Architecture

```
Browser (Vue 3 + TS + Element Plus + ECharts + AntV G6)
    │  REST + JWT  ·  SSE for live analysis streams
    ▼
Business service (Spring Boot 3, port 8080)
    auth/RBAC · business knowledge CRUD · metadata catalog ·
    session & task archiving · SSE proxy
    │  internal REST + SSE event protocol
    ▼
Agent engine (FastAPI, port 8100, stateless)
    planner · retriever · NL2SQL + SQL guard · read-only executor ·
    Python sandbox · ML modeler · report builder · LLM client (multi-provider failover)
    │  read-only credentials only
    ▼
MySQL 8 ── mes_demo (manufacturing sample data) + a07_platform (platform data)
```

The agent engine talks to the business database **only through a read-only account**, and to the platform database only via the business service. LLM access goes through one OpenAI-compatible client (primary + fallback provider, per-task model routing).

## Tech stack

- **Frontend**: Vue 3, TypeScript (strict), Vite, Element Plus, Apache ECharts, AntV G6, Pinia
- **Business service**: Java 17, Spring Boot 3.3, Spring Security (JWT), MyBatis-Plus, Flyway, Maven Wrapper
- **Agent engine**: Python 3.10+, FastAPI, pydantic v2, OpenAI-compatible SDK, sqlglot, pandas, scikit-learn
- **Data**: MySQL 8 (two schemas), synthetic manufacturing dataset (~110k rows with seeded business anomalies)
- **Infra**: docker-compose (MySQL), one-click start/stop scripts, unified quality gate (backend tests + type-check + build + E2E smoke)

## Quick start

Requirements: JDK 17+, Python 3.10+, Node 20+, Docker.

```bash
# 0) configure — fill in your LLM API key (any OpenAI-compatible endpoint)
cp .env.example .env

# 1) start MySQL (auto-creates both schemas and loads the sample dataset)
docker compose -f deploy/docker-compose.yml up -d mysql

# 2) verify the synthetic dataset (optional, already seeded on first init)
python a07-data/generate.py

# 3) start everything (agent engine 8100 + backend 8080 + frontend 5173)
bash deploy/start-all.sh

# 4) open the app
#    http://localhost:5173   demo accounts: admin/admin123 · dm/dm123456 · user/user123456
```

Stop everything with `bash deploy/stop-all.sh`. Logs land in `deploy/logs/`.

## Example questions the demo answers

- 请分析各工序的良率。— yield per process (grouped stats + bar chart)
- 统计每条产线最近 7 天的产量趋势。— output trend per production line (multi-series line chart)
- 分析设备停机时间和不良率是否相关。— correlation via the Python sandbox (scatter + Pearson/Spearman)
- 检测最近一个月设备数据中的异常。— Isolation-Forest anomaly detection on equipment data
- 用随机森林分析哪些因素对质量结果影响较大。— random forest with feature importance
- 生成本周质量分析报告。— a full weekly quality report (multi-query + anti-hallucination checks)
- 删除所有质量检验数据。— refused: the platform is strictly read-only

A batch evaluation harness (`a07-agent/scripts/eval.py`) runs a curated question set through the full live chain and scores pass rate. The dataset of evaluation questions is kept out of this public repository.

## Security model

- The LLM never holds admin credentials; agent SQL runs under a read-only account and is AST-validated before execution
- LLM-generated Python never runs inside the web process; it executes in a constrained sandbox subprocess (memory limits, import whitelist, timeout)
- API keys live only in `.env` (never committed); JWT-based auth with role separation (admin / data steward / analyst)
- Demo data is fully synthetic — no real personal or production data

## Project structure

```
a07-server/   Spring Boot business service (auth, knowledge, metadata, sessions, audit)
a07-agent/    FastAPI agent engine (retrieval, NL2SQL, sandbox, ML, reporting)
a07-web/      Vue 3 frontend (workbench, knowledge center, data catalog, ML workbench)
a07-data/     DDL, synthetic data generator, metric seeds, retrieval corpus
deploy/       docker-compose, start/stop scripts, quality gate
```

## Testing

```bash
bash deploy/gate.sh        # runs: engine pytest suite, Java tests, frontend type-check + build, E2E smoke
```

The engine suite covers the SQL guard (injection/DML samples), sandbox escape/limit cases, planner contracts, multi-series charts, streaming and refusal paths; the Java suite covers auth, SSE proxy passthrough and archiving; the frontend is strict-TypeScript with a production build check.
