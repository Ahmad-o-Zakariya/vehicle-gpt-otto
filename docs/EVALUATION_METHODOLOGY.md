# Evaluation methodology and current evidence

## Isolation and systems

Inference is restricted to the frozen operational database opened read-only. The ground-truth sidecar is not opened by TRACE, the API, direct-SQL baseline, or lexical retrieval. `scripts/run_benchmark.py` runs a development-only five-question smoke set and explicitly checks that held-out thermal trip `TripB14` is absent from TRACE results and FTS retrieval. It does not read held-out labels.

The implemented comparison surfaces are: (A) a read-only SELECT executor with SQLite authorizer/query and row limits, tested with hand-authored SQL; (B) SQLite FTS5/BM25 lexical retrieval over permitted metadata and real event descriptions; and (C) TRACE deterministic execution and verification. The local SLM planner was separately evaluated on the five case-study questions through the application; actual SLM-generated SQL and RAG answer baselines were not evaluated. These checks are not fair end-to-end model comparisons.

## Metrics

The smoke report records case-level expected/actual engine intent, coverage state, evidence grade, grounded status, execution latency, evidence count, provenance, trip IDs, and intent/coverage/grade classification accuracy. Accuracy is exact matches divided by five fixture cases. Latencies are deterministic engine timing only; they exclude SLM and UI time. The SQL smoke records the selected vehicle count; retrieval records returned document IDs and top-k count. No values are represented as held-out detection, numerical correctness, or causal performance.

Current development fixture results: 5/5 expected intents, coverage states, and grades matched; all five answers passed the verifier. `TripB14` was not returned. These are fixture self-consistency checks, not independent accuracy estimates. The report is generated at `artifacts/benchmark/dev_benchmark.json` and excluded from source control.

## Not measured / next evaluation gate

The five-case run verifies plan creation, evidence grade, verifier acceptance and observed end-to-end latency for this question set only; it is not a held-out metric or a repeated trial. Tokens/s, RAM, GPU VRAM, numerical tolerance, event precision/recall, and model comparison metrics were not measured. No ablations or repeated stochastic trials were run. The SLM-generated SQL/RAG baselines remain untested.
