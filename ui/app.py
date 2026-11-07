from __future__ import annotations

import json
import os
from uuid import uuid4

import plotly.express as px
import requests
import streamlit as st
from request_state import (
    begin_query,
    commit_query_response,
    format_api_error,
    response_matches_context,
)

API = os.getenv("VEHICLEGPT_API_URL", "http://127.0.0.1:8000")
EXAMPLES = [
    "Why has driving range reduced over the last two weeks?",
    "When did fuel efficiency show its largest drop?",
    "Show all ADAS disengagement events from yesterday.",
    "What happened before the battery overheating warning?",
    "Compare energy consumption between city and highway driving.",
]
st.set_page_config(page_title="VehicleGPT | TRACE", page_icon="🚘", layout="wide")
st.title("VehicleGPT · TRACE evidence explorer")
st.caption("Local prototype · read-only dataset · synthetic evidence is labelled")
try:
    vehicles = requests.get(API + "/vehicles", timeout=4).json()
    health = requests.get(API + "/health", timeout=4).json()
except requests.RequestException as exc:
    st.error(f"Backend unavailable at {API}: {exc}")
    st.stop()
with st.sidebar:
    st.subheader("Vehicle context")
    vehicle_ids = [v["vehicle_id"] for v in vehicles]
    vehicle = st.selectbox("Vehicle", vehicle_ids)
    try:
        caps = requests.get(API + f"/vehicles/{vehicle}/capabilities", timeout=5).json()
        st.caption(f"{len(caps)} measured signals available")
    except requests.RequestException:
        caps = []
    st.caption("Backend: " + health.get("status", "unknown"))
    st.caption("Planner mode: " + health.get("planner_mode", "unknown"))
    st.caption("Operational database: read-only")
example = st.selectbox("Example question", ["Choose an example…", *EXAMPLES])
question = st.text_area(
    "Ask about this dataset",
    value="" if example == "Choose an example…" else example,
    height=90,
)
run = st.button("Run query", type="primary", disabled=not question.strip())

stored = st.session_state.get("last_query")
if stored and not response_matches_context(stored, question, vehicle):
    st.session_state.pop("last_query", None)

if run:
    ui_request_id = str(uuid4())
    begin_query(st.session_state, ui_request_id, question, vehicle)
    with st.spinner("Planning and checking evidence…"):
        try:
            response = requests.post(
                API + "/query",
                json={"question": question, "vehicle_id": vehicle},
                timeout=45,
            )
            if response.status_code >= 400:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                st.error(format_api_error(payload, response.text))
            else:
                body = response.json()
                if not commit_query_response(
                    st.session_state, ui_request_id, question, vehicle, body
                ):
                    st.info(
                        "The response identity did not match the current request and was discarded."
                    )
        except requests.RequestException as exc:
            st.session_state.pop("last_query", None)
            st.error(f"Query request failed: {exc}")

stored = st.session_state.get("last_query")
if stored and response_matches_context(stored, question, vehicle):
    data = stored["response"]
    answer = data["answer"]
    result = data["engine_result"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Evidence grade", answer["overall_grade"])
    c2.metric("Coverage", answer["coverage_status"].upper())
    c3.metric("Execution", f"{data['latency_ms']:.1f} ms")
    st.markdown("### Answer")
    st.write(answer["text"])
    st.caption(
        f"Grounded by verifier: {'yes' if answer['grounded'] else 'no'} · planner: {data['planner_mode']}"
    )
    st.markdown("### Claims and evidence")
    for claim in answer["claims"]:
        with st.expander(
            f"{claim['claim_id']} · {claim['grade']} · {claim['verifier_status']}",
            expanded=True,
        ):
            st.write(claim["text"])
            if claim.get("limitations"):
                st.warning("; ".join(claim["limitations"]))
            st.json(
                [
                    e
                    for e in answer["evidence"]
                    if e["evidence_id"] in claim["evidence_refs"]
                ]
            )
    st.markdown("### Evidence coverage")
    st.json(result["coverage"])
    st.caption("Provenance: " + (", ".join(result.get("provenance", [])) or "none"))
    if result.get("missing_data"):
        st.warning("Missing or flagged data: " + "; ".join(result["missing_data"]))
    for limitation in result.get("limitations", []):
        st.info(limitation)
    points = result.get("result", {}).get("points", [])
    if points:
        st.markdown("### Signal history")
        fig = px.line(
            points,
            x="ts",
            y="value",
            color="trip_id",
            labels={
                "ts": "Source-derived replay timestamp",
                "value": data["plan"]["signals"][0]
                if data["plan"]["signals"]
                else "value",
            },
        )
        st.plotly_chart(fig, width="stretch")
    events = result.get("result", {}).get("events", [])
    if events:
        st.markdown("### Event timeline")
        flattened = []
        for event in events:
            metadata_raw = event.get("event_metadata_json") or "{}"
            try:
                event_metadata = (
                    json.loads(metadata_raw)
                    if isinstance(metadata_raw, str)
                    else metadata_raw
                )
            except TypeError, json.JSONDecodeError:
                event_metadata = {}
            flattened.append(
                {
                    "trip_id": event.get("trip_id"),
                    "event_type": event.get("event_type"),
                    "timestamp": event.get("event_timestamp"),
                    "offset_seconds": 0,
                    "role": "warning anchor, separate from preceding samples",
                    "signal": None,
                    "value": None,
                    "unit": None,
                    "provenance": "synthetic" if event.get("synthetic") else "real",
                    "source_snapshot_at_T0": event_metadata.get(
                        "captured_source_values"
                    )
                    if event.get("event_type") == "diagnostic.freeze_frame"
                    else None,
                    "synthetic_injected_state_at_T0": event_metadata.get(
                        "synthetic_injected_values_at_T0", "not stored in frozen v0.1.0"
                    )
                    if event.get("event_type") == "diagnostic.freeze_frame"
                    else None,
                }
            )
            flattened.extend(
                {
                    **sample,
                    "trip_id": event.get("trip_id"),
                    "event_id": event.get("event_id"),
                }
                for sample in event.get("timeline", [])
            )
        st.dataframe(flattened, width="stretch", hide_index=True)

    if result.get("event", {}).get("event_type") == "diagnostic.freeze_frame":
        metadata = result["event"].get("event_metadata_json") or "{}"
        try:
            metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
        except TypeError, json.JSONDecodeError:
            metadata = {"unparsed_metadata": metadata}
        st.markdown("### Freeze-frame provenance")
        st.caption(
            "Captured source values are original measurements at T0, not the synthetic injected state."
        )
        st.json(
            {
                "source_snapshot_at_T0": metadata.get("captured_source_values", {}),
                "synthetic_injected_state_at_T0": metadata.get(
                    "synthetic_injected_values_at_T0", "not stored in frozen v0.1.0"
                ),
            }
        )
