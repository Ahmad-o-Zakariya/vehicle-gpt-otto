import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui"))
from request_state import begin_query, commit_query_response, response_matches_context


def response(vehicle="ved:455", request_id="rid"):
    return {
        "request_id": request_id,
        "query_id": request_id,
        "selected_vehicle_id": vehicle,
    }


def test_new_failed_query_clears_previous_answer_and_evidence():
    state = {
        "last_query": {
            "response": response(),
            "question": "old",
            "vehicle_id": "ved:455",
        }
    }
    begin_query(state, "new-local-id", "new question", "ved:119")
    assert "last_query" not in state
    assert state["active_ui_context"] == ("new question", "ved:119")


def test_response_only_commits_for_matching_request_and_vehicle():
    state = {}
    begin_query(state, "local-id", "question", "ved:119")
    assert not commit_query_response(
        state, "old-id", "question", "ved:119", response("ved:119")
    )
    assert not commit_query_response(
        state, "local-id", "question", "ved:455", response("ved:455")
    )
    malformed_identity = response("ved:119", "local-id")
    malformed_identity["query_id"] = "mismatched"
    assert not commit_query_response(
        state, "local-id", "question", "ved:119", malformed_identity
    )
    assert commit_query_response(
        state, "local-id", "question", "ved:119", response("ved:119", "local-id")
    )
    entry = state["last_query"]
    assert response_matches_context(entry, "question", "ved:119")
    assert not response_matches_context(entry, "edited question", "ved:119")
    assert not response_matches_context(entry, "question", "ved:455")
