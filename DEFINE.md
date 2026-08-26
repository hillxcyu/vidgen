# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T04:27:15Z
*   **Target Task:** Expose Video Files via ADK Artifacts & Clickable Links
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Tool & Orchestrator Implementation [agent] [tools]
- [ ] `[T001]` **[tools]** Update `generate_video_shot_clip`, `concatenate_video_clips`, and `generate_multi_shot_video` in `app/agent.py` to register ADK artifacts via `tool_context.save_artifact` and return public GCS URLs (`video_url`).
- [ ] `[T002]` **[agent]** Update `vidgen_orchestrator` instruction in `app/agent.py` to format delivery with clickable markdown links, embedded `<video>` player tags, and shot clip links.

### Phase 2: Testing & CI/CD [test] [deploy]
- [ ] `[T003]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T004]` **[git]** Commit changes on `main` and push to GitHub.
- [ ] `[T005]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 3: Verification [verify]
- [ ] `[T006]` **[verify]** Verify live reasoning engine stream query returns valid delivery format with artifact and URL metadata.
