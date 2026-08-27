# `PLAN.md`

## 📋 Metadata
*   **Task:** Verify and Enhance QualityRater Multimodal Reference Image Continuity Audit
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-27
*   **Status:** IN_PROGRESS

---

## 🎯 Analysis & Objectives

### 1. How QualityRater Uses the Reference Image
* In `evaluate_video_clip_quality`, when a reference image exists (from user input or Shot 1 first frame), it attaches the reference image bytes as a `Part.from_bytes(...)` alongside the MP4 video `Part.from_bytes(...)` in the `client.models.generate_content` call to Gemini 3.7 Flash.
* Gemini 3.7 Flash performs cross-modal comparison between the image and video frames, evaluating facial structure, hair color, skin tone, wardrobe color, and clothing style, with a mandatory score penalty (< 0.60) and `RETRY` verdict on character morphing or costume mismatch.

### 2. Implementation Enhancements
- [ ] Broaden state scope fallback resolution for `ref_img_path` in `evaluate_video_clip_quality` across `canonical_character_reference`, `reference_image_path`, and `user:character_bible['main_character_frame']`.
- [ ] Add URL download support for `ref_img_path` (supporting GCS / HTTPS reference image URLs).
- [ ] Add explicit logging of the reference image audit status to Cloud Logging.
- [ ] Run full test suite: `uv run pytest tests/unit tests/integration`.
- [ ] Deploy updated agent container to Vertex AI Agent Runtime in `asia-east1`.
- [ ] Commit and push to GitHub `main`.
