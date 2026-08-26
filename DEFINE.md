# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T10:15:30Z
*   **Target Task:** Add Final Video Evaluation Step & Dual-Anchor (First & Last Frame) Shot Modification
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Frame Extraction & Dual-Anchor Omni Generation Tools [backend] [tools]
- [ ] `[T001]` **[tools]** Add `extract_first_frame(video_path: str, output_image_path: Optional[str])` to `app/tools/video_parser.py`.
- [ ] `[T002]` **[tools]** Update `build_omni_control_string` & `generate_omni_clip` in `app/tools/omni_client.py` to support `end_image_b64` (`<LAST_FRAME>image_1.png`).
- [ ] `[T003]` **[agent]** Add `parse_initial_frame(video_path: str)` tool to `app/agent.py`.
- [ ] `[T004]` **[agent]** Update `generate_video_shot_clip` in `app/agent.py` to accept `end_image_path: Optional[str] = None`.

### Phase 2: Agent Instructions & Pipeline Orchestration Logic [agent]
- [ ] `[T005]` **[agent]** Update `UNIFIED_BASE_SYSTEM_INSTRUCTION` and `vidgen_orchestrator` instruction in `app/agent.py` for:
  - Phase 3 Final Video Evaluation step by `QualityRaterAgent` on the stitched video.
  - Shot modification & regeneration flow using dual-anchor frames (`parse_terminal_frame` for shot $k-1$ and `parse_initial_frame` for shot $k+1$) and previous rater feedback.
- [ ] `[T006]` **[agent]** Update `PromptOptimizerAgent` and `QualityRaterAgent` instructions for feedback-driven refinement and full stitched video audits.

### Phase 3: Testing & CI/CD [test] [deploy]
- [ ] `[T007]` **[test]** Add unit tests in `tests/unit/test_video_parser.py` and `tests/unit/test_omni_client.py` for `extract_first_frame` and dual-anchor control strings.
- [ ] `[T008]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T009]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [ ] `[T010]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 4: Verification [verify]
- [ ] `[T011]` **[verify]** Verify live reasoning engine deployment and execution.
