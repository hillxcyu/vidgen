# DEFINE.md — Stage 2: Task Decomposition (Regenerate All 3 Shots of `retail_uc3_beauty_extend_30s` with Dropper Cap Persistence & Update Decks)

## [2026-11-08 05:58 UTC] Decomposed TODO List (Run 6)

### Phase 1: Update `retail_uc3_beauty_extend_30s` 3-Shot Storyboard & Component-Level AVU Rubric
- [x] `[prompts]` Update `retail_uc3_beauty_extend_30s` in `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/regenerate_all_9_omni12_v3.py`:
  - **Scene 1 (`0–10s`, R2V):** Spokesperson in champagne-ivory silk blazer lifts the glass pipette slightly to release one luminous golden serum drop and **lowers the pipette back into the bottle neck so the gold collar and white rubber bulb dropper cap sit cleanly on top of the amber bottle** by the end of Shot 1.
  - **Scene 2 (`10–20s`, `video_extend`):** Unbroken single-take slow dolly-in inside the sunlit travertine marble studio as she holds and gently tilts the **complete, closed amber-gold glass bottle with its gold collar and white rubber dropper bulb handle intact on top** in warm morning sunbeams.
  - **Scene 3 (`20–30s`, `video_extend`):** Unbroken single-take smooth orbital close-up as she sets the **complete, fully capped amber-gold glass bottle — with its gold collar and white rubber dropper bulb handle clearly seated on top — onto the sunlit travertine counter beside white orchids**.
  - Update `evaluation_criteria` across Scenes 1–3 so `QualityRaterAgent` (`gemini-3.8-flash` AVU) explicitly requires the **gold collar + white rubber dropper bulb cap/handle** to remain visible and intact (scoring `< 0.80` if the bottle ever appears uncapped/bare-threaded in Shot 3).

### Phase 2: Full 3-Shot Regeneration (`0–30s`), AVU Audit & Multi-Frame Contact-Sheet Verification
- [x] `[e2e]` Execute `uv run --no-sync python .../regenerate_all_9_omni12_v3.py --force --only retail_uc3_beauty_extend_30s --concurrency 1` (`VIDEO_GEN_MODEL=gemini-omni-1.2-flash`, `VIDEO_EXTEND_MODEL=gemini-omni-1.2-flash`, `ORCHESTRATOR_MODEL=gemini-3.8-flash`, `MEDIA_PROCESSING=agentic`, `max_attempts=3`).
- [x] `[qa]` Build a 15-frame visual contact sheet (`0.5s` to `29.5s`) plus inspect `shot_1_last_frame.png`, `shot_2_last_frame.png`, and `shot_3_last_frame.png` via `read_file` to verify: (a) gold collar + white rubber bulb dropper cap/handle is 100% present and seated on the bottle in Shot 3, (b) `WER = 0.0` across all 3 shots, and (c) low OpenCV `seam_mae` across both boundaries. *(If Shot 3 `extend` drops the cap on any attempt, apply automatic `<FIRST_FRAME> + <LAST_FRAME>` interpolation to a `gemini-nano-banana-2.1` capped-bottle closing keyframe and re-stitch.)*

### Phase 3: Pin Updated `#3` in Canonical `#1..#9` Order & Refresh Bilingual Slide 9 (`EN` & `ZH-CN`)
- [x] `[e2e]` Run canonical `#1..#9` GCS pinning (`regenerate_all_9_omni12_v3.py --concurrency 2`, `[SKIP-CACHED]` on all 9 runs) to update `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_extend_30s/` (`pinned_at` > container seed so live Cloud Run `vidgen-frontend` immediately serves the new video) and sync `output/saved_runs.json`.
- [x] `[slides]` `[parallel]` Rebuild `uc3_extend_strip_en.png` & `uc3_extend_strip_zh.png` (`build_all_composites_v13.py`), update Slide 9 (`Mode C`) metrics & composites in place across both **English (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`)** and **Simplified Chinese (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`)** 15-slide decks (keeping Slides 1–8 and 10–15 untouched), and visually verify rendered `en_slide-09.png` and `zh_slide-09.png`.


---

## [2026-11-08 02:54 UTC] Stage 2 (`/btw` Side Thread): Task Decomposition — 90s Hierarchical 3-Scene Commercial (`retail_uc3_beauty_90s`)

### 1. Hierarchical Multi-Scene & Two-Frame Interpolation Upgrade in `Skill/vidgen-long-video`
- [x] `[skill]` `[parallel]` Enhance [Skill/vidgen-long-video/scripts/omni_direct.py](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/Skill/vidgen-long-video/scripts/omni_direct.py):
  - Harden `<FIRST_FRAME> + <LAST_FRAME>` two-frame interpolation (`end_image_b64` + `input_image_b64`): attach explicit `response_format={"type": "video", "aspect_ratio": aspect_ratio, "duration": f"{duration}s", "resolution": resolution}` and natural-language two-frame role hint (`"Use the first image as the starting frame and the second image as the final frame."`), plus retry/backoff on transient `429` / `503`.
  - Add `generate_reference_image_direct()` (and CLI subcommand `generate-image`) calling `gemini-nano-banana-2.1` (`aspect_ratio="16:9"`, filtering `part.thought == True`) to synthesize clean per-scene architectural reference plates and interpolation boundary keyframes when needed.
- [x] `[skill]` Enhance [Skill/vidgen-long-video/scripts/run_vidgen_workflow.py](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/Skill/vidgen-long-video/scripts/run_vidgen_workflow.py):
  - Add `--scenes-json` and `--max-parallel-scenes` (default `2`) supporting hierarchical `N`-scene long-form video orchestration (`SceneSpec` -> `Shot 1` R2V + `Shots 2..K` `video_extend`).
  - Implement automatic **Post-Scene AVU Rating + Targeted `<FIRST_FRAME>+<LAST_FRAME>` Interpolation Self-Healing**:
    - Audit each `30s` scene video (`evaluate_stitched_master_direct`) and all 3 individual `10s` shots (`evaluate_clip_quality_direct`, `MediaProcessing.AGENTIC`).
    - For any shot scoring `< 0.80` (or flagged by the scene seam critic), regenerate that shot via `10s` `<FIRST_FRAME> + <LAST_FRAME>` interpolation (`Shot 2`: `shot_1_last_frame.png -> shot_3_first_frame.png`; `Shot 1`: grounded opening keyframe -> `shot_2_first_frame.png`; `Shot 3`: `shot_2_last_frame.png` -> closing hero keyframe), re-rate with Auto-Rater v2, keep the higher-scoring version, and re-stitch `scene_{i}_30s.mp4`.
  - Assemble all validated `30s` scene videos into `output_master_90s.mp4` (`0.0s` clean act-break cuts across locations; `80ms` `xfade`/`acrossfade` inside each scene) and run a final 90s Master Continuity Audit.
- [x] `[docs]` `[parallel]` Update [Skill/vidgen-long-video/SKILL.md](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/Skill/vidgen-long-video/SKILL.md) and [Skill/vidgen-long-video/references/storyboard_spec.md](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/Skill/vidgen-long-video/references/storyboard_spec.md) with the `--scenes-json` hierarchical 90s+ workflow and `<FIRST_FRAME>+<LAST_FRAME>` repair documentation.
- [x] `[test]` Add unit test coverage in [tests/unit/test_standalone_skill.py](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/tests/unit/test_standalone_skill.py) verifying hierarchical multi-scene execution and automatic `<FIRST_FRAME>+<LAST_FRAME>` interpolation self-healing when a shot scores `< 0.80`, then run `uv run --no-sync pytest tests/unit/test_standalone_skill.py -v`.

### 2. Per-Scene Reference Plate Synthesis & 90s Storyboard Spec (`retail_uc3_beauty_90s`)
- [x] `[assets]` `[parallel]` Copy canonical [uc3_beauty_anchor.png](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/output/retail_uc3_beauty_extend_30s/uc3_beauty_anchor.png) into `output/retail_uc3_beauty_90s/refs/` and generate the 3 people-free `16:9` scene environment reference plates via `omni_direct.py generate-image` (`gemini-nano-banana-2.1`):
  - `scene1_travertine_sanctuary_ref.png` (sunlit warm beige travertine bathroom vanity with orchid stem & morning window light).
  - `scene2_botanical_atelier_ref.png` (sunlit limestone-and-glass botanical skincare table with chamomile blooms & apothecary glassware).
  - `scene3_golden_terrace_ref.png` (golden-hour architectural limestone rooftop terrace with olive planters & travertine plinth).
- [x] `[assets]` Visually inspect all 3 generated reference plates to confirm crisp `16:9` framing, zero people/faces, and cohesive luxury skincare aesthetic, then write `output/retail_uc3_beauty_90s/scenes_storyboard.json`.

