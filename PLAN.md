# `PLAN.md`

## 📋 Metadata
*   **Task:** Add Final Video Evaluation Step & Dual-Anchor (First & Last Frame) Shot Modification
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Final Video Evaluation Step (Quality Rater Audit for Stitched Video)**:
   - In Phase 3 (Post-Production), after `concatenate_video_clips` produces the final stitched video (`stitched_video.mp4`), `vidgen_orchestrator` must delegate to `QualityRaterAgent` to evaluate the **entire stitched final video**.
   - `QualityRaterAgent` audits the full video via `evaluate_video_clip_quality` across:
     - Cross-shot character/subject identity consistency
     - Narrative pacing & seamless shot-to-shot transitions
     - Overall color grading and lighting stability
     - Audio and spoken dialogue flow
   - Outputs the **Overall Final Video Quality Score & Report** to the chat stream.

2. **Dual-Anchor (First & Last Frame) Shot Modification & Regeneration**:
   - Add `extract_first_frame` in `app/tools/video_parser.py` and `parse_initial_frame` tool in `app/agent.py`.
   - Update `build_omni_control_string` and `generate_omni_clip` in `app/tools/omni_client.py` to accept `end_image_b64` (`<LAST_FRAME>image_1.png`).
   - Update `generate_video_shot_clip` in `app/agent.py` to accept `end_image_path: Optional[str] = None`.
   - When modifying or regenerating shot `k`:
     - **Preceding Anchor (First Frame of Shot k)**: Last frame of shot $k-1$ via `parse_terminal_frame`.
     - **Succeeding Anchor (Last Frame of Shot k)**: First frame of shot $k+1$ via `parse_initial_frame`.
     - **Feedback Chaining**: Pass previous `QualityRaterAgent` critique/suggestions to `PromptOptimizerAgent` for targeted refinement.
     - Generate shot $k$ with dual-frame constraints (`input_image_path` + `end_image_path`).
     - Re-stitch and perform final video quality evaluation.

3. **Testing & Deployment**:
   - Add unit tests for `extract_first_frame`, `parse_initial_frame`, and dual-anchor control strings.
   - Run unit and integration tests (`uv run pytest tests/unit tests/integration`).
   - Commit & push to `main` (Cloud Run deployment).
   - Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

4. **Verification**:
   - Verify final video evaluation and dual-anchor shot modification in live pipeline.
