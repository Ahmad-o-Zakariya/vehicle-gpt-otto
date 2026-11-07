from __future__ import annotations

from typing import Any


def response_matches_context(
    entry: dict[str, Any], question: str, vehicle_id: str
) -> bool:
    response = entry.get("response", {})
    return (
        entry.get("question") == question
        and entry.get("vehicle_id") == vehicle_id
        and response.get("selected_vehicle_id") == vehicle_id
        and bool(response.get("request_id"))
        and response.get("request_id") == response.get("query_id")
    )


def begin_query(
    state: Any, local_request_id: str, question: str, vehicle_id: str
) -> None:
    state.pop("last_query", None)
    state["active_ui_request_id"] = local_request_id
    state["active_ui_context"] = (question, vehicle_id)


def commit_query_response(
    state: Any,
    local_request_id: str,
    question: str,
    vehicle_id: str,
    response: dict[str, Any],
) -> bool:
    if (
        state.get("active_ui_request_id") != local_request_id
        or state.get("active_ui_context") != (question, vehicle_id)
        or response.get("selected_vehicle_id") != vehicle_id
        or not response.get("request_id")
        or response.get("request_id") != response.get("query_id")
    ):
        return False
    state["last_query"] = {
        "response": response,
        "question": question,
        "vehicle_id": vehicle_id,
        "ui_request_id": local_request_id,
    }
    return True


def format_api_error(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail", payload)
        if isinstance(detail, dict):
            code = detail.get("code")
            message = detail.get("message") or detail.get("reasons")
            if isinstance(message, list):
                message = "; ".join(str(item) for item in message)
            if code and message:
                return f"{code}: {message}"
            if message:
                return str(message)
        if isinstance(detail, str):
            return detail
    return fallback