### 3. Live 90s (`3 × 30s`) Parallel Scene Execution, Rating, Repair & GCS Preview Upload
- [x] `[pipeline]` Execute `uv run --no-sync python Skill/vidgen-long-video/scripts/run_vidgen_workflow.py --scenes-json output/retail_uc3_beauty_90s/scenes_storyboard.json --max-parallel-scenes 2 --output-dir output/retail_uc3_beauty_90s` against Vertex AI (`gemini-omni-1.2-flash` + `gemini-3.8-flash` AVU).
- [x] `[delivery]` Verify `output_master_90s.mp4` (`~90.0s`, audio/video sync, per-shot & per-scene AVU scores, and any interpolation repairs), upload `output_master_90s.mp4`, `scene_1..3_30s.mp4`, reference plates, and `run_manifest.json` to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_90s_preview/`, and present clickable playback links + telemetry report.


---

## [2026-11-08 03:56 UTC] Stage 2 (`/btw` Side Thread): Task Decomposition — 3 New Bilingual Infographic & Diagram Slides (Slides 11–13 of 14)

### 1. Visual Asset Extraction & High-DPI Thumbnail Framing (`scratch/skill_slide_assets/`)
- [x] `[assets]` `[parallel]` Write `scratch/prepare_skill_slide_assets.py` (with mandatory `# Copyright 2026 Author:Hill YU(xcyu@)` + top-of-file module docstring) to extract and fit crisp, aspect-locked PNG thumbnails from `output/retail_uc3_beauty_90s/`:
  - **Slide 11 Anchors & Scene Plates:** Fitted `#FFFFFF` Hero Character+SKU Anchor (`uc3_beauty_anchor.png`) + the 3 `16:9` `Nano Banana 2.1` architectural plates (`scene1_travertine_sanctuary_ref.png`, `scene2_botanical_atelier_ref.png`, `scene3_golden_terrace_ref.png`).
  - **Slide 13 Auto-Heal Visual Frames:** Fitted `<FIRST_FRAME>` lock (`scene_1/shot_2_last_frame.png`), synthesized `<LAST_FRAME>` anchor (`scene_1/shot_3_interp_end.png`), and healed mid-shot still extracted via OpenCV from `scene_1/shot_3.mp4` (`Score 1.00 ACCEPTED`).

### 2. Bilingual Native-Vector Infographic & Flowchart Builder (`scratch/add_skill_3_slides.py`)
- [x] `[slides]` Author `scratch/add_skill_3_slides.py` (with mandatory copyright + module docstring, UTF-16 code-unit `u16_len`, `ROUND_RECTANGLE` / `DIAMOND` shapes, bound `createLine` + `updateLineProperties` `FILL_ARROW` connectors, zero `solidFill.alpha`, dark `#202124` text on yellow fills, and idempotent slide replacement):
  - **Insertion & Page Counter Sync:** Dynamically inspect existing slides on `EN` (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`) and `ZH-CN` (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`), insert `v13_s11_skill_arch_{lang}`, `v13_s12_autoheal_{lang}`, and `v13_s13_90s_proof_{lang}` at indices `10, 11, 12` (shifting `GTM Qualification & 2-Week Pilot` to Slide 14), and update all footer page counters across Slides 1–14 to `XX / 14`.
  - **Slide 11 (`Skill + Antigravity/Jetski Harness vs. ADK & 90s Swimlane Topology`):**
    - Left architectural contrast diagram comparing **Custom `google-adk` Stack** (rigid sub-agent transfers, `SessionService` boilerplate, SDK pinning, isolated from Workspace tools) vs. **`Skill/vidgen-long-video` on Antigravity / Jetski Harness** (upper tier: frontier Creative Director with native Active Vision, dynamic planning, parallel tasks/subagents, Workspace/GCS integration, zero-rewrite harness upgrades; lower tier: `SKILL.md` + `media_ops.py` + `omni_direct.py` + `run_vidgen_workflow.py`).
    - Right hierarchical `90s` (`3 × 30s`) swimlane diagram with real anchor/plate thumbnails fanning into 3 parallel `30s` lanes (`Shot 1 R2V` -> `Shot 2 5s Extend + MAE Trim` -> `Shot 3 5s Extend` -> `80ms xfade`) -> `0.0s` act-break `90s` Master MP4.
  - **Slide 12 (`Closed-Loop AVU Gate & <FIRST_FRAME>+<LAST_FRAME> Auto-Healing Engine`):**
    - Native-vector decision flowchart (`3×10s Clips` -> `Gemini 3.8 Flash AVU Audit [KEY FRAME A/M/B + WER + Seam MAE]` -> `Diamond Gate: Score >= 0.80 & Seam OK?` -> `YES: Lock Clip` vs. `NO: Boundary Keyframes -> Omni 1.2 Flash 10s Two-Frame Interpolation -> Re-Audit -> Monotonic Best-of-K Keep & Re-Stitch 30s Scene`).
    - Visual 3-Position Boundary Wiring diagram (**Opening Shot 1**: `Nano Banana Opening Keyframe -> Shot 2 First Frame`; **Middle Shot 2**: `Shot 1 Last Frame -> Shot 3 First Frame`; **Closing Shot 3**: `Shot 2 Last Frame -> Nano Banana Closing Hero Keyframe`).
  - **Slide 13 (`Live 90s Proof: Scene 1 Shot 3 Auto-Heal 0.70 -> 1.00 & Dual Delivery Takeaway`):**
    - Visual 4-step auto-heal flow with real thumbnails (`Extend 0.70 Flagged` -> `shot_2_last_frame.png [<FIRST_FRAME>]` + `shot_3_interp_end.png [<LAST_FRAME>]` -> `Healed Shot 1.00 ACCEPTED, seam_mae=3.79, WER=0.0`).
    - `9/9 PASSED` (`0.88–1.00`) 9-shot timeline strip + clickable GCS playback pills (`▶ 90s Master MP4`, `▶ Scene 1–3`) + Dual Delivery Pattern banner (`Skill + Antigravity/Jetski` vs. `Hosted ADK Web Studio`).
- [x] `[slides]` `[parallel]` Populate tripartite speaker notes (`[PURPOSE]`, `[VERBAL SCRIPT]`, `[TRANSITION]`, `[DATA SOURCE]`) in English and Simplified Chinese on all 3 new slides across both decks.

### 3. Execution, 4-Quadrant Active Vision Audit & URL Artifacts
- [x] `[qa]` `[parallel]` Export both updated 14-slide decks (`EN` & `ZH-CN`) to PDF via `gslides`, rasterize Slides 10–14 (`150 DPI` PNGs in `scratch/slides_audit/`), and visually inspect every slide via `read_file` to verify zero text overflow, crisp vector connectors, dark text on yellow fills, and clean `XX / 14` pagination (caught & surgically patched `MASTER` / `硬切转场` capsule width on Slide 11 and `通过` / `NB2.1 收官` pill widths on Slide 12 `ZH-CN`, re-exported and visually confirmed 100% clean).
- [x] `[delivery]` Create `.url.json` bookmark artifacts (`UserFacing: true`) for both updated Google Slides presentations and log full execution outputs in `ACTION.md`.


---

## [2026-11-08 06:09 UTC] Stage 2 (`/btw` Side Thread): Task Decomposition — Update Slide 13 & Insert Dedicated Slide 14 (`9-Shot Visual Contact Sheet`, 15 Slides Total)

### 1. High-DPI `16:9` Contact Sheet Asset Preparation (`scratch/skill_slide_assets/`)
- [x] `[assets]` `[parallel]` Extend `scratch/prepare_skill_slide_assets.py` to generate `s14_contact_sheet_90s.png` (`1440 × 810 px` exact `16:9` for `420 × 236.25 pt` placement) from `output/retail_uc3_beauty_90s/contact_sheet_90s.png` with zero cropping of the `S1.1..S3.3` timestamp badges and a crisp subtle frame border.

### 2. Bilingual Slide 13 Refresh + Dedicated Slide 14 Insertion (`scratch/update_skill_slides_15.py`)
- [x] `[slides]` Build and execute `scratch/update_skill_slides_15.py` (with mandatory `# Copyright 2026 Author:Hill YU(xcyu@)` + top-of-file module docstring) across both `EN` (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`) and `ZH-CN` (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`):
  - **Slide 13 (`v13_s13_90s_proof_{lang}`, `13 / 15`):**
    - Add dedicated amber/green highlight banner featuring the exact Scene 1 failed/auto-healed trace:
      - `EN`: `"Scene 1 (30s): Shots 1.00, 0.95, and Shot 3 auto-healed via <FIRST_FRAME> + <LAST_FRAME> interpolation (0.70 → 1.00, ACCEPTED)."`
      - `ZH-CN`: `"第一幕 Scene 1 (30s)：前两镜评分 1.00、0.95，第 3 镜经 <FIRST_FRAME> + <LAST_FRAME> 首尾双帧插值自动自愈（0.70 → 1.00, ACCEPTED）。"`
    - Render the 4-stage visual progression (`1. Shot 3 Failed 0.70` -> `2. <FIRST_FRAME> Lock` -> `3. <LAST_FRAME> Synth` -> `4. Accepted 0.70 → 1.00`) + Dual Enterprise Delivery takeaway banner.
  - **Slide 14 (`v13_s14_contact_sheet_{lang}`, `14 / 15`):**
    - Insert immediately after Slide 13 (shifting `GTM Qualification & 2-Week Pilot` to **Slide 15**).
    - **Left (`420 × 236.25 pt`):** Embed uncropped `s14_contact_sheet_90s.png` (`3×3` 9-shot storyboard `S1.1..S3.3`) + direct link button to `https://storage.cloud.google.com/vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_90s_preview/contact_sheet_90s.png`.
    - **Right (`202 pt` Telemetry & Playback Rail):** Per-scene score strips (`Scene 1`: `1.00 | 0.95 | 0.70→1.00★`, `Scene 2`: `1.00 | 1.00 | 0.95`, `Scene 3`: `0.98 | 1.00 | 0.95`) + one-click buttons for **`▶ Watch Full 90s Master`** and **`▶ Watch Scene 1–3 (30s)`**.
  - **`[parallel]`** Populate tripartite speaker notes on Slides 13–14 and dynamically update all 15 slide footers (`01 / 15` .. `15 / 15`) across both presentations.

