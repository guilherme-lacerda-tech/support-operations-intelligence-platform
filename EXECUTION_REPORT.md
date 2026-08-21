# Execution Report

Date: 2026-08-21  
Branch: `cleanroom-dotnet-poc`  
Push: not performed

## Inventory

- GitHub account available through `gh`: `guilherme-lacerda-tech`.
- Main repository: `support-operations-intelligence-platform`.
- Profile repository updated separately: `guilherme-lacerda-tech`.
- Secondary extractor repository prepared separately: `resumable-api-batch-extractor`.
- .NET SDK installed locally through `winget`: .NET SDK `10.0.400`.
- Docker was not available on PATH, so Docker validation was not executed.

## Implementation

- Preserved the existing Python/FastAPI implementation.
- Added shared clean-room behavior contract.
- Added deterministic JSONL workloads for 100, 1,000, 10,000, 50,000 and 100,000 events.
- Added .NET 10/ASP.NET Core implementation under `dotnet/`.
- Added SQLite persistence, parameterized SQL, metrics, audit, cooldown, retry handling and optional background action processing.
- Added Python contract runner and .NET benchmark runner.
- Added HTTP load benchmark and 30-minute soak benchmark.

## Evidence

PYTHON TESTS: `python -m pytest -q` -> 19 passed, 1 Starlette/httpx deprecation warning.

.NET TESTS: `dotnet test dotnet/OpsIntelligenceCleanRoom.sln --no-build` -> 14 passed.

PYTHON BUILD/RUN: `python -m support_operations_intelligence_platform.cli` -> `{'assets': 3, 'incidents': 1, 'actions': 1, 'action_state': 'succeeded'}`.

.NET BUILD: `dotnet build dotnet/OpsIntelligenceCleanRoom.sln` -> build succeeded, 0 warnings, 0 errors.

ENGINE BENCHMARK:

- 1 warmup + 5 measured runs per stack for default SQLite workloads 100 and 1,000.
- Raw/summary files:
  - `benchmarks/results/engine_raw_20260820-230729.jsonl`
  - `benchmarks/results/engine_summary_20260820-230729.json`

HTTP BENCHMARK:

- Local FastAPI and ASP.NET Core servers.
- Single external `httpx` load generator.
- Concurrency: 1, 10, 25, 50, 100.
- Requests per level: 50.
- Raw file: `benchmarks/results/http_summary_20260821-071805.json`.

CORRETUDE CROSS-STACK:

- Canonical equivalence = true for `workload_100.jsonl`.
- Canonical equivalence = true for `workload_1000.jsonl`.
- Canonical equivalence = true for `workload_100.jsonl` with SQLite WAL + synchronous NORMAL.

SQLITE COMPARISON:

- Default SQLite tested for 100 and 1,000 event workloads.
- WAL + synchronous NORMAL tested for 100 event workload.
- WAL result documented separately because it changes durability/performance tradeoffs.

CONCURRENCY:

- HTTP concurrency levels 1, 10, 25, 50, 100 executed.
- Python started returning errors at concurrency 50 in the measured run.
- .NET completed the same request count without HTTP errors but with high tail latency.
- Main bottleneck identified: SQLite write contention and high tail latency under concurrent writes.

LONG-RUNNING:

- 30-minute HTTP soak executed with local Python and .NET APIs.
- Configured duration: 1,800 seconds.
- Samples written: 29.
- Final sampled state at 1,740.438 seconds:
  - Python: 1,667 events, 400 incidents, 266 actions, 266 succeeded actions, 0 failed actions, 24 retries, 1,267 suppressions, 0 errors.
  - .NET: 1,667 events, 400 incidents, 266 actions, 266 succeeded actions, 0 failed actions, 24 retries, 1,267 suppressions, 0 errors.
- Raw file: `benchmarks/results/http_soak_20260821-074956.json`.

CURRICULO:

- Four new DOCX versions created in `C:\Users\guilh\OneDrive\Área de Trabalho\curriculos`:
  - `Guilherme_Lacerda_Curriculo_Mestre_ATS_2026_v3_Portfolio_MultiStack.docx`
  - `Guilherme_Lacerda_Curriculo_Python_Automacao_Integracao_2026_v3_Portfolio_MultiStack.docx`
  - `Guilherme_Lacerda_Curriculo_Integracao_Sistemas_2026_v3_Portfolio_MultiStack.docx`
  - `Guilherme_Lacerda_Curriculo_PeD_Automacao_Desenvolvimento_Solucoes_2026_v3_Portfolio_MultiStack.docx`
- Academic formation, job titles and professional dates were preserved.
- Added consolidated complementary formation, public portfolio project and approved quantified results.
- DOCX render QA could not be completed because LibreOffice/Word renderer was not available on PATH; structural DOCX QA passed with `python-docx`.

PORTFOLIO:

- Profile README refreshed in `guilherme-lacerda-tech`.
- `PORTFOLIO.md` refreshed with recommended pins and metric boundaries.
- `LINKEDIN_PROFILE_PROPOSAL.md` created with headline, About, experience bullets, project metrics and post draft.
- `INTERVIEW_CASES.md` created in this repository.
- Secondary extractor benchmark backlog prepared in `resumable-api-batch-extractor`.

PUSH REALIZADO: NAO.
