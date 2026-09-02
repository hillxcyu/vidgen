# `ACTION.md`

## 📋 Metadata
*   **Execution Task:** Reference Adherence Benchmark: Pipeline-Optimized vs. Simple Prompt on Gemini Omni Flash 1.1
*   **Started At:** 2026-09-02T06:34:45Z
*   **Completed At:** 2026-09-02T06:40:50Z
*   **Status:** COMPLETED

---

## 📜 Execution Log

* **[2026-09-02T06:35:40Z]** Generated canonical 20-year-old Asian male reference image wearing alpine ski jacket and dark beanie using `gemini-3.1-flash-image` (Nano Banana 2) on Vertex AI (`project: vital-octagon-19612`). Saved to `benchmarks/reference_xcyu.png` (1,487,239 bytes).
* **[2026-09-02T06:36:30Z]** Generated Video A with pipeline-optimized prompt and MMC control string tags (`[# References <IMAGE_REF_0>[Character A]image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=5s] Character A, continuous single take...`) via `gemini-omni-1.1-flash-preview` in 40.21s (2,428,173 bytes).
* **[2026-09-02T06:37:00Z]** Generated Video B with simple prompt (`[aspect_ratio=16:9] [resolution=720p] [duration=5s] xcyu (reference image) skiing in Hakuba`) via `gemini-omni-1.1-flash-preview` in 27.61s (2,903,085 bytes).
* **[2026-09-02T06:40:08Z]** Performed quality and reference adherence audit with `gemini-3.7-flash` on keyframes against `reference_xcyu.png`:
  * **Video A (Optimized)**: Facial Similarity 0.90, Outfit 0.95, Motion 0.92, Overall 0.92.
  * **Video B (Simple)**: Facial Similarity 0.96, Outfit 0.97, Motion 0.94, Overall 0.96.
* **[2026-09-02T06:40:40Z]** Constructed side-by-side interactive HTML report (`benchmarks/index.html`) displaying verbatim prompts, video players, and score breakdowns.
* **[2026-09-02T06:40:41Z]** Deployed report and all media assets to `/google/data/rw/users/xc/xcyu/www/reports/r2v_omini_flash_1_1/` using the `x20-upload` skill.
* **[2026-09-02T06:40:44Z]** Verified live reachability: `https://x20web.corp.google.com/~xcyu/reports/r2v_omini_flash_1_1/`.