### 3. 4-Quadrant Active Vision Audit & Bookmark Update
- [x] `[qa]` `[parallel]` Export both 15-slide presentations to PDF, rasterize Slides 11–15 (`150 DPI` PNGs), and visually inspect via `read_file` confirming crisp legibility of all 9 contact-sheet panels, exact Scene 1 callout text, zero text clipping, and `01 / 15` – `15 / 15` pagination.
- [x] `[delivery]` Update `.url.json` bookmark descriptions (`15 slides`) and log full execution outputs in `ACTION.md`.


---

## [2026-11-08 06:31 UTC] Stage 2: Decomposed TODO List — Archive Pre-Heal Failed Shots, Upload Failed vs. Healed Shot 1.3 MP4s & Attach Comparison Links on Slide 13

### 1. Harden `Skill/vidgen-long-video` Pre-Heal Archival (`[skill]` `[test]`) `[parallel]`
- [x] `[skill]` Add `original_video_path: Optional[str] = None` to `InterpolationRepairRecord` in `Skill/vidgen-long-video/scripts/run_vidgen_workflow.py` and copy `rec.video_path` to `shot_{rec.shot_index}_failed_before_heal.mp4` before overwriting `rec.video_path` when an interpolated repair is accepted.
- [x] `[test]` Extend `tests/unit/test_standalone_skill.py` to assert that `shot_2_failed_before_heal.mp4` (`original_video_path`) is preserved with the original pre-heal bytes while `shot_2.mp4` receives the healed candidate, and run `uv run --no-sync pytest tests/unit/test_standalone_skill.py -v`.

### 2. Reproduce Failed `video_extend` Shot 1.3 & Upload Side-by-Side Clips (`[pipeline]` `[storage]`) `[parallel]`
- [x] `[pipeline]` Create scratch helper `scratch/reproduce_failed_shot1_3.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + module docstring, `GOOGLE_CLOUD_PROJECT=vital-octagon-19612`, `GOOGLE_CLOUD_LOCATION=global`) to run `video_extend` on the exact `output/retail_uc3_beauty_90s/scene_1/shot_2.mp4` `5.0s` tail + `scenes_storyboard.json` Shot 1.3 prompt, trim the `5.0s` prefix via OpenCV MAE against `shot_2_last_frame.png`, audit via `gemini-3.8-flash` AVU (`evaluate_clip_quality_direct`), and save `output/retail_uc3_beauty_90s/scene_1/shot_3_failed_before_heal.mp4` (keeping `scene_1_30s.mp4` and `output_master_90s.mp4` untouched).
- [x] `[pipeline]` Extract a crisp `16:9` frame thumbnail (`s13_shot3_failed_frame.png`) from `shot_3_failed_before_heal.mp4` for Card 1 on Slide 13 and upload it to GCS.
- [x] `[storage]` `[parallel]` Upload **both** MP4s (`--cache-control="no-cache, max-age=0"`) to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_90s_preview/`:
  - `scene_1_shot_3_failed_extend.mp4` (`https://storage.cloud.google.com/vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_90s_preview/scene_1_shot_3_failed_extend.mp4`)
  - `scene_1_shot_3_healed_interp.mp4` (`https://storage.cloud.google.com/vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_90s_preview/scene_1_shot_3_healed_interp.mp4`)

### 3. Attach Comparison Links on Slide 13 (`EN` & `ZH-CN`) & Run Active Vision Audit (`[slides]` `[qa]`)
- [x] `[slides]` `[parallel]` Update **Slide 13 (`13 / 15`)** across both `EN` (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`) and `ZH-CN` (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`) decks:
  - **Card 1 (`1. SHOT 3 FAILED`):** Embed the failed `video_extend` frame thumbnail + clickable **`▶ Watch Failed Shot 3`** / **`▶ 播放失败原片 (Extend)`** button (`scene_1_shot_3_failed_extend.mp4`).
  - **Card 4 (`4. ACCEPTED`):** Add clickable **`▶ Watch Healed Shot 3 (1.00)`** / **`▶ 播放自愈成片 (1.00)`** button (`scene_1_shot_3_healed_interp.mp4`).
  - Update Slide 13 speaker notes with both clickable URLs and exact AVU score comparison.
- [x] `[qa]` Export both 15-slide decks to PDF -> `150 DPI` PNG (`Slide 13` `EN` & `ZH-CN`) and inspect via `read_file` (4-Quadrant Active Vision Audit) to confirm zero text clipping, button overflow, or card collision.
- [x] `[delivery]` Log full execution steps and test/audit outputs in `ACTION.md`.


---

## [2026-11-08 06:59 UTC] Stage 2: Decomposed TODO List — Slide 5 6-Agent ADK Architecture Infographic (`EN` & `ZH-CN`)

### 1. Native-Vector 6-Agent Infographic & Slide 5 Mutation (`[diagram]` `[slides]`) `[parallel]`
- [x] `[diagram]` Create scratch script `scratch/update_slide_05_infographic.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + module docstring) implementing `build_slide_05_infographic` with:
  - **Left Column (`X=36, W=256`):** 3 color-coded M3 phase cards explicitly highlighting all 6 agent names (`1. ScreenwriterAgent + StoryboarderAgent`, `2. PromptOptimizerAgent + HealthCheckerAgent + vidgen_orchestrator`, `3. QualityRaterAgent`).
  - **Right Column (`X=304, W=380`):** Native-vector **6-Agent ADK 2.0 Hub & Closed-Loop Flywheel Diagram**:
    - Top coordinator bar: **`① vidgen_orchestrator`** (`Root Coordinator · ADK MemoryBank · Session State`)
    - Stage 1 row (Pre-Production): **`② ScreenwriterAgent`** → **`③ StoryboarderAgent`** (`10s` shots + Hybrid A/B/C)
    - Stage 2 row (Per-Shot Loop): **`④ PromptOptimizerAgent`** → **`⑤ HealthCheckerAgent`** → **`Omni 1.2 Flash Render`** (`R2V / I2V / Extend`)
    - Stage 3 row (AVU QA & Stitch): **`⑥ QualityRaterAgent`** (`3.8 AVU · WER · Seam QA`) → `≥0.80 PASS: 80ms FFMPEG Stitch` + **`<0.80 RETRY` closed-loop vector arrow** routing feedback back up to **`④ PromptOptimizerAgent`**!
- [x] `[slides]` `[parallel]` Surgically replace `v12_s05_arch_en` and `v12_s05_arch_zh` at `insertionIndex=4` (Slide `05 / 15`) across both `EN` and `ZH-CN` decks without disturbing any other slide.

### 2. Speaker Notes & 4-Quadrant Active Vision Audit (`[notes]` `[qa]`)
- [x] `[notes]` `[parallel]` Update Slide 5 speaker notes (`PURPOSE`, `VERBAL SCRIPT`, `TRANSITION`) in both `EN` and `ZH-CN` decks naming all 6 ADK agents.
- [x] `[qa]` Export `Slide 5` (`-f 5 -l 5`) at `150 DPI` PNG (`en_s05_v3-05.png`, `zh_s05_v3-05.png`) and inspect via `read_file` to verify zero text wrapping, overlap, or arrow collision; log execution in `ACTION.md`.


---

## [2026-11-08 07:06 UTC] Stage 2: Decomposed TODO List (Run 7 — Slide 2 Full-Canvas 3-Use-Case Diagonal `/` Vertical Banners + Bottom-Wide Midnight Capsule)

### Phase 1: High-DPI Diagonal `/` Triptych Asset Generation (`[assets]`)
- [x] `[assets]` Author `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/build_slide2_triptych.py` (with `# Copyright 2026 Author:Hill YU(xcyu@)` and top-level module docstring) to render `s2_triptych_720x405.png` (`1920 × 1080 px`, zero baked-in text):
  - **`uc1_bg` (Left `/` Panel, `0..~650 px`):** Hero frame from `retail_uc1_apparel_extend_30s` (`Terracotta Alpine Down Jacket`), focal-positioned so model face & jacket chest sit cleanly in `y = 0..615 px` (`0..231 pt`) above the lower-third capsule.
  - **`uc2_bg` (Center `/` Panel, `~650..~1290 px`):** Hero frame from `retail_uc2_footwear_extend_30s` (`AeroPulse Cobalt Carbon-Plate Runner` on dark basalt pedestal with cyan rim light), centered cleanly in `y = 0..615 px` (`0..231 pt`).
  - **`uc3_bg` (Right `/` Panel, `~1290..1920 px`):** Hero frame from regenerated `retail_uc3_beauty_extend_30s` (`shot_1_last_frame.png` — spokesperson in champagne-ivory silk blazer holding the **complete capped** amber-gold serum bottle in sunlit travertine studio), scaled/positioned so both her face AND the capped serum bottle sit cleanly inside `y = 0..615 px` (`0..231 pt`) above the bottom capsule.
  - Render crisp anti-aliased `/` slanted dividers (`~7°` forward slash slope) separating `uc1_bg / uc2_bg / uc3_bg` + subtle bottom dark-navy vignette (`y = 580..1080 px`), and visually inspect `s2_triptych_720x405.png` via `read_file`.

