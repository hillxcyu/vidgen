# `PLAN.md`

## 📋 Metadata
*   **Task:** Fix Reasoning Engine stream error for Gemini Enterprise (`streaming_agent_run_with_events` argument mismatch) and deploy updates
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Fix `reasoning_engine_adapter.py` Dispatch Logic**:
   - Inspect target method signature (`inspect.signature(method)`) dynamically.
   - For `streaming_agent_run_with_events`: pass only `request_json` (ensuring it is stringified JSON) without injecting unwanted `user_id` or `message` kwargs.
   - For `async_stream_query` / `stream_query`: maintain backward-compatible defaults (`user_id="default_user"`, mapping `prompt` to `message`).
   - Add robust error handling and logging inside the streaming generator.

2. **Verify Tests**:
   - Run unit & integration test suite (`uv run pytest tests/unit tests/integration`).

3. **Deploy & Update**:
   - Push commit to `main` to trigger Cloud Build for Cloud Run.
   - Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

4. **Verify Live Stream**:
   - Send `streamQuery` with `streaming_agent_run_with_events` to Agent Runtime in `asia-east1` and verify live events stream properly.
