# `PLAN.md`

## 📋 Metadata
*   **Task:** Fix Stream Serialization Crash for Artifacts (`TypeError: Object of type Part is not JSON serializable`)
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Fix JSON Serialization in `reasoning_engine_adapter.py`**:
   - `AdkApp.streaming_agent_run_with_events` yields `_StreamingRunResponse` objects where artifact versions contain raw `google.genai.types.Part` objects.
   - Implement `safe_json_dumps` encoder in `reasoning_engine_adapter.py` that serializes `types.Part` (via `.model_dump()`), Pydantic models, and raw bytes safely.
   - Prevents the stream generator from crashing when artifacts are registered, allowing the full generation and delivery message to reach Gemini Enterprise.

2. **Streamline GCS Bucket Access (`app/tools/gcs_storage.py`)**:
   - Avoid unnecessary IAM policy mutation requests on existing buckets during runtime.

3. **Testing & Deployment**:
   - Run unit and integration tests (`uv run pytest tests/unit tests/integration`).
   - Commit and push to `main` to deploy to Cloud Run via Cloud Build.
   - Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

4. **Verification**:
   - Verify live `:streamQuery` with `streaming_agent_run_with_events` to ensure artifact events serialize without dropping the connection.