### Phase 2: Surgical Slide 2 In-Place Rebuild (`EN` & `ZH-CN`) (`[slides]` `[parallel]`)
- [x] `[slides]` `[parallel]` Author `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/refresh_slide2_only.py` (with `# Copyright 2026 Author:Hill YU(xcyu@)` and module docstring, updating `update_decks_11_slides_v13.py` Slide 2 layout to match) to refresh **only** `v12_s02_cinema_en` and `v12_s02_cinema_zh` in place:
  - Insert full-bleed `s2_triptych_720x405.png` (`0, 0, 720, 405 pt`).
  - Add 3 subtle native top-edge category pills (`UC1 · APPAREL`, `UC2 · FOOTWEAR`, `UC3 · BEAUTY` / `案例1 · 户外服饰`, `案例2 · 运动鞋履`, `案例3 · 美妆护肤`) aligned to each vertical `/` banner.
  - Render the **Bottom-Wide Midnight Capsule** (`x = 28, y = 234, w = 664, h = 156 pt`, `#0B192C` surface, `1.2pt` `#4285F4` border, zero `solidFill.alpha`) housing:
    - Top bar: `ACT I · THE 8-SECOND WALL` badge (left) + gold `Retail Mandate: 30s–60s+ Cohesive Brand Storytelling` callout pill (right).
    - Single-line assertive headline + `#4285F4` accent rule + 3 crisp single-line colored-span bullets + `02 / 15` subtle dark-mode counter.
  - Sync tripartite speaker notes (`[PURPOSE]`, `[VERBAL SCRIPT]`, `[TRANSITION]`, `[DATA SOURCE]`) referencing all 3 retail verticals (`Apparel / Footwear / Beauty`).

### Phase 3: 4-Quadrant Active Vision Audit (`[qa]`)
- [x] `[qa]` `[parallel]` Export `en_slide-02.png` and `zh_slide-02.png` via `gslides readonly export-thumbnail`, visually inspect both via `read_file` to verify zero occlusion of all 3 SKUs/faces, crisp `/` banner edges, and zero text overflow, and log execution in `ACTION.md`.


---

## [2026-11-08 07:20 UTC] Stage 2: Decomposed TODO List — Insert Section `02` Break Slide (`11 / 16`) Introducing Skill-Based Flow (`EN` & `ZH-CN`)

### 1. Section `02` Break Slide Insertion & `XX / 16` Footer Sync (`[slides]` `[footers]` `[notes]`) `[parallel]`
- [x] `[slides]` Create scratch script `scratch/insert_skill_break_slide_11.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + module docstring) to insert `v13_s11_break_skill_en` and `v13_s11_break_skill_zh` at `insertionIndex=10` (immediately between Slide 10 and old Slide 11, idempotently deleting `v13_s11_break_skill_{lang}` first if re-run) on a `#1E8E3E` Google Green background matching Slide 4's exact `X/Y/W/H` geometry (`02` hero numeral + `24pt` 3-line headline + `10.6pt` subtitle + 4 `#FFFFFF` `ROUND_RECTANGLE` pillar cards `01..04`).
- [x] `[footers]` `[parallel]` Dynamically update all slide page counter footers across both `EN` and `ZH-CN` decks from `XX / 15` to `01 / 16` .. `16 / 16`.
- [x] `[notes]` `[parallel]` Populate tripartite speaker notes (`PURPOSE`, `VERBAL SCRIPT`, `TRANSITION`) on `v13_s11_break_skill_en` and `v13_s11_break_skill_zh`.

### 2. 4-Quadrant Active Vision Audit & Bookmark Sync (`[qa]` `[delivery]`)
- [x] `[qa]` Export `Slide 11` (`-f 11 -l 11`) at `150 DPI` PNG (`en_s11_break-11.png`, `zh_s11_break-11.png`) and inspect via `read_file` alongside Slide 4 (`01`) to verify exact alignment, contrast, and zero text wrapping/overflow.
- [x] `[delivery]` Update `.url.json` bookmark descriptions (`16 slides`) and log full execution outputs in `ACTION.md`.


---

## [2026-11-08 07:47 UTC] Stage 2: Decomposed TODO List — Slide 16 Pilot Removal & Full-Deck Bilingual Audit Polish (`EN` & `ZH-CN`, `16` Slides)

### 1. Slide 16 Pilot Removal & Dual Enterprise Delivery Bar (`[slides]` `[design]` `[notes]`) `[parallel]`
- [x] `[slides]` Delete the `2-Week Retail Pilot Path` / `推荐两周零售客户 POC 落地路径` shapes (`v14_shp_{lang}_0218`, `v14_txt_{lang}_0219`, `v14_txt_{lang}_0220`) on `v12_s11_gtm_en` (`EN`) and `v12_s11_gtm_zh` (`ZH-CN`).
- [x] `[design]` `[parallel]` Update Slide 16's eyebrow (`GTM EXECUTION PLAYBOOK · BUYER QUALIFICATION & DUAL DELIVERY ARCHITECTURE`), single-line headline (`Dual ADK Studio & Portable Skill delivery powers enterprise retail video`), and unified footer (`ADK 2.0 & Portable Skill + Omni 1.2 + 3.8 AVU`).
- [x] `[design]` `[parallel]` Insert the **Dual Enterprise Delivery Summary Bar** (`Y=311..373 pt`, crisp `1 pt` `RECTANGLE` container with `4.5 pt` `#1A73E8` left accent bar):
  - **Track 1 — Hosted ADK 2.0 Web Studio (`Cloud Run / Agent Runtime`):** Self-serve browser portal for merchandisers generating standard `30s` (`3×10s`) SKU spots in ~5m.
  - **Track 2 — Portable Zero-ADK Skill (`Antigravity / Jetski Harness`):** Drop-in `.agents/skills/` workflow for creative teams producing bespoke `90s+` (`3×30s`) auto-healed campaigns in ~17m.

### 2. Narrative, Metric & Speaker-Note Consistency (`[copy]` `[notes]`) `[parallel]`
- [x] `[copy]` `[parallel]` Update **Slide 1 (`Cover`)**, **Slide 2 (`8-Second Wall`)**, and **Slide 10 (`Hub`)** across `EN` & `ZH-CN`:
  - **Slide 1:** Expand subtitle to cover both `ADK 2.0 Studio (9 × 30s Ads)` and `Portable Skill + Antigravity/Jetski (90s Auto-Healed Master)`, and update right-rail header (`30s–90s+ RETAIL AD ARC` / Card 4 `SKILL + 90s AUTO-HEAL`).
  - **Slides 2 & 10:** Upgrade `30s–60s` / `30–60 秒` narrative scope references to **`30s–90s+`** / **`30–90 秒+`**.
- [x] `[copy]` `[parallel]` Clarify QA metrics on **Slide 7 (`Mode A`)** and **Slide 8 (`Mode B`)** (`EN` & `ZH-CN`) using verified `all_9_omni12_showcase_summary.json` scores so they align cleanly with Slide 13's `< 0.80` gate:
  - **Slide 7 (`UC2 Footwear`):** Update raw `0.67` bullet to `0.95 SKU lock · WER 0.0` / `0.95 鞋型锁定 · WER 0.0`.
  - **Slide 8 (`Mode B` Cards 1–3):** Surface verified `Seam 0.87 PASS · WER 0.0`, `S1 1.00 · WER 0.0 (3-set)`, and `S1 1.00 · WER 0.0 (0% white)` (and matching single-line `ZH-CN` bullets).
- [x] `[notes]` `[parallel]` Fix stale speaker-note `[TRANSITION]` slide numbers and remove `2-week pilot / 两周 POC` language across **Slides 1, 10, 14, 15, 16** (`EN` & `ZH-CN`), including syncing `ZH` Slide 14 `[VERBAL SCRIPT]` with the exact unlabeled-bottle root cause (`瓶身标签丢失`).

### 3. Visual & Typographic Polish (`[design]` `[slides]`) `[parallel]`
- [x] `[copy]` `[parallel]` Tighten `EN` headlines on **Slides 3, 6, 7, 8, 9, 10, 16** onto crisp single lines (`14.0–14.2 pt`, zero 2-line orphan words).
- [x] `[design]` `[parallel]` Convert tall outer `ROUND_RECTANGLE` wrapper containers on **Slides 7, 8, 9, 10, 12, and 15** (`EN` & `ZH-CN`) into crisp `1 pt`-bordered `RECTANGLE` frames (`SEND_TO_BACK` with flush `4 pt` top accent strips on Slides 7–9), eliminating curved-corner grazing on inner headers and bottom CTA buttons.

