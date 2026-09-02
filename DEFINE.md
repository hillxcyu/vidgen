# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-09-02T06:34:45Z
*   **Target Task:** Reference Adherence Benchmark: Pipeline-Optimized vs. Simple Prompt on Gemini Omni Flash 1.1
*   **Status:** COMPLETED

---

## 📝 Detailed TODO Breakdown

### Phase 1: Reference Image Generation [backend]
- [x] `[T001]` **[backend]** Generate canonical reference portrait of a 20-year-old Asian male using `gemini-3.1-flash-image` (Nano Banana 2) on Vertex AI (`project: vital-octagon-19612`).
- [x] `[T002]` **[backend]** Save reference image to `benchmarks/reference_xcyu.png` (1.5MB) and extract base64 string.

### Phase 2: Video Generations via Omni Flash [backend]
- [x] `[T003]` **[backend]** Generate Video A (Pipeline Optimized Prompt) with MMC control strings (`[# References <IMAGE_REF_0>[Character A]image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=5s] Character A, ...`) and attached reference image via `gemini-omni-1.1-flash-preview`. Saved to `benchmarks/video_pipeline_optimized.mp4` (2.4MB, 40.2s generation latency).
- [x] `[T004]` **[backend]** Generate Video B (Simple Prompt) with `[aspect_ratio=16:9] [resolution=720p] [duration=5s] xcyu (reference image) skiing in Hakuba` and attached reference image via `gemini-omni-1.1-flash-preview`. Saved to `benchmarks/video_simple_prompt.mp4` (2.8MB, 27.6s generation latency).

### Phase 3: Agentic Quality Evaluation & Report Generation [backend] [frontend]
- [x] `[T005]` **[backend]** Run `evaluate_video_clip_quality` with Gemini 3.7 Flash on both videos comparing against `reference_xcyu.png`.
  - Video A (Optimized): Facial Similarity 0.90, Outfit 0.95, Motion 0.92, Overall 0.92 (STRONG_ADHERENCE).
  - Video B (Simple): Facial Similarity 0.96, Outfit 0.97, Motion 0.94, Overall 0.96 (STRONG_ADHERENCE).
- [x] `[T006]` **[frontend]** Construct interactive side-by-side HTML comparison report (`benchmarks/index.html`) displaying the reference image, both video players, verbatim prompts, and quantitative/qualitative analysis.

### Phase 4: Deployment to x20 Web Hosting [deploy]
- [x] `[T007]` **[deploy]** Create target directory `/google/data/rw/users/xc/xcyu/www/reports/r2v_omini_flash_1_1/`.
- [x] `[T008]` **[deploy]** Copy `index.html`, `reference_xcyu.png`, `video_pipeline_optimized.mp4`, and `video_simple_prompt.mp4` to the x20 web directory.
- [x] `[T009]` **[deploy]** Apply `chmod -R a+rX /google/data/rw/users/xc/xcyu/www/reports/r2v_omini_flash_1_1/`.
- [x] `[T010]` **[deploy]** Verify HTTP 200/302 response via `curl` and provide live link: `https://x20web.corp.google.com/~xcyu/reports/r2v_omini_flash_1_1/`.
