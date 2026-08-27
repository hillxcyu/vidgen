# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-27T07:17:20Z
*   **Target Task:** Cross-Shot Character Identity, Wardrobe Consistency & Per-Shot Directing Checkpoints
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Quality Rater Multimodal Cross-Shot Inspection [rater] [multimodal]
- [ ] `[T001]` **[rater]** Update `evaluate_video_clip_quality` in `app/agent.py` to accept `reference_image_path: Optional[str] = None`.
- [ ] `[T002]` **[rater]** Update the Gemini 3.7 Flash `generate_content` payload to attach the reference image Part alongside the video MP4 Part.
- [ ] `[T003]` **[rater]** Update the evaluation prompt with strict cross-shot continuity rubrics (penalizing face swaps, hair drift, clothing color mismatches).
- [ ] `[T004]` **[rater]** Replace masked `0.88` fallback with explicit failure diagnostics.

### Phase 2: Generation Reference Image Conditioning & Pipeline State [generator] [agent]
- [ ] `[T005]` **[generator]** Update `generate_video_shot_clip` in `app/agent.py` to accept `reference_image_path: Optional[str] = None` and pass `reference_images_b64` to `generate_omni_clip`.
- [ ] `[T006]` **[agent]** Update `vidgen_orchestrator` instructions to save `state["canonical_character_reference"]` on Shot 1 and pass it to all subsequent shot generations ($k \ge 2$) and evaluations.

### Phase 3: Per-Shot HITL Directing Checkpoints [hitl] [agent]
- [ ] `[T007]` **[agent]** Add per-shot interactive review checkpoint instructions to `vidgen_orchestrator` (pausing for director review after each shot with player and continuity score).

### Phase 4: Verification & Deployment [test] [git]
- [ ] `[T008]` **[test]** Add unit tests for `evaluate_video_clip_quality` with reference image and `generate_video_shot_clip` with reference asset in `tests/unit/test_agent.py`.
- [ ] `[T009]` **[test]** Run full test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T010]` **[git]** Commit changes on `main` and push to GitHub.
