# TRACE Evidence System

Evidence grades are deterministic project rules: E0 no evidence; E1 partial,
insufficient or synthetic support; E2 adequate direct operational support; E3
at least three trips, two signals and two independent source datasets under
adequate coverage; E− conflicting evidence. E3 is not causal or scientific proof.

Claims are Pydantic records containing type, value/units, evidence IDs,
calculation reference, grade, limits and verifier status. Canonical and overlay
references resolve through read-only SQLite queries. Aggregate calculation
references resolve against the returned engine/query result and state their
source interval, row count and transformation.

The verifier checks actual record resolution, vehicle/trip/provenance/source,
calculation values, units, grades, synthetic labeling, causal language and exact
claim-rendered prose. Any issue rejects the complete answer. The SLM does not
assign grades or generate final free-form prose. An answer is rendered only from
verified claim text.
