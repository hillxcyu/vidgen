# DEFINE.md — Detailed Task Breakdown: Auto-Rater v2 & Pipeline Architecture (`feat/autorater-v2-pipeline`)

## [2026-11-03 16:20 UTC] Stage 2: Tagged TODO List

### Phase 0: Git Baseline Commit & Branch Isolation
- [x] `[git]` Restore `main`'s completed Mode-A `PLAN.md` / `DEFINE.md`, stage & commit the verified 3-mode + 9-run showcase baseline onto `main` so `main` has a clean working tree, then create and switch to `feat/autorater-v2-pipeline` and restore this `PLAN.md` / `DEFINE.md`.

### Phase 1: Auto-Rater v2 — Ground-Truth Anchoring, Observation-First Schema & Telemetry
- [x] `[autorater]` `[parallel]` Add deterministic telemetry & keyframe utilities in `app/tools/video_parser.py` (and `src/tools/video_parser.py` parity):
  - `extract_labeled_audit_keyframes(video_path)` -> returns `("KEY FRAME A (t=0.00s, opening)", png_bytes)`, `("KEY FRAME M (mid-shot)", png_bytes)`, and `("KEY FRAME B (terminal frame)", png_bytes)`.
  - `analyze_clip_audio_tail(video_path, tail_sec=0.20)` -> extracts `clip_duration_sec`, `mid_rms_db`, `trailing_rms_db` (`[duration - 0.2s, duration]`, i.e. `9.8s–10.0s` on a `10s` clip), and `speech_cutoff_detected: bool`.
  - `compute_transcript_metrics(expected_dialogue, heard_transcript)` -> returns deterministic `(transcript_wer, transcript_word_overlap)` using normalized word-level Levenshtein distance.
  - `decode_valid_image_b64(b64_str)` -> safely validates PNG/JPEG/WebP magic bytes so mock strings (e.g. `"fake_ref_b64"`) degrade gracefully in unit tests.
- [x] `[backend]` `[parallel]` Add `RATER_TIMEOUT_MS = 120000` (`120s`) and `MAX_PARALLEL_SHOTS = 3` in `app/config.py` and `src/config.py`.
- [x] `[autorater]` Upgrade `QualityEvaluationResult` and `evaluate_clip_quality()` in `app/agents/pipeline.py` (plus `evaluate_video_clip_quality()` in `app/agent.py`):
  - Place CoT grounding fields **strictly before `score` and `verdict`** (`opening_environment_observed`, `heard_transcript`, `speech_end_sec`, `detected_internal_cuts`) and pass an explicit `response_schema` with `property_ordering` (`["opening_environment_observed", "heard_transcript", "speech_end_sec", "detected_internal_cuts", "reason", "score", "verdict", "feedback"]`).
  - Attach captioned `CANONICAL REFERENCE ANCHOR (#FFFFFF)` (`reference_images_b64[0]`), `PRIOR SHOT TERMINAL FRAME` (`prev_last_frame_b64`), and labeled `KEY FRAME A / M / B` stills alongside `video_part`.
  - Inject deterministic OpenCV/FFMPEG telemetry (`clip_duration_sec`, `r2v_f0_mae`, `r2v_white_pct`, `seam_mae`, `peak_early_mae`, `mid_rms_db`, `trailing_rms_db`) into the rater prompt, compute `(transcript_wer, transcript_word_overlap)`, and apply deterministic post-rater score caps (`< 0.8` -> `REATTEMPT_REQUIRED`) on active `9.8s–10.0s` speech cutoffs, `transcript_wer > 0.35`, or `detected_internal_cuts > 0`.
  - Replace the per-attempt un-schematized `consolidate_rubric_with_llm()` call inside `evaluate_clip_quality()` with deterministic `build_shot_evaluation_rubric()` (keeping `consolidate_rubric_with_llm()` available for backward compatibility) and flag API timeout fallbacks explicitly with `audit_status="AUDIT_TIMEOUT_DEGRADED"`.

### Phase 2: Monotonic Best-of-$K$ Checkpointing & Post-Stitch Master Seam Rater
- [x] `[autorater]` Implement **Monotonic Best-of-$K$ Retry Checkpointing** inside shot generation in `app/agents/pipeline.py`: track `(best_score, best_video_bytes, best_prompt, best_eval_result)` across attempts `1..max_attempts` so lower-scoring final retries never overwrite a higher-scoring earlier clip.
- [x] `[autorater]` Add `MasterSeamEvaluationResult` and `evaluate_stitched_master()` in `app/agents/pipeline.py` (plus `master_quality_report: Optional[Dict[str, Any]] = None` on `PipelineState` in `app/state.py` / `src/state.py`) to audit `output_stitched_*.mp4` across seam transition windows (`[t_cut - 1.5s, t_cut + 1.5s]`) for voice timbre consistency, loudness continuity, and `xfade` smoothness.

### Phase 3: Parallel Mode A Execution, Per-Shot Hybrid Choreography & Unified Loop
- [x] `[backend]` `[parallel]` Extend `app/state.py` & `src/state.py`:
  - Add `mode_override: Optional[Literal["reference", "i2v_chaining", "video_extend"]] = None` to `StoryboardEntry` and `VideoShot`.
  - Add `"hybrid"` to `PipelineState.mode` (`Literal["reference", "i2v_chaining", "video_extend", "hybrid"]`) so `StoryboarderAgent` automatically assigns `"reference"` on act-break location jumps and `"video_extend"` / `"i2v_chaining"` on continuous takes.
- [x] `[backend]` Upgrade `run_production_loop_async()` in `app/agents/pipeline.py`:
  - Execute independent Mode A (`mode="reference"`) shots concurrently via `asyncio.Semaphore(Config.MAX_PARALLEL_SHOTS)` + `asyncio.gather` while preserving deterministic shot ordering for FFMPEG stitching.
  - Honor `shot.mode_override` (and `"hybrid"` mode) per shot cleanly.
- [x] `[backend]` `[frontend]` Unify `run_adk_pipeline_background()` in `app/fast_api_app.py` to delegate to `run_pipeline_async(..., event_callback=...)` while streaming Web Studio SSE `broadcast_log` events, and add the `🧬 Hybrid Choreography (Auto R2V + Extend/I2V)` option & badge in `app/templates/index.html` and `src/templates/index.html`.

### Phase 4: Unit, Integration, Golden Calibration Suite & Live Vertex AI Smoke Audit
- [x] `[qa]` `[parallel]` Create `tests/unit/test_autorater_v2.py` (with copyright & docstring header) testing ground-truth image & keyframe attachment, `property_ordering` schema structure, WER/overlap math, Best-of-$K$ monotonic selection, `evaluate_stitched_master`, parallel Mode A concurrency, and `"hybrid"` `mode_override` execution.
- [x] `[qa]` `[parallel]` Create `tests/unit/test_autorater_calibration.py` (with copyright & docstring header) testing synthetic golden positive vs. negative clips (`#FFFFFF`-locked Frame 0, seam jump-cuts, truncated `9.8s–10.0s` speech energy, and clean reference clips).
- [x] `[qa]` Run `uv run pytest tests/unit tests/integration -v` (100% pass target), execute a live Vertex AI `evaluate_clip_quality()` + `evaluate_stitched_master()` smoke audit on an existing retail showcase run + `#FFFFFF` anchor, log all results to `ACTION.md`, and create clean commits on `feat/autorater-v2-pipeline`.
