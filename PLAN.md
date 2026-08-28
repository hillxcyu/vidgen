# `PLAN.md`

## 📋 Metadata
*   **Task:** Fix Reference Image Ingestion in Sequential Image-to-Video (`i2v_chaining`) Mode
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-28
*   **Status:** PENDING_USER_APPROVAL

---

## 🔍 Root Cause Analysis

In [`app/fast_api_app.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/fast_api_app.py#L668-L687) and [`app/agents/pipeline.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agents/pipeline.py#L656-L675), there was an `if/else` branch:

```python
# CURRENT CODE (BUG):
if mode == "i2v_chaining":
    video_bytes = generate_omni_clip(
        prompt=optimized_prompt,
        input_image_b64=prev_frame_b64, # <--- Only passed previous frame anchor!
        # reference_images_b64 was DROPPED!
    )
else: # reference mode
    video_bytes = generate_omni_clip(
        prompt=optimized_prompt,
        reference_images_b64=reference_assets_b64, # <--- Passed reference image
    )
```

### Why this broke I2V Mode:
1. **Shot 1**: `prev_frame_b64` is `None` and `reference_images_b64` was not passed. Shot 1 generated from pure text without seeing the character reference image.
2. **Shots 2 & 3**: Only the terminal frame was passed (`<FIRST_FRAME>`), but the canonical character reference image was never attached as `<IMAGE_REF_0>[Character A]`.

In contrast, **Asset Reference Mode** passed `reference_images_b64=reference_assets_b64`, which is why it worked properly!

---

## 📋 Proposed Step-by-Step Fix Plan

1. **Unify Reference Asset Injection in I2V Mode**:
   * Update [`app/fast_api_app.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/fast_api_app.py) and [`app/agents/pipeline.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agents/pipeline.py) so `generate_omni_clip` receives `reference_images_b64=reference_assets_b64` across **all modes** (both `i2v_chaining` and `reference`).
   * For **Shot 1**: `input_image_b64` is `None`, and `reference_images_b64` attaches `<IMAGE_REF_0>[Character A]image_0.png`.
   * For **Shots 2+**: Passes **both** `<FIRST_FRAME>image_0.png` (for seamless motion chaining) AND `<IMAGE_REF_0>[Character A]image_1.png` (for persistent character identity locking).

2. **Verify with Pytest**:
   * Run full test suite: `uv run pytest tests/unit tests/integration`.

3. **Deploy Updated Container to Cloud Run & Agent Runtime**:
   * Build container with Cloud Build and update Cloud Run (`vidgen-frontend`) in `vital-octagon-19612`.
   * Deploy updated agent to Vertex AI Agent Runtime in `vital-octagon-19612`.
   * Commit and push to GitHub `main`.
