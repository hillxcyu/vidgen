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


---

## [2026-11-07 14:42 UTC] Stage 1: Confirmed Final Plan — Merge to `main`, Deploy to Cloud Run (`vidgen-frontend`), Regenerate All 9 Showcase Videos & Refresh Bilingual 11-Slide Decks

### Confirmed Scope & Constraints
- **Do NOT pin** the ad-hoc `retail_uc1_apparel_hybrid_v2_30s` test run yet.
- Merge `feat/autorater-v2-pipeline` into `main` and deploy to Cloud Run (`vidgen-frontend`).
- After successful Cloud Run deployment, **trigger generation of all 9 canonical 30s (`3 × 10s`, 720p) retail showcase videos** (`3 SKUs × 3 Modes`: Mode A `reference`, Mode B `i2v_chaining`, Mode C `video_extend`) using the newly deployed Auto-Rater v2 + Best-of-$K$ + Parallel Mode A + Master Seam Critic code, then **rebuild composites and update both 11-slide bilingual Google Slides decks (`EN` & `ZH-CN`)**.

### Step-by-Step Plan

1. **Step 1 — ADK Sub-Agent Fallback Isolation & Cloud Run Batch-Run Readiness (`app/agents/pipeline.py`, `app/fast_api_app.py`)**
   - Isolate standalone sub-agent fallback executions inside `run_adk_agent()` (`disallow_transfer_to_parent=True`, `disallow_transfer_to_peers=True`, `tools=[]`) so a transient timeout on `PromptOptimizerAgent` or `HealthCheckerAgent` never transfers up to `vidgen_orchestrator`.
   - Accept optional pre-structured `storyboard` entries on `POST /api/pipeline/start` (`GenerateRequest` in `app/fast_api_app.py`) and copy `reference_anchor.png` + `shot_*_first_frame.png` alongside `save_run()` so Cloud Run natively executes and pins exact canonical 3-scene retail campaigns to `gs://vital-octagon-19612-vidgen-showcase/showcase/{run_id}/`.

2. **Step 2 — Pre-Deployment Test Suite & Git Merge (`feat/autorater-v2-pipeline` → `main`)**
   - Run `uv run --no-sync pytest tests/unit tests/integration tests/test_pipeline.py` (confirming 100% pass rate including new unit test coverage).
   - Commit onto `feat/autorater-v2-pipeline` and fast-forward merge into `main`.

3. **Step 3 — Deploy `main` to Cloud Run (`vidgen-frontend`) & Verify Live Endpoints**
   - Deploy `main` to Cloud Run service `vidgen-frontend` (`vital-octagon-19612`, `asia-east1`, `2 vCPU / 4Gi RAM`, `--no-cpu-throttling`, `--session-affinity`, `--cpu-boost`, `--timeout=1800`, `GOOGLE_CLOUD_PROJECT=vital-octagon-19612`, `GOOGLE_CLOUD_LOCATION=global`, `GOOGLE_GENAI_USE_VERTEXAI=True`, `GCS_SHOWCASE_BUCKET=vital-octagon-19612-vidgen-showcase`).
   - Verify live `/`, `/api/runs/list`, and `/api/gcs/...` streaming at `https://vidgen-frontend-440790012685.asia-east1.run.app`.

4. **Step 4 — Trigger Generation of All 9 Showcase 30s Videos on Deployed Cloud Run Service**
   - Trigger all **9 × 30s (`3 × 10s`, 720p, `max_attempts=3`)** retail showcase runs directly against the deployed Cloud Run `vidgen-frontend` API (`POST /api/pipeline/start` → poll `/api/pipeline/session/{id}` → verify GCS upload & pin order):
     - **Mode A (`reference` — Parallel Shared `#FFFFFF` R2V):** `retail_uc3_beauty_r2v_30s`, `retail_uc2_footwear_r2v_30s`, `retail_uc1_apparel_r2v_30s`
     - **Mode B (`i2v_chaining` — Shot 1 R2V + `<FIRST_FRAME>` I2V):** `retail_uc3_beauty_regional_30s`, `retail_uc2_footwear_hero_30s`, `retail_uc1_apparel_lookbook_30s`
     - **Mode C (`video_extend` — Shot 1 R2V + `5.0s` Audio-Intact Video Extend):** `retail_uc3_beauty_extend_30s`, `retail_uc2_footwear_extend_30s`, `retail_uc1_apparel_extend_30s`
   - Sync freshly rendered frames, manifests, and continuity/Auto-Rater v2 metrics to `gs://vital-octagon-19612-vidgen-showcase/showcase/` and local `output/`.

5. **Step 5 — Rebuild Storyboard Composites & Update Bilingual 11-Slide Google Slides Decks (`EN` & `ZH-CN`)**
   - Rebuild all bilingual `2×2` storyboard composite strips (`uc{1,2,3}_{r2v,strip,extend_strip}_{en,zh}.png`) from the newly rendered 9 videos.
   - Update both **English (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`)** and **Simplified Chinese (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`)** 11-slide decks (including Auto-Rater v2 & Master Seam Critic architecture/metrics + fresh Mode A/B/C showcase visuals and links) and run a **4-Quadrant Active Vision Audit** (`PDF` → `PNG` → visual inspection) confirming zero layout defects.
