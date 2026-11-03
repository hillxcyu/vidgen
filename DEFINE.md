# DEFINE.md — Detailed Task Breakdown: Mode A (`reference` R2V) Examples & 11-Slide Unified Hub + Comparison

## [2026-11-03 15:53 UTC] Stage 2: Tagged TODO List

### Phase 1: Mode A (`mode="reference"`) 30s Showcase Generation & 9-Run GCS Sync
- [x] `[pipeline]` Author `scratch/retail_showcase/run_retail_cases_r2v_mode_a.py` (with copyright & docstring header) for all 3 retail campaigns (`retail_uc1_apparel_r2v_30s`, `retail_uc2_footwear_r2v_30s`, `retail_uc3_beauty_r2v_30s`):
  - Configure **Shots 1, 2, and 3 (`0–10s`, `10–20s`, `20–30s`)** to independently use `task="reference_to_video"` with `[anchor_b64]` (`Character A`), `input_image_b64=None`, `input_video_b64=None` across 3 distinct editorial environments per SKU.
  - Enforce `detect_r2v_first_frame_lock()` (`MAE >= 12.0` and `white_px <= 25%`) with up to 3 attempts per shot, and extract `shot_{1,2,3}_first_frame.png` + `shot_{1,2,3}_last_frame.png`.
- [x] `[pipeline]` Execute `run_retail_cases_r2v_mode_a.py`, stitch all 3 × 30s masters via `stitch_videos()` (`80ms` `xfade` + `acrossfade`), upload clips/frames/masters to `gs://vital-octagon-19612-vidgen-showcase/showcase/`, and update `output/saved_runs.json` + GCS `saved_runs.json` with all **9 pinned runs** (`3 × video_extend` + `3 × i2v_chaining` + `3 × reference`).

### Phase 2: Web Studio 9-Run Showcase Drawer & Cloud Run Deployment
- [x] `[frontend]` `[parallel]` Polish Showcase Drawer mode badges in `app/templates/index.html` and `src/templates/index.html` so `reference` (`🎨 Shared R2V`), `i2v_chaining` (`⚡ I2V Chaining`), and `video_extend` (`🎞️ Video Extend`) are visually distinct across all 9 pinned runs.
- [x] `[qa]` Run `uv run pytest tests/unit tests/integration` to verify 100% test pass rate before deployment.
- [x] `[infra]` `[parallel]` Build and deploy `vidgen-frontend` on Cloud Run (`vital-octagon-19612`, `asia-east1`) with the 9-run `saved_runs.json` seed manifest and verify revision readiness.

### Phase 3: Mode A Storyboard Composites & 11-Slide Bilingual GTM Decks (`EN` & `ZH-CN`)
- [x] `[gtm-slides]` `[parallel]` Create `scratch/retail_showcase/build_mode_a_composites.py` to render bilingual `2×2` Mode A storyboard strips (`uc{1,2,3}_r2v_strip_{en,zh}.png`: `#FFFFFF Anchor` + `0–10s Scene 1 R2V` + `10–20s Scene 2 R2V` + `20–30s Scene 3 R2V`) via `uv run --with pillow python ...` and upload to `gs://vital-octagon-19612-vidgen-showcase/showcase/composites/`.
- [x] `[gtm-slides]` Update deck builder script (`v11_` element IDs, `11`-slide pagination `01 / 11 .. 11 / 11`) for both **EN (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`)** and **ZH-CN (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`)**:
  - **Slide 7 (NEW):** Mode A (`#FFFFFF` Shared Canonical R2V) 3-card 30s Retail Showcase (`UC1`, `UC2`, `UC3` clickable MP4s + Frame-0 MAE / multi-location metrics).
  - **Slide 8:** Mode B (`Shot 1 R2V + <FIRST_FRAME> I2V`) 3-card 30s Retail Showcase.
  - **Slide 9:** Mode C (`Shot 1 R2V + 5.0s Audio-Intact Video Extend`) 3-card 30s Retail Showcase.
  - **Slide 10 (Unified Fast-Access Hub + Method Comparison + Hybrid Combinations):**
    - Top/Left **3-Mode Engineering Comparison Table** (`Mode A: Shared R2V` vs. `Mode B: I2V Chaining` vs. `Mode C: 5s Video Extend` — Conditioning, Parallelism, Cut/Motion Physics, Best Use Case & Trade-offs).
    - Right **All-9 Fast-Access Clickable MP4 Grid** (`UC1 Apparel`, `UC2 Footwear`, `UC3 Beauty` × `[🎨 R2V | ⚡ I2V | 🎞️ Extend]`) + `🎬 Live Web Studio (9 Runs)` button.
    - Bottom **Hybrid Multi-Mode Choreography Callout** (*Act-Break Re-Anchoring*: `Mode A` → `Mode C` unbroken take → `Mode A` location cut re-locking `#FFFFFF` SKU + `Dual-Anchor` surgical middle-shot edits).
  - **Slide 11:** GTM Qualification Matrix & 2-Week Retail Pilot Path.
- [x] `[qa]` Export PDFs (`en_v11.pdf`, `zh_v11.pdf`) and rasterize PNGs (`audit_v11/`), visually inspecting Slides 7, 8, 9, 10, and 11 in both EN and ZH-CN to confirm zero text overflow, clean margins, and accurate links.
