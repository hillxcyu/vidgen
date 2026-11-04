# PLAN.md — Auto-Rater v2 & Pipeline Architecture Improvements (`feat/autorater-v2-pipeline`)

## [2026-11-03 16:20 UTC] Stage 1: Confirmed Final Plan (Local + Vertex AI Validation; Cloud Run Stays on `main`)

### Objective
Implement the full suite of **Auto-Rater v2 (`QualityRaterAgent`)** and **Pipeline Architecture** upgrades on a dedicated Git feature branch (`feat/autorater-v2-pipeline`) branched cleanly from the verified `main` baseline.

---

### Step-by-Step Plan

1. **Phase 0 — Git Baseline Commit & Branch Isolation (`feat/autorater-v2-pipeline`)**
   - Commit the verified 3-mode (`reference`, `i2v_chaining`, `video_extend`) + 9-run showcase baseline cleanly onto `main` so `main` has a clean working tree.
   - Create and check out a new feature branch `feat/autorater-v2-pipeline` for all Auto-Rater v2 and pipeline changes.

2. **Phase 1 — Auto-Rater v2: Multimodal Ground-Truth Anchoring, Observation-First Schema & Deterministic Telemetry**
   - **Ground-Truth & Hybrid Keyframe Payload (`evaluate_clip_quality` in `app/agents/pipeline.py` & `evaluate_video_clip_quality` in `app/agent.py`):**
     - Attach captioned ground-truth image parts (`CANONICAL REFERENCE ANCHOR (#FFFFFF)` from `reference_images_b64[0]` and `PRIOR SHOT TERMINAL FRAME` from `prev_last_frame_b64`) alongside the `AGENTIC` `video_part`, plus captioned high-res keyframe stills (`KEY FRAME A` at `t=0.0s`, `KEY FRAME M` mid-shot, `KEY FRAME B` terminal frame via `extract_boundary_and_mid_keyframes`) so fine SKU/facial/wardrobe details are evaluated against ground truth rather than intra-clip only.
     - Gracefully skip malformed/mock base64 strings so existing unit/integration tests remain 100% green.
   - **Observation-First Schema (`property_ordering`) & Deterministic OpenCV/FFMPEG/WER Signals (`QualityEvaluationResult` & `app/tools/video_parser.py`):**
     - Place all 4 CoT grounding fields **strictly before `score` and `verdict`** in `QualityEvaluationResult` AND enforce explicit JSON schema `propertyOrdering` (`["opening_environment_observed", "heard_transcript", "speech_end_sec", "detected_internal_cuts", "reason", "score", "verdict", "feedback"]`):
       1. `opening_environment_observed: str`
       2. `heard_transcript: str`
       3. `speech_end_sec: Optional[float]`
       4. `detected_internal_cuts: int`
       (plus deterministic post-computed fields `transcript_wer: Optional[float]`, `transcript_word_overlap: Optional[float]`, and `audit_status: str`).
     - Feed a structured **Deterministic OpenCV & FFMPEG Telemetry Block** directly into `evaluate_clip_quality()`'s prompt context:
       - `clip_duration_sec` (exact container/frame duration from OpenCV/FFprobe)
       - `r2v_f0_mae` & `r2v_white_pct` (Frame-0 vs. `#FFFFFF` anchor pixel MAE & white-pixel %)
       - `seam_mae` & `peak_early_mae` (Shot $k-1$ terminal frame vs. Shot $k$ Frame-0 MAE)
       - `trailing_rms_db` (`[duration - 0.2s, duration]`, i.e. `9.8s–10.0s` on a `10s` clip, vs. mid-clip speech `mid_rms_db` via `analyze_clip_audio_tail()`)
     - Compute **both** exact word-level Levenshtein **WER (`transcript_wer`)** and **word-overlap (`transcript_word_overlap`)** deterministically between `heard_transcript` and `spoken_dialogue` (`compute_transcript_metrics()`), applying deterministic score caps (`score < 0.8` -> `REATTEMPT_REQUIRED`) whenever speech is still hot in `9.8s–10.0s` (`speech_cutoff_detected`), `transcript_wer > 0.35`, or `detected_internal_cuts > 0`.
   - **Zero-Extra-Hop Rubric Builder & Dedicated `120s` Rater Timeout (`app/config.py`, `app/agents/pipeline.py`):**
     - Replace the per-attempt un-schematized `consolidate_rubric_with_llm()` call inside `evaluate_clip_quality()` with deterministic mode-aware `build_shot_evaluation_rubric()` (saving 1 LLM round-trip / ~3–6s per shot attempt while keeping `consolidate_rubric_with_llm()` intact for backward compatibility).
     - Add `RATER_TIMEOUT_MS = 120000` (`120s`) in `Config` for multi-turn `AGENTIC` video inspection, and explicitly flag timeout fallbacks with `audit_status="AUDIT_TIMEOUT_DEGRADED"` instead of spoofing an unflagged pass.

