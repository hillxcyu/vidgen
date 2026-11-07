# PLAN.md — Auto-Rater v2 & Pipeline Architecture (`feat/autorater-v2-pipeline`)

## [2026-11-03 16:20 UTC] Run 1 (COMPLETED): Auto-Rater v2 & Pipeline Architecture Implementation
- [x] **Phase 0:** Git Baseline Commit (`eaf2e99` on `main`) & Branch Isolation (`feat/autorater-v2-pipeline` `4844323`).
- [x] **Phase 1:** Auto-Rater v2 — Ground-Truth `#FFFFFF` + Prior Frame + High-Res `KEY FRAME A/M/B` Anchoring, Observation-First `property_ordering` Schema, and Deterministic OpenCV/FFMPEG/WER Telemetry (`RATER_TIMEOUT_MS=120000`).
- [x] **Phase 2:** Monotonic Best-of-$K$ Retry Checkpointing & Post-Stitch Master Seam Critic (`evaluate_stitched_master`).
- [x] **Phase 3:** Parallel Mode A (`asyncio.Semaphore`) Rendering, Per-Shot `mode_override` (`mode="hybrid"`), and Unified FastAPI `run_pipeline_async` Runner.
- [x] **Phase 4:** 69 Automated Unit/Integration/Calibration Tests Passed (`0 failed`) + Live Vertex AI Smoke Audit Verified.

---

## [2026-11-07 14:36 UTC] Run 2 (COMPLETED): Live 30s `mode="hybrid"` UC1 Apparel E2E Run & Auto-Rater v1 vs. v2 Benchmark

### Confirmed Scope & Constraints
- **Target Use Case:** **UC1 Apparel** (`uc1_apparel_anchor.png`, `3 × 10s` = `30s` at `720p`, `16:9`, `mode="hybrid"`, `max_attempts=3`).
- **Output Delivery:** Direct authenticated **GCS MP4 links** (`gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc1_apparel_hybrid_v2_30s/`) — live `main` Cloud Run deployment kept untouched.
- **Core Evaluation Goal:** Verify end-to-end performance of **Auto-Rater v2** in a live multi-shot generation loop alongside a direct **v1 vs. v2 rater comparison**.

---

### Completed Steps
- [x] **Step 1 — Head-to-Head Diagnostic Audit (`v1` vs. `v2`):** Evaluated 4 stress cases (clean valid shot, spoken copy drift `WER=1.0`, mid-sentence speech cutoff `-22.4 dBFS`, and cobalt-vs-terracotta `#FFFFFF` SKU color drift); confirmed **v2** catches `#FFFFFF` SKU drift missed by **v1** (`0.40 REATTEMPT` vs. `0.95 PASS`) and cuts per-shot rater latency by **20.7%–26.0%**.
- [x] **Step 2 — Live End-to-End 30s `mode="hybrid"` Commercial Generation (`max_attempts=3`):** Rendered Shot 1 (`reference` R2V, `f0_mae=107.8`), Shot 2 (`video_extend`, `seam_mae=6.06`), and Shot 3 (`reference` act-break re-anchor, `f0_mae=176.57`); all 3 passed **v2** (`1.00`, `WER=0.0`, zero cutoffs), while **v1** suffered a `0.65` False Reject on Shot 3 due to lacking access to `reference_anchor.png`.
- [x] **Step 3 — Post-Stitch Master Seam Audit & GCS Showcase Upload:** Stitched `output_stitched_30s.mp4` (`29.92s`), passed `evaluate_stitched_master()` (`0.95 PASSED`: `0.95` @ `10.0s`, `0.96` @ `20.0s`), and uploaded all MP4s, frames, anchor, and telemetry JSON to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc1_apparel_hybrid_v2_30s/`.
- [x] **Step 4 — Side-by-Side Results & User Sign-Off:** Confirmed by user (`2026-11-07T14:35:55Z`).
