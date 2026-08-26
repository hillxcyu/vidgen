# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T06:28:30Z
*   **Target Task:** Fix Gemini Enterprise "Failed to load attachment" by using URI Artifacts
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Tool Artifact Registration Updates [agent]
- [ ] `[T001]` **[agent]** Update `generate_video_shot_clip` in `app/agent.py` to upload to GCS first and register artifact using `types.Part.from_uri(file_uri=gcs_url, mime_type="video/mp4")`.
- [ ] `[T002]` **[agent]** Update `concatenate_video_clips` in `app/agent.py` to register artifact using `types.Part.from_uri`.
- [ ] `[T003]` **[agent]** Update `generate_multi_shot_video` in `app/agent.py` to register artifact using `types.Part.from_uri`.

### Phase 2: Testing & CI/CD [test] [deploy]
- [ ] `[T004]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T005]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [ ] `[T006]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 3: Verification [verify]
- [ ] `[T007]` **[verify]** Verify live reasoning engine stream query.
