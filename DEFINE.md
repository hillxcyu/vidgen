# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T08:23:00Z
*   **Target Task:** Equip Quality Rater Agent to Audit Actual Video Files via Multimodal Vision
*   **Status:** ✅ ALL_TASKS_COMPLETED

---

## 📝 Detailed TODO Breakdown

### Phase 1: Tool Definition & Agent Tool Attachment [agent]
- [x] `[T001]` **[agent]** Define `evaluate_video_clip_quality` tool in `app/agent.py` supporting local path / GCS URL multimodal loading.
- [x] `[T002]` **[agent]** Attach `tools=[evaluate_video_clip_quality]` to `QualityRaterAgent` and update its instruction to mandate tool execution on the actual video file.

### Phase 2: Testing & CI/CD [test] [deploy]
- [x] `[T003]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [x] `[T004]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [x] `[T005]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 3: Verification [verify]
- [x] `[T006]` **[verify]** Verify multimodal video evaluation tool execution and live deployment status.