### 4. Execution, 4-Quadrant Active Vision Audit & Bookmark Sync (`[qa]` `[delivery]`)
- [x] `[slides]` Author and run `/usr/local/google/home/xcyu/.gemini/jetski/brain/0ba02227-f740-47d8-9252-48853f0a7e88/scratch/polish_full_deck_16.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + top-of-file module docstring) applying all updates atomically per deck while preserving all 27 clickable video/image/Studio slide links (`30` total links incl. speaker notes).
- [x] `[qa]` `[parallel]` Export both updated 16-slide presentations to PDF -> `150 DPI` PNGs (`scratch/full_audit_v2/`) and inspect every modified slide (`1, 2, 3, 6, 7, 8, 9, 10, 12, 14, 15, 16` across `EN` & `ZH-CN`) via `read_file` to verify zero text wrapping, overlap, or corner grazing.
- [x] `[delivery]` Update `.url.json` bookmark artifacts (`16 Slides`) and log full execution outputs in `ACTION.md`.


---

## [2026-11-08 08:40 UTC] Stage 2: Decomposed TODO List — Second `90s` Skill Example (`Hook → SKU Hero → Lifestyle Proof → CTA`) + New Slide 16 (`17` Slides Total)

### 1. Architectural Scene Plates & 4-Act Storyboard Spec (`[assets]` `[storyboard]`) `[parallel]`
- [x] `[assets]` Create `output/retail_uc3_beauty_arc_90s/refs/` and copy canonical `#FFFFFF` anchor `output/retail_uc3_beauty_90s/refs/uc3_beauty_anchor.png`.
- [x] `[assets]` `[parallel]` Generate 4 people-free `16:9` architectural reference plates in parallel via `uv run Skill/vidgen-long-video/scripts/omni_direct.py generate-image` (`gemini-nano-banana-2.1`):
  - `act1_urban_vanity_ref.png` (`Hook`: twilight sleek walnut-and-slate penthouse vanity overlooking cool city dusk lights)
  - `act2_alabaster_pedestal_ref.png` (`SKU Hero`: warm backlit alabaster apothecary counter with golden light beams)
  - `act3_daylight_gallery_ref.png` (`Lifestyle Proof`: airy mid-morning sunlit glass-and-oak design studio lounge)
  - `act4_flagship_plinth_ref.png` (`CTA`: golden-hour champagne-travertine retail flagship display plinth)
- [x] `[qa]` Visually inspect all 4 generated plates via `read_file` to verify zero unwanted people/text overlays and clean architectural composition.
- [x] `[storyboard]` Write `output/retail_uc3_beauty_arc_90s/scenes_storyboard.json` defining the asymmetric 4-Act `90s` arc (`20s Hook [2×10s] → 20s SKU Hero [2×10s] → 30s Lifestyle Proof [3×10s] → 20s CTA [2×10s]` = `9 × 10s` shots, `<= 10` words/shot spoken copy, capped-bottle continuity guardrails, and `opening_keyframe_prompt` / `closing_keyframe_prompt` anchors).

### 2. Standalone `90s` Skill Execution, AVU Audit & Auto-Healing (`[backend]` `[qa]`)
- [x] `[backend]` Execute `uv run Skill/vidgen-long-video/scripts/run_vidgen_workflow.py --scenes-json output/retail_uc3_beauty_arc_90s/scenes_storyboard.json --max-parallel-scenes 2 --quality-threshold 0.80 --output-dir output/retail_uc3_beauty_arc_90s`.
- [x] `[qa]` Inspect `output/retail_uc3_beauty_arc_90s/run_manifest.json` to verify all `9/9` shots pass `gemini-3.8-flash` AVU (`>= 0.80`, `WER = 0.0`, `avu_tool_use_tokens > 0`), check any `<FIRST_FRAME>+<LAST_FRAME>` interpolation repairs, and confirm `output_master_90s.mp4` duration & Master Seam Critic score.