3. **Phase 2 — Monotonic Best-of-$K$ Retry Checkpointing & Post-Stitch Master Seam Audit**
   - **Best-of-$K$ Checkpointing (`run_production_loop_async`):**
     - Track `(best_score, best_video_bytes, best_prompt, best_eval_result)` across retry attempts `1..max_attempts` so a lower-scoring final attempt never overwrites a higher-scoring earlier attempt.
   - **Post-Stitch Master Seam Rater (`evaluate_stitched_master`):**
     - Add a Pattern-B whole-commercial rater pass on `output_stitched_*.mp4` targeting seam transition windows (`[t_cut - 1.5s, t_cut + 1.5s]` at `10s`, `20s`, ...) to audit cross-shot voice timbre, acoustic loudness continuity, and `xfade` smoothness, saving `master_quality_report` on `PipelineState`.

4. **Phase 3 — Pipeline Architecture Upgrades: Parallel Mode A, Per-Shot Hybrid Choreography & Unified Loop**
   - **Parallel Mode A Rendering (`mode="reference"`):**
     - Render independent R2V shots concurrently via `asyncio.gather` bounded by `Config.MAX_PARALLEL_SHOTS = 3`, cutting 30s Mode A wall-clock latency by **~3×**.
   - **Per-Shot Hybrid Mode Schedule (`mode_override` & `mode="hybrid"`):**
     - Add optional `mode_override: Optional[Literal["reference", "i2v_chaining", "video_extend"]] = None` on `StoryboardEntry` and `VideoShot`, plus `mode="hybrid"` on `PipelineState` (and Web Studio selector) so `StoryboarderAgent` can automatically assign `"reference"` at act-break location jumps and `"video_extend"` / `"i2v_chaining"` on continuous takes within the same spot.
   - **Unify `app/fast_api_app.py` Orchestration with `run_pipeline_async`:**
     - Route `run_adk_pipeline_background` in `app/fast_api_app.py` through `run_pipeline_async(..., event_callback=...)` so Web Studio SSE streaming and CLI/SDK execution share a single source-of-truth pipeline loop.

5. **Phase 4 — Automated Unit, Integration, Golden Calibration Tests & Live Vertex AI Smoke Verification**
   - Add `tests/unit/test_autorater_v2.py` and `tests/unit/test_autorater_calibration.py` covering ground-truth image attachment, observation-first schema validation, Best-of-$K$ retry selection, `evaluate_stitched_master`, parallel Mode A execution, `"hybrid"` per-shot scheduling, and synthetic calibration cases (`#FFFFFF`-locked Frame 0, seam jump-cuts, clipped speech tail vs. clean baseline).
   - Run `uv run pytest tests/unit tests/integration -v`, run a live Vertex AI Auto-Rater v2 smoke audit against an existing showcase clip + `#FFFFFF` anchor, and commit all verified changes to `feat/autorater-v2-pipeline`.
