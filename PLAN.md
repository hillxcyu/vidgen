# `PLAN.md`

## 📋 Metadata
*   **Task:** Fix ADK Debug UI Artifact Fetching (`"Failed to fetch artifact data: Invalid response data: missing mimeType or data or text"`)
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Root Cause Analysis in ADK Debug UI**:
   - The compiled ADK browser client (`browser/main-KSQARI5D.js`) specifically requires artifact GET endpoints to return `inlineData.data`/`inlineData.mimeType`, `data`/`mimeType`, or `text`.
   - When artifacts are saved with `file_data` (`types.Part.from_uri`), the raw FastAPI artifact endpoint returns `{ "fileData": { "fileUri": "...", "mimeType": "..." } }` without top-level `mimeType` or `data`, causing the ADK frontend to throw `"Failed to fetch artifact data: Invalid response data: missing mimeType or data or text"`.

2. **Implement Enhanced Artifact Endpoint in `app/fast_api_app.py`**:
   - Add `format_artifact_for_adk_ui` which dynamically resolves `file_data` (from local storage or GCS) into base64 `data` and `inlineData` on demand when requested by the ADK UI.
   - Attach enhanced GET `/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_name:path}/versions/{version_id}` and `/artifacts/{artifact_name:path}` route handlers.
   - Leaves the SSE streaming state unbloated (~100B per event for Gemini Enterprise) while allowing the ADK Debug UI to fetch and render full video player previews on demand.

3. **Testing & Deployment**:
   - Run unit and integration tests (`uv run pytest tests/unit tests/integration`).
   - Commit and push to `main` to deploy to Cloud Run via Cloud Build.
   - Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

4. **Verification**:
   - Verify artifact retrieval endpoint via TestClient and live service.
