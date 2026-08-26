# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T08:23:00Z
*   **Target Task:** Equip Quality Rater Agent to Audit Actual Video Files via Multimodal Vision
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Tool Definition & Agent Tool Attachment [agent]
- [ ] `[T001]` **[agent]** Define `evaluate_video_clip_quality` tool in `app/agent.py` supporting local path / GCS URL multimodal loading.
- [ ] `[T002]` **[agent]** Attach `tools=[evaluate_video_clip_quality]` to `QualityRaterAgent` and update its instruction to mandate tool execution on the actual video file.

### Phase 2: Testing & CI/CD [test] [deploy]
- [ ] `[T003]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T004]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [ ] `[T005]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 3: Verification [verify]
- [ ] `[T006]` **[verify]** Verify live reasoning engine deployment.
