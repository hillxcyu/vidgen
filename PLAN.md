# `PLAN.md`

## 📋 Metadata
*   **Task:** Equip Quality Rater Agent to Audit Actual Video Files via Multimodal Vision
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Root Cause Analysis**:
   - `QualityRaterAgent` was previously defined in `app/agent.py` without any tools (`tools=[]`).
   - When the orchestrator transferred control to `QualityRaterAgent` passing the text string `video_path`, the LLM had no way to load or inspect the video bytes. It generated synthetic scores from text alone, which is why video file accesses/multimodal spans never appeared in the trace.

2. **Implement `evaluate_video_clip_quality` Tool in `app/agent.py`**:
   - Implement `evaluate_video_clip_quality(video_path: str, prompt: str, evaluation_criteria: Optional[str])`:
     - Reads the actual `.mp4` video bytes from local filesystem (or GCS).
     - Passes `types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")` to Gemini 3.7 Flash multimodal vision.
     - Audits the real video frames across Subject Consistency, Motion Smoothness, Prompt Adherence, and Temporal Asset Persistence.
     - Returns structured scores, rubric breakdown, verdict, and detailed critique.
   - Attach `tools=[evaluate_video_clip_quality]` to `QualityRaterAgent`.
   - Update `QualityRaterAgent` instruction mandating invoking `evaluate_video_clip_quality` on the video file before reporting scores.

3. **Testing & Deployment**:
   - Run test suite (`uv run pytest tests/unit tests/integration`).
   - Commit and push to `main` for Cloud Run.
   - Deploy to Vertex AI Agent Runtime in `asia-east1`.

4. **Verification**:
   - Verify multimodal video evaluation tool execution and live deployment status.
