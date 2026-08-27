# `PLAN.md`

## 📋 Metadata
*   **Task:** Fix Cross-Shot Character Identity & Wardrobe Continuity in Quality Rater & Video Generation
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-27
*   **Status:** APPROVED (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Multimodal Cross-Shot Continuity in `evaluate_video_clip_quality`**:
   - [ ] Add `reference_image_path: Optional[str] = None` parameter to `evaluate_video_clip_quality`.
   - [ ] Pass BOTH the reference character image Part (JPEG/PNG) and the target video clip Part (MP4) to Gemini 3.7 Flash.
   - [ ] Enforce strict cross-shot identity rubrics: penalize facial feature discrepancies, hair changes, and clothing/wardrobe color drift (<0.60 score / `RETRY` verdict).
   - [ ] Eliminate the masked fallback score (return explicit diagnostic `0.0` / `RETRY` instead of dummy `0.88`).

2. **Canonical Reference Image Conditioning in Video Generation**:
   - [ ] In `generate_video_shot_clip`, accept optional `reference_image_path: Optional[str] = None` and bind to `reference_images_b64` for Gemini Omni Flash `<IMAGE_REF_0>[Character A]`.
   - [ ] After Shot 1 is rendered, automatically save its initial keyframe as `state["canonical_character_reference"]` and `user:character_bible["main_character_frame"]`.
   - [ ] Feed `canonical_character_reference` into all subsequent shot generations ($k \ge 2$) and audits.

3. **Per-Shot HITL Directing Checkpoints with Interactive Review**:
   - [ ] Pause at each shot in interactive mode (`user:directing_mode == 'interactive'`), displaying the player, link, and cross-shot consistency audit, and offering the user one-click approval or dual-anchor regeneration.

---

## 🧪 Testing & Verification Plan

1. **Unit & Integration Tests**:
   - Test `evaluate_video_clip_quality` with `reference_image_path`.
   - Test `generate_video_shot_clip` with reference image conditioning.
   - Run full pytest test suite (`uv run pytest tests/unit tests/integration`).
2. **Git Commit & Cloud Build**:
   - Commit & push to `main`.
