# `PLAN.md`

## 📋 Metadata
*   **Task:** Fix Gemini Enterprise "Failed to load attachment" by using URI Artifacts instead of Large Base64 Inline Blobs
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Fix Attachment Overload in `app/agent.py`**:
   - `tool_context.save_artifact` currently embeds 5MB–20MB of raw base64 video bytes into session state (`types.Part.from_bytes(...)`).
   - This oversized payload is transmitted on every subsequent SSE streaming event, exceeding streaming buffer limits and causing Gemini Enterprise to fail with `"Something went wrong while answering your question. Please try again later. Failed to load attachment"`.
   - Update `generate_video_shot_clip`, `concatenate_video_clips`, and `generate_multi_shot_video` to upload to the GCS showcase bucket first and save the artifact using `types.Part.from_uri(file_uri=gcs_url, mime_type="video/mp4")`.

2. **Testing & Deployment**:
   - Run unit and integration tests (`uv run pytest tests/unit tests/integration`).
   - Commit and push to `main` to trigger Cloud Build for Cloud Run.
   - Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

3. **Verification**:
   - Verify live reasoning engine stream query and confirm lightweight URI artifact serialization.
