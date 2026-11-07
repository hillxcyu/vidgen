# DEFINE.md — Detailed Task Breakdown: Deploy to Cloud Run, Regenerate All 9 Showcase Videos & Update Bilingual GTM Decks

## [2026-11-07 14:42 UTC] Stage 2: Tagged TODO List

### Phase 1: Pipeline Hardening, Pre-Merge Tests & Git Merge to `main`
- [ ] `[backend]` Update `run_adk_agent()` in `app/agents/pipeline.py` to execute fallback single-agent calls on an isolated `Agent` clone (`disallow_transfer_to_parent=True`, `disallow_transfer_to_peers=True`, `tools=[]`) so transient timeouts never trigger parent `vidgen_orchestrator` transfers.
- [ ] `[backend]` Update `GenerateRequest` and `run_adk_pipeline_background()` in `app/fast_api_app.py` (and `save_run()` in `app/tools/gcs_storage.py` / `src/tools/gcs_storage.py`) to:
  - Accept optional `storyboard: Optional[List[Dict[str, Any]]] = None` on `POST /api/pipeline/start` so canonical 3-scene retail campaigns can be triggered natively through the Cloud Run API.
  - Extract & upload `shot_{k}_first_frame.png` and `reference_anchor.png` alongside `shot_{k}.mp4`, `shot_{k}_last_frame.png`, and `output_stitched_30s.mp4` during `save_run()`, and include `master_quality_report` in `run_manifest.json` (while leaving `output/saved_runs.json` free of unpinned ad-hoc test runs).
- [ ] `[qa]` Add unit tests in `tests/unit/test_autorater_v2.py` covering isolated `run_adk_agent` fallback and `GenerateRequest.storyboard` passthrough, then run `uv run --no-sync pytest tests/unit tests/integration tests/test_pipeline.py -v` + `g4 fix` / linter checks as applicable.
- [ ] `[git]` Commit onto `feat/autorater-v2-pipeline` and fast-forward merge `feat/autorater-v2-pipeline` into `main`.

### Phase 2: Deploy `main` to Cloud Run (`vidgen-frontend`) & Verify Live Service
- [ ] `[deploy]` Build and deploy `main` to Cloud Run `vidgen-frontend` (`project=vital-octagon-19612`, `region=asia-east1`, `--cpu=2`, `--memory=4Gi`, `--no-cpu-throttling`, `--session-affinity`, `--cpu-boost`, `--timeout=1800`, `--set-env-vars=GOOGLE_CLOUD_PROJECT=vital-octagon-19612,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=True,VIDGEN_GCS_BUCKET=vital-octagon-19612-vidgen-showcase,GCS_SHOWCASE_BUCKET=vital-octagon-19612-vidgen-showcase`).
- [ ] `[qa]` Smoke-test live `https://vidgen-frontend-440790012685.asia-east1.run.app/` (`GET /`, `GET /api/runs/list`, and `/api/gcs/...` media proxy).

### Phase 3: Trigger Generation of All 9 Canonical 30s Showcase Videos on Deployed Cloud Run
- [ ] `[showcase]` Write runner script `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/trigger_all_9_cloudrun_showcase.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + module docstring) and trigger all **9 × 30s (`3 × 10s`, 720p, `max_attempts=3`)** showcase runs against live Cloud Run `https://vidgen-frontend-440790012685.asia-east1.run.app/api/pipeline/start` in reverse display order so final pinned order is `#1..#9` (`Mode C` -> `Mode B` -> `Mode A`, `UC1` -> `UC2` -> `UC3`):
  1. **Mode A (`mode="reference"` — Parallel Shared `#FFFFFF` R2V):** `retail_uc3_beauty_r2v_30s`, `retail_uc2_footwear_r2v_30s`, `retail_uc1_apparel_r2v_30s`
  2. **Mode B (`mode="i2v_chaining"` — Shot 1 R2V + `<FIRST_FRAME>` I2V):** `retail_uc3_beauty_regional_30s`, `retail_uc2_footwear_hero_30s`, `retail_uc1_apparel_lookbook_30s`
  3. **Mode C (`mode="video_extend"` — Shot 1 R2V + `5.0s` Audio-Intact Video Extend):** `retail_uc3_beauty_extend_30s`, `retail_uc2_footwear_extend_30s`, `retail_uc1_apparel_extend_30s`
- [ ] `[showcase]` `[parallel]` Download the 9 freshly rendered GCS runs (`output_stitched_30s.mp4`, `shot_1..3_first_frame.png`, `shot_1..3_last_frame.png`, `run_manifest.json`) to local `output/{run_id}/`, compute updated OpenCV Frame-0 / seam MAE + Auto-Rater v2 + Master Seam Critic summary JSONs, and sync clean 9-run `saved_runs.json` to `gs://vital-octagon-19612-vidgen-showcase/showcase/saved_runs.json`.

### Phase 4: Rebuild Storyboard Composites & Update 11-Slide Bilingual Google Slides Decks (`EN` & `ZH-CN`)
- [ ] `[slides]` `[parallel]` Rebuild all bilingual `2×2` storyboard composite strips (`uc{1,2,3}_r2v_strip_{en,zh}.png`, `uc{1,2,3}_strip_{en,zh}.png`, `uc{1,2,3}_extend_strip_{en,zh}.png`) from the newly generated 9 videos and upload them to `gs://vital-octagon-19612-vidgen-showcase/showcase/composites/`.
- [ ] `[slides]` Update and execute the 11-slide deck builder for both **English (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`)** and **Simplified Chinese (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`)** presentations—incorporating Auto-Rater v2 (observation-first CoT + `#FFFFFF` ground-truth + WER/audio-tail telemetry + Master Seam Critic) on Slide 5 & Speaker Notes, updated continuity/rater metrics on Slides 6–10, and fresh composite strips on Slides 7–9.
- [ ] `[qa]` Export both updated decks to PDF/PNG and perform a **4-Quadrant Active Vision Audit** (`read_file` inspection across updated slides in both `EN` and `ZH-CN`) to verify zero text overflow, zero element overlap, and working links, logging all steps to `ACTION.md`.
