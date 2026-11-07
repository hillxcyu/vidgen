# DEFINE.md — Detailed Task Breakdown: End-to-End UC1 Apparel `mode="hybrid"` Run & Auto-Rater v2 Evaluation

## [2026-11-07 14:03 UTC] Stage 2: Tagged TODO List

### Phase 1: Benchmark Harness & Baseline Auto-Rater v1 vs. v2 Diagnostic
- [x] `[autorater]` `[parallel]` Write an evaluation & E2E runner script in `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/run_e2e_hybrid_autorater_v2.py` (with `# Copyright 2026 Author:Hill YU(xcyu@)` and top-level docstring) that:
  - Implements a faithful `evaluate_clip_v1_baseline()` comparator mirroring `main`'s legacy rater (`consolidate_rubric_with_llm` + prompt-only `video/mp4`, no `#FFFFFF` anchor, no CoT observation fields, no `trailing_rms_db` or `transcript_wer` telemetry).
  - Runs **v1 vs. v2** head-to-head on existing UC1 shots (plus any newly rendered attempts) to record latency (`ms`), `score`, `verdict`, `heard_transcript`, `transcript_wer`, `trailing_rms_db`, and false-pass / discrimination deltas.

### Phase 2: Live End-to-End 30s `mode="hybrid"` Generation (`UC1 Apparel`, `max_attempts=3`)
- [x] `[backend]` Execute `run_pipeline_async()` end-to-end on **UC1 Apparel** (`output/retail_uc1_apparel_extend_30s/uc1_apparel_anchor.png`, `mode="hybrid"`, `num_shots=3`, `duration=10`, `max_attempts=3`) into `output/retail_uc1_apparel_hybrid_v2_30s/`:
  - Verify `ScreenwriterAgent` -> `StoryboarderAgent` (`mode_override` assignment: Shot 1 `"reference"` -> Shot 2 `"video_extend"` -> Shot 3 `"reference"` act-break re-anchor) -> `PromptOptimizerAgent` -> `HealthCheckerAgent` -> `GeminiOmniFlash` -> OpenCV guardrails -> **`QualityRaterAgent` v2** -> **Best-of-$K$ checkpointing**.
  - Capture every attempt's full `EVALUATE_QUALITY` event (`opening_environment_observed`, `heard_transcript`, `speech_end_sec`, `detected_internal_cuts`, `transcript_wer`, `trailing_rms_db`, `r2v_f0_mae`, `seam_mae`, `score`, `best_score_so_far`, `verdict`, and `feedback`).

### Phase 3: Post-Stitch Master Seam Audit & GCS Upload (`[gcs]`)
- [x] `[autorater]` Verify FFMPEG `80ms` `xfade` + `acrossfade` stitching (`output_stitched_30s.mp4`) and capture the live **`EVALUATE_MASTER_SEAMS`** report (`seam_observations` across `[8.5s–11.5s]` and `[18.5s–21.5s]`, `voice_timbre_consistent`, `loudness_continuity_ok`, `visual_xfade_smooth`, `score`, `verdict`).
- [x] `[gcs]` `[parallel]` Upload `output_stitched_30s.mp4`, `shot_1.mp4`, `shot_2.mp4`, `shot_3.mp4`, extracted frames, `reference_anchor.png`, and `e2e_autorater_v2_telemetry.json` to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc1_apparel_hybrid_v2_30s/` with `Cache-Control: no-cache, max-age=0` (without modifying `main`'s `saved_runs.json`).

### Phase 4: Side-by-Side E2E Performance Report & Logging (`[qa]`)
- [x] `[qa]` Also run `evaluate_clip_v1_baseline()` on the newly generated shots (including any retried attempts if a retry occurred) so we have an exact apples-to-apples **v1 vs. v2** comparison on the live E2E run.
- [x] `[qa]` Log full CLI/telemetry outputs to `ACTION.md`, mark `DEFINE.md` items complete, and present the direct clickable GCS MP4 links + **Auto-Rater v1 vs. v2 E2E Performance Table** for confirmation.
