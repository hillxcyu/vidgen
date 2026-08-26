# `PLAN.md`

## 📋 Metadata
*   **Task:** Expose Video Files via ADK Artifacts & Clickable HTTPS Links (Gemini Enterprise & ADK UI)
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Native ADK Artifact Registration in Tools (`app/agent.py`)**:
   - In `generate_video_shot_clip`, `concatenate_video_clips`, and `generate_multi_shot_video`:
     - Accept `tool_context: Optional[ToolContext] = None`.
     - When video bytes are generated or stitched, call `await tool_context.save_artifact(filename, types.Part.from_bytes(data=video_bytes, mime_type="video/mp4"))`.
     - This causes Vertex AI Agent Runtime to expose the file directly in the `:streamQuery` event artifacts array for Gemini Enterprise / ADK UI file download card.

2. **GCS Showcase Sync & Public HTTPS Streaming**:
   - Sync the stitched video and clips to `gs://universal-trail-492014-n5-vidgen-showcase` and return `video_url` (`https://storage.googleapis.com/...`).

3. **Orchestrator Delivery Formatting (`app/agent.py`)**:
   - Instruct `vidgen_orchestrator` to format the final delivery with:
     - `[▶️ Click here to watch / download the generated video]({video_url})`
     - `<video controls width="100%" src="{video_url}"></video>`
     - Detailed shot breakdown with individual clip URLs and quality scores.

4. **Testing & Deployment**:
   - Run `uv run pytest tests/unit tests/integration`.
   - Commit to `main` and push to GitHub (triggers Cloud Build for Cloud Run).
   - Update Vertex AI Agent Runtime in `asia-east1` with `agents-cli deploy`.

5. **Verification**:
   - Test live execution to verify that artifacts and URLs are properly produced.