### 3. Act-Labeled `3×3` Contact Sheet & GCS Showcase Upload (`[assets]` `[gcs]`) `[parallel]`
- [x] `[assets]` Author `/usr/local/google/home/xcyu/.gemini/jetski/brain/0ba02227-f740-47d8-9252-48853f0a7e88/scratch/upload_90s_arc_preview.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + module docstring) to extract a `3×3` 9-Shot Visual Contact Sheet (`contact_sheet_arc_90s.png`) labeled by Act & Shot (`H1.1 Hook`, `H1.2 Hook`, `S2.1 Hero`, `S2.2 Hero`, `L3.1 Proof`, `L3.2 Proof`, `L3.3 Proof`, `C4.1 CTA`, `C4.2 CTA`) and inspect via `read_file`.
- [x] `[gcs]` Upload `output_master_90s.mp4`, all 4 act MP4s (`act_1_hook_20s.mp4`, `act_2_sku_hero_20s.mp4`, `act_3_lifestyle_proof_30s.mp4`, `act_4_cta_20s.mp4`), `contact_sheet_arc_90s.png`, `run_manifest.json`, `scenes_storyboard.json`, and `refs/*.png` to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_arc_90s_preview/` (`cache_control = "no-cache, max-age=0"`).

### 4. Insert Dedicated Slide 16 (`16 / 17`) in EN & ZH-CN Decks + 4-Quadrant Vision Audit (`[slides]` `[qa]` `[delivery]`) `[parallel]`
- [x] `[slides]` Author `/usr/local/google/home/xcyu/.gemini/jetski/brain/0ba02227-f740-47d8-9252-48853f0a7e88/scratch/insert_slide_16_arc_90s.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + module docstring) fetching fresh live deck JSON and inserting `v17_s16_arc_90s_en` & `v17_s16_arc_90s_zh` right after Slide 15 (`16 / 17`, shifting GTM Playbook to `17 / 17`):
  - Left panel (`1pt` `RECTANGLE`): embedded `contact_sheet_arc_90s.png` + clickable high-res link button.
  - Right panel (`1pt` `RECTANGLE`): 4-Act Conversion Hub (`Act 1 Hook · 20s`, `Act 2 SKU Hero · 20s`, `Act 3 Lifestyle Proof · 30s`, `Act 4 CTA · 20s`) with live AVU scores, per-act clickable MP4 pills, and full **`90s` Conversion Master MP4** CTA card.
  - Sync all `01 / 17 .. 17 / 17` page counters, Cover/Section `02` references (`2 × 90s` Skill Masters), and tripartite speaker notes (`Slides 15, 16, 17`).
- [x] `[qa]` `[parallel]` Export updated PDFs -> `150 DPI` PNGs (`scratch/arc_90s_audit/`) and inspect `Slide 1, 11, 15, 16, 17` across both `EN` and `ZH-CN` via `read_file` to verify zero overlap, wrapping, or broken links.
- [x] `[delivery]` Update `.url.json` bookmark artifacts (`17 Slides`) and log timestamped execution results in `ACTION.md`.


---

## [2026-11-08 08:42 UTC] Stage 2: Decomposed TODO List (Run 8 — Update Mode B `i2v_chaining` Prompts Only to Match Mode C's Single-Take Scenes & Refresh Slide 8)

### Phase 1: Single-Take Mode B Prompt Alignment & Fresh 3 × 30s (`9`-Shot) Generation (`[prompts]` `[pipeline]`)
- [x] `[prompts]` Author `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/regenerate_mode_b_single_take.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + top-level module docstring, **zero** edits to `app/`, `src/`, or `Skill/`) updating **only** the 3 Mode B (`mode="i2v_chaining"`) showcase storyboards & spoken transcripts to match Mode C's exact continuous single-location scenes (no hard transitions):
  - **`retail_uc1_apparel_lookbook_30s` (`UC1 Apparel`):** Boutique café exit onto misty winter sidewalk (`Shot 1` `#FFFFFF` R2V) → backward tracking snowfall walk (`Shot 2` `<FIRST_FRAME>` I2V) → smooth arc to hero medium close-up beneath falling snow (`Shot 3` `<FIRST_FRAME>` I2V), spoken lines: `"Engineered for the city street. Crafted to shield against freezing winter wind. Featherlight warmth for every cold winter journey."`
  - **`retail_uc2_footwear_hero_30s` (`UC2 Footwear`):** Standalone cobalt carbon-plate shoe on dark basalt pedestal orbital (`Shot 1` `#FFFFFF` R2V) → continuous low-angle orbital macro glide in cool mist (`Shot 2` `<FIRST_FRAME>` I2V) → warm golden rim-light sweep into hero profile lockup (`Shot 3` `<FIRST_FRAME>` I2V), spoken lines: `"Built from carbon fiber precision. Sculpted carbon geometry channels pure forward momentum. Responsive cushion engineered for effortless speed."`
  - **`retail_uc3_beauty_regional_30s` (`UC3 Beauty`):** Medium waist-up sunlit travertine studio shot releasing one golden droplet & seating the metallic gold collar + white bulb dropper cap closed onto the bottle (`Shot 1` `#FFFFFF` R2V) → slow single-take dolly-in holding & tilting the closed serum bottle in morning sunbeams (`Shot 2` `<FIRST_FRAME>` I2V) → smooth orbital close-up setting the complete capped serum bottle onto the travertine counter beside white orchids (`Shot 3` `<FIRST_FRAME>` I2V), spoken lines: `"One golden drop awakens pure radiance. Pure botanical moisture melts smoothly into skin. Warm morning light reveals a natural glow."`
- [x] `[pipeline]` `[parallel]` Execute all 3 Mode B 30s (`3 × 10s`, `720p`) campaigns fresh from scratch (`Shot 1` R2V + `Shots 2–3` `<FIRST_FRAME>` I2V) on `gemini-omni-1.2-flash` + `gemini-3.8-flash` AVU (`MediaProcessing.AGENTIC`) + `evaluate_stitched_master()`, saving updated telemetry to `pinned_retail_i2v_chaining_summary.json` and `all_9_omni12_showcase_summary.json`.

### Phase 2: Visual Continuity Audit & GCS Showcase Re-Pinning (`[qa]` `[storage]`)
- [x] `[qa]` Build 15-frame visual contact sheets for the 3 regenerated Mode B runs and inspect via `read_file` to verify zero location cuts, `WER = 0.0`, clean `<FIRST_FRAME>` boundary MAE (`Shot 1→2` & `Shot 2→3`), and intact UC3 closed dropper cap across all 3 shots.
- [x] `[storage]` `[parallel]` Re-pin all 9 canonical 30s runs in `#1..#9` deterministic order (`Mode C #1–#3`, updated `Mode B #4–#6`, `Mode A #7–#9`) to `gs://vital-octagon-19612-vidgen-showcase/showcase/{run_id}/` + `output/saved_runs.json` (no Cloud Run container rebuild/redeployment).

### Phase 3: Mode B `2×2` Composites & Surgical Slide 8 Refresh (`[assets]` `[slides]` `[qa]`)
- [x] `[assets]` `[parallel]` Rebuild Mode B `2×2` bilingual composite strips (`uc1_strip_{en,zh}.png`, `uc2_strip_{en,zh}.png`, `uc3_strip_{en,zh}.png`) via `build_all_composites_v13.py` and upload to `gs://vital-octagon-19612-vidgen-showcase/showcase/composites/`.
- [x] `[slides]` `[parallel]` Author and run `scratch/refresh_slide8_only.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + module docstring) to surgically refresh **only** `v12_s08_i2v_en` and `v12_s08_i2v_zh` in place across both `EN` and `ZH-CN` decks (preserving dynamic total slide count, `1pt` `RECTANGLE` outer card frames, updated single-take arcs & live metrics matching Mode C's scenes, and Mode B vs. Mode C comparison speaker notes).
- [x] `[qa]` `[parallel]` Export `en_slide-08.png` and `zh_slide-08.png` via `gslides readonly export-thumbnail`, inspect via `read_file` to verify zero text wrapping/clipping or frame grazing, and log full execution telemetry in `ACTION.md`.


---

## [2026-11-08 11:09 UTC] Stage 2: Decomposed TODO List (Run 9 — Replace `8s` Single-Clip Limit with `15s` Across Decks & Refocus Slide 8 Purely on Mode B)

### Phase 1: Sync Source Copy & Author Surgical Update Script (`[copy]` `[slides]`)
- [x] `[copy]` Update `s1`, `s2`, and `s8` (`EN` & `ZH-CN`) in `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/update_decks_11_slides_v13.py` so the canonical copy definitions match `15s` (`15-Second` / `15 秒`) and pure Mode B (`i2v_chaining`) descriptions without Mode C comparison.
- [x] `[slides]` Author `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/update_15s_and_slide8_mode_b.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + top-level module docstring) to surgically mutate **only** the targeted text elements, speaker notes, and presentation file titles across `EN` (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`) and `ZH-CN` (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`) while preserving 100% of existing styling, layouts, images, and links:
  - **Presentation Titles (`gdrive mutate rename`):**
    - `EN`: `'vidgen-omni: Scaling Retail Video Beyond the 15-Second Clip (GTM Showcase)'`
    - `ZH-CN`: `'vidgen-omni：突破 15 秒瓶颈，打造零售与电商长视频生成方案（GTM 实战演示）'`
  - **Slide 1 (`Cover` — `v12_s01_cover_{en,zh}`):**
    - `v14_txt_en_0008`: `'Scaling Retail Video Beyond\nthe 15-Second Clip'` + `EN` speaker notes (`15-second wall` / `15 seconds`).
    - `v14_txt_zh_0008`: `'突破 15 秒短视频瓶颈\n规模化生成零售商业长视频'`.
  - **Slide 2 (`Act I` — `v12_s02_cinema_{en,zh}`):**
    - `v14_txt_en_6905`: `'ACT I  ·  THE 15-SECOND WALL'` + `v14_txt_en_6907`: `'Retailers lose campaign conversion when generative AI stops at isolated 15-second clips'` + `EN` speaker notes (`up to 15s on Gemini Omni 1.2 Flash` / `15-second AI clips`).
    - `v14_txt_zh_9705`: `'第一幕  ·  零售营销“15 秒高墙”'` + `v14_txt_zh_9707`: `'当生成式 AI 止步于孤立的 15 秒片段，零售品牌将错失全漏斗广告转化'` + `ZH-CN` speaker notes (`单次生成上限 15 秒` / `孤立的 15 秒 AI 短片`).
  - **Slide 8 (`Mode B` — `v12_s08_i2v_{en,zh}`, Zero Mode C Mention):**
    - `EN` headline (`v14_txt_en_109802`): `'Mode B chains Shot 1 native R2V into sequential <FIRST_FRAME> I2V for pixel-locked 30s ads'`
    - `EN` banner (`v14_txt_en_109821`): `"Mode B (gemini-omni-1.2-flash, mode='i2v_chaining'): Shot 1 native #FFFFFF R2V + Shots 2–3 terminal PNG (<FIRST_FRAME>) I2V + 80ms xfade."`
    - `ZH-CN` eyebrow (`v14_txt_zh_114601`): `'30 秒实测零售样片展示  ·  模式 B：首镜原生白底 R2V + 尾帧 <FIRST_FRAME> I2V 顺序接力'`
    - `ZH-CN` headline (`v14_txt_zh_114602`): `'模式 B 以首镜原生白底 R2V 入景，逐镜提取静态末帧驱动 <FIRST_FRAME> I2V 像素级接力'`
    - `ZH-CN` banner (`v14_txt_zh_114621`): `"模式 B（gemini-omni-1.2-flash, mode='i2v_chaining'）：首镜原生白底 R2V + 第 2–3 镜提取静态末帧 PNG（<FIRST_FRAME>）顺序接力 + 80ms 叠化。"`
    - `EN` & `ZH-CN` Slide 8 speaker notes: Explain Mode B's mechanics and 3 showcase campaigns standalone without referencing similarity to Mode C.

### Phase 2: Execute Updates, Full-Deck `8s` Sweep & 4-Quadrant Active Vision Audit (`[slides]` `[qa]` `[delivery]`) `[parallel]`
- [x] `[slides]` `[parallel]` Execute `update_15s_and_slide8_mode_b.py` across both `EN` and `ZH-CN` 17-slide decks and run an automated full-deck regex assertion across all 17 slides + speaker notes + titles confirming **zero** residual `8s` / `8-second` / `eight-second` / `8 秒` hits and **zero** Mode C mentions on Slide 8.
- [x] `[qa]` `[parallel]` Export PNG thumbnails for `Slides 1, 2, 8` (`en_slide-01.png`, `en_slide-02.png`, `en_slide-08.png`, `zh_slide-01.png`, `zh_slide-02.png`, `zh_slide-08.png`) via `gslides readonly export-thumbnail` and inspect all 6 PNGs via `read_file` to verify crisp single-line headlines, preserved font/color styling, and zero clipping/wrapping.
- [x] `[delivery]` Update `.url.json` bookmark artifacts and log timestamped execution results in `ACTION.md`.


---

## [2026-11-08 11:57 UTC] Stage 2: Decomposed TODO List (Run 10 — Add Author Badge with Round Moma Profile Photo on Cover Slide 1 in `EN` & `ZH-CN`)

### Phase 1: Circular Moma Avatar Asset & Surgical Slide 1 Script (`[assets]` `[copy]` `[slides]`)
- [x] `[assets]` Render `xcyu_moma_round_512.png` (`512×512` RGBA PNG) from `scratch/moma_profile/xcyu_preferred.jpg` using Pillow (`uv run --with pillow`) with a `4x` (`2048×2048` $\rightarrow$ `512×512` Lanczos) supersampled circular alpha mask, crisp `#FFFFFF` inner hairline ring, and subtle `#4285F4` Google Blue outer ring; visually verify `xcyu_moma_round_512.png` via `read_file`.
- [x] `[copy]` `[parallel]` Sync Cover Slide 1 (`s1`) layout and author credit constants in `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/update_decks_11_slides_v13.py`.
- [x] `[slides]` Author `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/add_author_moma_badge.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + top-level docstring) to idempotently update **only** `v12_s01_cover_en` (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`) and `v12_s01_cover_zh` (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`):
  - Insert `xcyu_moma_round_512.png` at `X=48, Y=277, W=40, H=40` (`1:1` aspect ratio).
  - Add styled two-line author credit block at `X=96, Y=277, W=388, H=40`:
    - **EN:** `Hill Yu  ·  xcyu@google.com` (bold `#202124` / `#1967D2`) / `Practice Specialist, AI Vision  |  Google Cloud` (`#5F6368`).
    - **ZH-CN:** `Hill Yu  ·  xcyu@google.com` (bold `#202124` / `#1967D2`) / `Practice Specialist, AI Vision（AI 视觉专家） |  Google Cloud` (`#5F6368`).
  - Reposition existing `Audience` pill (`v14_txt_{lang}_0010`) cleanly to `X=48, Y=330, W=436, H=36` (`bottom = 366`, aligning exact bottom baseline with the 4th right-hand arc card at `Y = 366`).

### Phase 2: Live Slides Execution & 4-Quadrant Active Vision Audit (`[slides]` `[qa]` `[delivery]`) `[parallel]`
- [x] `[slides]` `[parallel]` Execute `uv run --with pillow python .../add_author_moma_badge.py` across both `EN` and `ZH-CN` decks (`task-8529`, exit code `0`).
- [x] `[qa]` `[parallel]` Export `en_slide-01.png` and `zh_slide-01.png` via `/google/bin/releases/gemini-agents-gslides/gslides readonly export-thumbnail` and visually inspect both PNGs via `read_file` to verify crisp circular anti-aliasing, balanced vertical spacing, and zero clipping/overlap.
- [x] `[delivery]` Refresh `.url.json` deliverable bookmarks and log full execution telemetry in `ACTION.md`.

---

## [2026-11-08 12:04 UTC] Stage 2: Decomposed TODO List — Remake Act 2 (`SKU Hero`, `20s`) Using `.agents/skills/vidgen-long-video` Directly (Zero Skill Code Edits)

### 1. Standalone `#FFFFFF` Bottle-Only Anchor via Skill `generate-image` CLI (`[assets]` `[qa]`)
- [x] `[assets]` Invoke the existing skill CLI as-is (`SKILL_DIR=".agents/skills/vidgen-long-video"`, **zero** edits to `Skill/vidgen-long-video/`):
  `uv run "$SKILL_DIR/scripts/omni_direct.py" generate-image --reference output/retail_uc3_beauty_arc_90s/refs/uc3_beauty_anchor.png --aspect-ratio 16:9 --output output/retail_uc3_beauty_arc_90s/refs/uc3_bottle_only_anchor.png --prompt "..."`
  to isolate the exact closed amber-gold `AURORA` serum dropper bottle (cylindrical amber glass, brushed-gold collar, white rubber bulb cap, and label typography) upright on pure `#FFFFFF` with **zero humans, hands, or shadows**.
- [x] `[qa]` Visually inspect `output/retail_uc3_beauty_arc_90s/refs/uc3_bottle_only_anchor.png` via `read_file` to confirm 100% bottle/label accuracy and zero human presence.

### 2. Update `scenes_storyboard.json` & Re-Render Act 2 via Skill `run_vidgen_workflow.py --resume` (`[storyboard]` `[skill]` `[qa]`)
- [x] `[storyboard]` Update `act_2_sku_hero` in `output/retail_uc3_beauty_arc_90s/scenes_storyboard.json`:
  - Set `reference_paths` to `["output/retail_uc3_beauty_arc_90s/refs/uc3_bottle_only_anchor.png", "output/retail_uc3_beauty_arc_90s/refs/act2_alabaster_pedestal_ref.png"]` and update `opening_keyframe_prompt` / `closing_keyframe_prompt` to strictly human-free bottle macro compositions.
  - **Shot 2.1 (`20–30s`, R2V — Unique Botanical Formula Macro):** Standalone closed amber-gold `AURORA` dropper serum bottle resting on the warm backlit alabaster stone counter bathed in diagonal golden light beams beside botanical glassware and golden oil droplets; strictly product-only with zero human presence or hands, accompanied by off-camera female studio voiceover: `"Cold-pressed golden botanicals lock pure bio-active potency inside every drop."`
  - **Shot 2.2 (`30–40s`, `video_extend` — Deep-Absorbing Effectiveness Macro):** Seamless single-take orbital macro push-in around the illuminated closed `AURORA` serum bottle on the backlit alabaster counter as golden light beams refract through the micro-fine elixir; strictly product-only with zero human presence or hands, accompanied by off-camera female studio voiceover: `"Micro-fine lipids absorb deeply to visibly plump and restore radiance."`
- [x] `[skill]` Non-destructively archive `output/retail_uc3_beauty_arc_90s/act_2_sku_hero` -> `act_2_sku_hero_prev_spokesperson` and `act_2_sku_hero_20s.mp4` -> `act_2_sku_hero_20s_prev_spokesperson.mp4`, then invoke the skill orchestrator directly:
  `uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" --scenes-json output/retail_uc3_beauty_arc_90s/scenes_storyboard.json --resume --max-parallel-scenes 2 --quality-threshold 0.80 --output-dir output/retail_uc3_beauty_arc_90s`
  (reusing Acts 1, 3, and 4, rendering & AVU-auditing Act 2 with `<FIRST_FRAME>+<LAST_FRAME>` auto-heal if needed, and stitching `output_master_90s.mp4`).
- [x] `[qa]` Inspect `output/retail_uc3_beauty_arc_90s/run_manifest.json` and Act 2 boundary frames (`shot_1_first_frame.png`, `shot_1_last_frame.png`, `shot_2_last_frame.png`) via `read_file` to verify `score >= 0.80`, `WER = 0.0`, exact `AURORA` bottle lock, and **zero** human presence.

### 3. Rebuild `3×3` Contact Sheet & Sync Updated Artifacts to GCS (`[assets]` `[gcs]`) `[parallel]`
- [x] `[assets]` Rebuild `output/retail_uc3_beauty_arc_90s/contact_sheet_arc_90s.png` (`upload_90s_arc_preview.py`) and inspect via `read_file` to confirm `S2.1 SKU Hero` and `S2.2 SKU Hero` are crisp, human-free bottle macro shots alongside spokesperson Acts 1, 3, and 4.
- [x] `[gcs]` Upload updated `output_master_90s.mp4`, `act_2_sku_hero_20s.mp4`, `contact_sheet_arc_90s.png`, `uc3_bottle_only_anchor.png`, and `run_manifest.json` to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_arc_90s_preview/` (`cache_control = "no-cache, max-age=0"`).

### 4. Surgical Slide 16 In-Place Refresh (`EN` & `ZH-CN`) & Active Vision Audit (`[slides]` `[qa]` `[delivery]`) `[parallel]`
- [x] `[slides]` Author and run `scratch/refresh_slide_16_arc_only.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + module docstring) to refresh **only Slide 16 (`v17_s16_arc_90s_en` & `v17_s16_arc_90s_zh`)** in place across both 17-slide decks (touching **zero** elements on Slides 1–15 & 17).
- [x] `[qa]` `[parallel]` Export `150 DPI` `en-16.png` & `zh-16.png`, visually verify via `read_file`, and log timestamped CLI + audit outputs in `ACTION.md`.


---

## [2026-11-09 01:46 UTC] Stage 2: Decomposed TODO List (Run 11 — Insert Slide `17 / 18` on Omni 1.2 Draft Mode: `360p Draft -> Agentic Loop -> Standalone Upscale`)

### Phase 1: Author Surgical Slide 17 Insertion & `XX / 18` Footer Sync Script (`[diagram]` `[slides]` `[footers]` `[notes]`)
- [x] `[diagram]` `[slides]` Author `/usr/local/google/home/xcyu/.gemini/jetski/brain/dd460239-badd-49d0-b6be-d6d51eca5766/scratch/insert_slide_17_draft_upscale.py` (`# Copyright 2026 Author:Hill YU(xcyu@)` + top-level docstring) using Slide 5's exact `Split 40/60` pixel coordinates (`#FFFFFF` canvas, single-line assertive headline, `17 / 18` footer):
  - **Left Column (`X=36, W=254, Y=68..338` — 3 M3 Phase Cards `#F7F2E8` with `5pt` color accent strips):**
    1. **`1. Fast 360p Draft ($0.02/s · 3.5×–5× Cheaper)` (`#4285F4` Blue):** Render `10s–15s` Mode A/B/C or interpolation candidates at `resolution="360p"` (`24fps`, full lip-synced VO & SFX) — `\$0.20` per `10s` draft vs. `\$0.70` (`720p`) / `\$1.00` (`1080p`) / `\$2.10` (`4K`).
    2. **`2. Closed-Loop 3.8 AVU Agentic Gate (@ 360p)` (`#B06000` Amber):** `QualityRaterAgent` (`MediaProcessing.AGENTIC` + `WER ≤ 0.35` + Seam MAE) audits every `360p` take; `< 0.80` triggers Best-of-$K$ prompt rewrite or `<FIRST_FRAME>+<LAST_FRAME>` auto-heal at `\$0.20/take`.
    3. **`3. Zero-Reasoning Standalone Upscale` (`#34A853` Green):** Promote **only** `≥ 0.80` winners via `task="upscale"` (`previous_interaction_id` / `gs://` URI, `total_input_tokens: 0`): `360p → 720p/1080p` or `720p → 1080p/4K` with 100% locked framing & audio before `80ms` stitch.
  - **Right Column (`X=300, W=384, Y=68..338` — `1pt` `RECTANGLE` Native-Vector Flowchart):**
    - **Row 1 (`Y=94..132`):** Top Dual-Track Input Hub (`ADK 2.0 Web Studio (30s) & Portable Skill (90s+) · Storyboard & #FFFFFF Anchors`).
    - **Row 2 (`Y=146..192`):** `① Draft Render (Omni 1.2)` (`resolution="360p"` · `\$0.02/s`) $\rightarrow$ `② Gemini 3.8 Flash AVU` (`AGENTIC` · `WER` · `Seam MAE`).
    - **Feedback Loop (`Y=192..262`):** `< 0.80` dashed `#C5221F` feedback retry path through `↺ Retry / Auto-Heal @ 360p ($0.20/clip · Discard Cheaply)` back into `① Draft Render`, vs. `≥ 0.80 PASS` green path downward.
    - **Row 3 (`Y=212..262`):** `③ Standalone Upscale` (`task="upscale"` · `0 Input Tokens` · `360p→720p/1080p` | `720p→4K`).
    - **Row 4 (`Y=278..328`):** `④ 80ms Master Stitch` (`1080p / 4K Broadcast Master`) + side-by-side **Unit Economics Callout Box** (`30s Spot × K=3 Takes`: Naive `1080p` `\$9.00` $\rightarrow$ Draft+Upscale `\$4.80`, **`5×` less retry waste / `~50%–65%` savings**).
  - **Bottom Banner (`X=36, Y=347, W=648, H=25`):** Unified takeaway pill summarizing `Draft Fast at $0.02/s (360p)  →  Iterate & Self-Heal with 3.8 AVU  →  Pay to Upscale Only Winning Takes (task="upscale")`.
- [x] `[footers]` `[notes]` `[parallel]` Insert `v18_s17_draft_upscale_en` and `v18_s17_draft_upscale_zh` at `insertionIndex = 16` (`Slide 17 / 18`, shifting `v12_s11_gtm_{en,zh}` to `Slide 18 / 18`), dynamically update all `XX / 17` slide footers to `XX / 18` (`02 / 18 .. 18 / 18`, updating `17 / 17` on GTM to `18 / 18`), update Slide 16's `[TRANSITION]` note to reference Slide 17, and populate tripartite speaker notes on Slide 17.

### Phase 2: Execute Across Both Decks & Run 4-Quadrant Active Vision Audit (`[slides]` `[qa]` `[delivery]`) `[parallel]`
- [x] `[slides]` `[parallel]` Execute `insert_slide_17_draft_upscale.py` idempotently across both `EN` (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`) and `ZH-CN` (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`) presentations and verify total slide count = `18` and zero stale `/ 17` footers.
- [x] `[qa]` `[parallel]` Export PNG thumbnails (`en_slide-17.png`, `en_slide-18.png`, `zh_slide-17.png`, `zh_slide-18.png`) via `gslides readonly export-thumbnail` and inspect via `read_file` to verify single-line headlines, crisp arrows/boxes, and zero text wrapping or clipping across all 4 quadrants.
- [x] `[delivery]` Refresh `.url.json` deliverable bookmarks and log timestamped execution results in `ACTION.md`.


---

## [2026-11-09 01:56 UTC] Stage 2: Decomposed TODO List (Run 12 `/btw` — Upgrade `vidgen-long-video` Skill with Draft Mode & Benchmark Speed on the 4-Act `90s` Beauty Commercial)

### Phase 1: Upgrade Standalone Skill (`Skill/vidgen-long-video`) & Unit Tests (`[skill]` `[docs]` `[test]`)
- [ ] `[skill]` **Add Standalone Video Upscaling to `Skill/vidgen-long-video/scripts/omni_direct.py`:**
  - Implement `SUPPORTED_UPSCALE_TRANSITIONS = {"360p": ("720p", "1080p"), "720p": ("1080p", "4k")}` validation helper and `upscale_omni_clip_direct(video_bytes_or_b64, target_resolution="720p", source_resolution="360p", client=None)` invoking `interactions.create(model=DirectConfig.VIDEO_GEN_MODEL, input=[{"type": "video", "data": video_b64, "mime_type": "video/mp4"}], generation_config={"video_config": {"task": "upscale"}}, response_format={"type": "video", "resolution": target_resolution})`.
  - Extract interaction usage metadata (`total_input_tokens`, `total_output_tokens`, `upscale_sec`) alongside the returned MP4 bytes, and add an `upscale-clip` CLI subcommand (`--video`, `--output`, `--target-resolution`, `--source-resolution`) to `omni_direct.py`.
- [ ] `[skill]` **Add `--draft-mode` (`Draft -> Agentic Loop -> Upscale`) & Stage Timing Telemetry to `Skill/vidgen-long-video/scripts/run_vidgen_workflow.py`:**
  - Add CLI flags `--draft-mode` (`action="store_true"`), `--draft-resolution` (`default="360p"`, choices `["360p", "720p"]`), and `--max-parallel-upscales` (`type=int, default=3`) to both `run_standalone_pipeline_async` and `run_multi_scene_pipeline_async`.
  - When `draft_mode=True` and `draft_resolution != resolution`:
    1. Execute all candidate shot renders (`R2V`, `i2v_chaining`, `video_extend` + `5.0s` prefix trim), OpenCV R2V/seam guards, `gemini-3.8-flash` `MediaProcessing.AGENTIC` Auto-Rater v2, Best-of-$K$ retries, and `<FIRST_FRAME>+<LAST_FRAME>` interpolation self-healing at `draft_resolution` (`360p`).
    2. Archive each scene's winning `360p` clip as `shot_{idx}_draft_{draft_resolution}.mp4`, then concurrently upscale all winning `10s` clips per scene (`asyncio.Semaphore(max_parallel_upscales)`) to `resolution` (`720p` / `1080p`) via `upscale_omni_clip_direct`, overwrite `shot_{idx}.mp4` with the upscaled clip, refresh `shot_{idx}_{first,last}_frame.png`, stitch `output_stitched_{dur}s.mp4`, and run the post-stitch scene seam audit at final resolution!
  - Instrument exact wall-clock timers (`render_sec`, `avu_sec`, `upscale_sec` on `ShotRecord`, plus `draft_and_avu_sec`, `interpolation_repair_sec`, `upscale_sec`, `stitch_and_seam_audit_sec`, and `elapsed_sec` on `WorkflowManifest` / `MultiSceneWorkflowManifest`).
- [ ] `[docs]` `[parallel]` **Update `Skill/vidgen-long-video/SKILL.md` & `references/storyboard_spec.md`:**
  - Document `--draft-mode`, `--draft-resolution`, `--max-parallel-upscales`, `omni_direct.py upscale-clip`, supported GA resolution hops (`360p -> 720p/1080p`, `720p -> 1080p/4k`), and why upscaling prefix-trimmed `10s` clips avoids the `15s` upscale ceiling while cutting upscale tokens by `33%`.
- [ ] `[test]` **Extend `tests/unit/test_standalone_skill.py` & Verify Automated Suite:**
  - Add unit tests covering `upscale_omni_clip_direct` (`task="upscale"` payload, `upscale-clip` CLI, and `360p -> 4k` guard) and mocked end-to-end `run_multi_scene_pipeline_async(..., draft_mode=True, draft_resolution="360p", resolution="720p")` (`360p` draft + `<FIRST_FRAME>+<LAST_FRAME>` heal at `360p` + concurrent `720p` upscale + `shot_{idx}_draft_360p.mp4` preservation + stage timing fields).
  - Run `uv run --no-sync pytest tests/unit/test_standalone_skill.py -v` and confirm `100%` pass.

### Phase 2: Live `task="upscale"` Smoke Check & Full 4-Act `90s` Beauty Commercial Draft-Mode Run via Skill (`[benchmark]` `[skill]`)
- [ ] `[benchmark]` **Live Single-Clip `360p -> 720p` Smoke Verification via `.agents/skills/vidgen-long-video/scripts/omni_direct.py`:**
  - Render/extract a single `10s` `360p` test clip in conversation scratch dir and run `uv run .agents/skills/vidgen-long-video/scripts/omni_direct.py upscale-clip` to verify live Vertex AI `gemini-omni-1.2-flash` `task="upscale"` response shape, `1280x720 @ 24fps` `ffprobe` dimensions, intact `48kHz` AAC audio, and single-clip upscale latency before launching the full 9-shot run.
- [ ] `[benchmark]` `[skill]` **Execute Full 4-Act `90s` Beauty Commercial (`9 × 10s` Shots) in Draft Mode via Skill CLI:**
  - Run `GOOGLE_CLOUD_LOCATION=global uv run .agents/skills/vidgen-long-video/scripts/run_vidgen_workflow.py --scenes-json output/retail_uc3_beauty_arc_90s/scenes_storyboard.json --draft-mode --draft-resolution 360p --resolution 720p --max-parallel-scenes 2 --max-parallel-upscales 3 --quality-threshold 0.80 --output-dir output/retail_uc3_beauty_arc_90s_draft` (preserving `output/retail_uc3_beauty_arc_90s/` untouched).

### Phase 3: Active Vision Audit & Head-to-Head Speed / Cost / Quality Comparison (`[qa]` `[delivery]`) `[parallel]`
- [ ] `[qa]` `[parallel]` **Verify Output Media & Build `3×3` Contact Sheet:**
  - Run `ffprobe` on `output/retail_uc3_beauty_arc_90s_draft/output_master_90s.mp4` and per-act MP4s (`1280x720`, `24fps`, `~89.8s`, stereo AAC), render `output/retail_uc3_beauty_arc_90s_draft/contact_sheet_arc_90s_draft.png` (`H1.1 Hook .. C4.2 CTA`), and visually inspect via `read_file` (confirming spokesperson lock in Acts 1/3/4 and 100% human-free `AURORA` bottle macro in Act 2).
- [ ] `[delivery]` **Compile Quantitative Speed, Stage Latency, Quality & Cost Comparison (`ACTION.md` + User Summary):**
  - Compare `Draft Mode (360p -> AVU Loop -> 720p Upscale)` (`output/retail_uc3_beauty_arc_90s_draft/run_manifest.json`) against our recorded `720p` baseline logs (`1,039.76s = 17.33m` un-resumed `9 × 10s` `720p` run + `310.84s` Act 1 / `308.78s` Act 2 `720p` scene logs): total wall-clock speedup, per-stage breakdown (`360p` draft + AVU loop vs. interpolation heal vs. concurrent `720p` upscale vs. stitch), retry/auto-heal counts, AVU + Master Seam scores, and compute cost.
