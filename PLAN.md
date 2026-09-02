# `PLAN.md`

## 📋 Metadata
*   **Project / Task:** Reference Adherence Benchmark: Pipeline-Optimized vs. Simple Prompt on Gemini Omni Flash 1.1
*   **Timestamp:** 2026-09-02T06:35:00Z
*   **Author:** Hill YU (xcyu@)
*   **Status:** AWAITING_REVIEW

---

## 🎯 Objective
Investigate and benchmark character reference adherence in `gemini-omni-1.1-flash-preview` (R2V / Image-to-Video with Reference conditioning). Specifically, compare:
1. **Pipeline-Optimized Prompt**: Full multi-agent cinematic description with standard MMC tags (`[# References <IMAGE_REF_0>[Character A]image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=5s] Character A, ...`).
2. **Simple Prompt**: Direct, unadorned prompt (`xcyu (reference image) skiing in Hakuba`) with the reference image attached in the payload.

Results will be compiled into an interactive side-by-side HTML comparison report and deployed to `https://x20web.corp.google.com/~xcyu/reports/r2v_omini_flash_1_1/` using the `x20-upload` skill.

---

## 📐 Architecture & Execution Plan

### Step 1: Generate Canonical Character Reference Image
*   **Model:** `gemini-3.1-flash-image` (Nano Banana 2) on Vertex AI (`project: vital-octagon-19612`, `location: global`).
*   **Prompt:** Realistic portrait of a 20-year-old Asian male, sharp facial features, neutral lighting, looking directly at camera, alpine/winter gear.
*   **Output:** Save to `reference_xcyu.png` and encode to base64.

### Step 2: Generate Video A (Pipeline-Optimized Prompt)
*   **Model:** `gemini-omni-1.1-flash-preview`.
*   **Prompt Generation:** Run the pipeline's Screenwriter / Prompt Optimizer or format the canonical cinematic shot prompt:
    *   *Prompt Text:* `"Character A, Continuous single take, dynamic cinematic tracking shot following the character skiing on Hakuba Happo-One ridge, crisp alpine morning light, Japanese Northern Alps in the background, sharp cinematic depth of field, high quality, photorealistic."`
    *   *Full Omni Control String:* `[# References <IMAGE_REF_0>[Character A]image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=5s] Character A, Continuous single take...`
*   **Input Payload:** Text prompt + 1 attached reference image.
*   **Output:** Save to `video_pipeline_optimized.mp4`.

### Step 3: Generate Video B (Simple Prompt)
*   **Model:** `gemini-omni-1.1-flash-preview`.
*   **Prompt Text:** `"xcyu (reference image) skiing in Hakuba"`
*   **Full Omni Payload:**
    *   *Prompt Text:* `[aspect_ratio=16:9] [resolution=720p] [duration=5s] xcyu (reference image) skiing in Hakuba` (also testing direct `<IMAGE_REF_0>[xcyu]image_0.png` binding).
    *   *Images:* 1 attached reference image.
*   **Output:** Save to `video_simple_prompt.mp4`.

### Step 4: Quality & Reference Adherence Evaluation
*   Run the newly integrated **Agentic Video Understanding** (`media_processing="agentic"` on `gemini-3.7-flash`) to audit both videos:
    *   Subject Identity Consistency against reference image.
    *   Motion Dynamics & Skiing Realism.
    *   Prompt Adherence.

### Step 5: Build Interactive HTML Comparison Report
*   Self-contained, modern web design:
    *   Header: Model metadata, timestamp, experiment goals.
    *   Reference Asset Card: Displays the generated 20yo Asian male reference image with its exact generation prompt.
    *   Side-by-Side Video Players: Synchronized playback controls for Video A (Optimized) vs. Video B (Simple).
    *   Verbatim Prompt Display: Exact raw control strings and payloads sent to Omni Flash.
    *   Metric & Observation Breakdown: Quantitative scores + qualitative analysis of character resemblance, facial stability, and skiing motion.
*   Save as `index.html`.

### Step 6: Deploy to x20 Web Hosting
*   **Target Directory:** `/google/data/rw/users/xc/xcyu/www/reports/r2v_omini_flash_1_1/`
*   Copy `index.html`, `reference_xcyu.png`, `video_pipeline_optimized.mp4`, and `video_simple_prompt.mp4`.
*   Apply permissions: `chmod -R a+rX /google/data/rw/users/xc/xcyu/www/reports/r2v_omini_flash_1_1/`.
*   Verify via `curl` and provide live link: `https://x20web.corp.google.com/~xcyu/reports/r2v_omini_flash_1_1/`.

---

## ❓ Clarifications & Confirmation
1. For Video B (Simple prompt), would you like the prompt text to literally be `[aspect_ratio=16:9] [resolution=720p] [duration=5s] xcyu (reference image) skiing in Hakuba` or pure plain text without any bracket tokens? (We recommend keeping the format tokens `[aspect_ratio=16:9] [resolution=720p] [duration=5s]` so the video resolution matches 720p 16:9, while keeping the user prompt completely minimal).
2. Please confirm to proceed to Stage 2 (`DEFINE.md`) and Stage 3 (`ACTION.md`).
