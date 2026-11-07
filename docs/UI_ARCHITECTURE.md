# UI and API architecture

The Streamlit/Plotly frontend in `ui/app.py` calls FastAPI and contains no engine logic. FastAPI (`src/vehicle_gpt/api/app.py`) exposes health, vehicle list, measured capabilities, query, typed-plan execution, real-only event listing, canonical signal history, and evidence resolution. Request/response models reject extra fields; app scripts bind to `127.0.0.1`; CORS permits only the local UI origins.

The UI presents vehicle selection, example/free-text questions, planner mode, answer, evidence grade, coverage, latency, claim evidence, missingness, limitations, measured history plots, and event rows. Synthetic status is surfaced in the answer and provenance. The browser process was checked with HTTP 200 and API integration queries were exercised for all five case-study families. This is a functional smoke check; no visual browser review or accessibility audit was completed.

Start `scripts/run_backend.sh` and `scripts/run_ui.sh` in separate terminals. Set `VEHICLEGPT_DEMO_MODE=1` for the clearly labeled deterministic development planner. Default planner mode requires the local llama.cpp service described in `SLM_PLANNER.md`. API history/event limits and read-only repository policy apply to UI requests as well.
