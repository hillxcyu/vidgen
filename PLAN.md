# PLAN.md — Auto-Rater v2 & Pipeline Architecture (`vidgen-omni`)

## [2026-11-03 16:20 UTC] Run 1 (COMPLETED): Auto-Rater v2 & Pipeline Architecture Implementation
- [x] **Phase 0:** Git Baseline Commit (`eaf2e99` on `main`) & Branch Isolation (`feat/autorater-v2-pipeline` `4844323`).
- [x] **Phase 1:** Auto-Rater v2 — Ground-Truth `#FFFFFF` + Prior Frame + High-Res `KEY FRAME A/M/B` Anchoring, Observation-First `property_ordering` Schema, and Deterministic OpenCV/FFMPEG/WER Telemetry (`RATER_TIMEOUT_MS=120000`).
- [x] **Phase 2:** Monotonic Best-of-$K$ Retry Checkpointing & Post-Stitch Master Seam Critic (`evaluate_stitched_master`).
- [x] **Phase 3:** Parallel Mode A (`asyncio.Semaphore`) Rendering, Per-Shot `mode_override` (`mode="hybrid"`), and Unified FastAPI `run_pipeline_async` Runner.
- [x] **Phase 4:** 69 Automated Unit/Integration/Calibration Tests Passed (`0 failed`) + Live Vertex AI Smoke Audit Verified.

---

## [2026-11-07 14:36 UTC] Run 2 (COMPLETED): Live 30s `mode="hybrid"` UC1 Apparel E2E Run & Auto-Rater v1 vs. v2 Benchmark
- [x] **Step 1 — Head-to-Head Diagnostic Audit (`v1` vs. `v2`):** Confirmed **v2** catches `#FFFFFF` SKU drift missed by **v1** (`0.40 REATTEMPT` vs. `0.95 PASS`) and cuts per-shot rater latency by **20.7%–26.0%**.
- [x] **Step 2 — Live End-to-End 30s `mode="hybrid"` Commercial Generation (`max_attempts=3`):** Rendered Shot 1 (`reference` R2V), Shot 2 (`video_extend`), and Shot 3 (`reference` act-break re-anchor); all 3 passed **v2** (`1.00`, `WER=0.0`).
- [x] **Step 3 — Post-Stitch Master Seam Audit & GCS Showcase Upload:** Stitched `output_stitched_30s.mp4` (`29.92s`), passed `evaluate_stitched_master()` (`0.95 PASSED`), and uploaded to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc1_apparel_hybrid_v2_30s/`.
- [x] **Step 4 — Side-by-Side Results & User Sign-Off:** Confirmed by user (`2026-11-07T14:35:55Z`).

---

## [2026-11-07 16:08 UTC] Run 3 (COMPLETED): Merge to `main`, Deploy to Cloud Run (`vidgen-frontend`), Regenerate All 9 Showcase Videos & Refresh Bilingual 11-Slide Decks
- [x] **Step 1 — ADK Sub-Agent Fallback Isolation & Cloud Run Batch-Run Readiness (`app/agents/pipeline.py`, `app/fast_api_app.py`, `app/tools/gcs_storage.py`):** Completed (`6577f80`).
- [x] **Step 2 — Pre-Deployment Test Suite & Git Merge (`feat/autorater-v2-pipeline` → `main`):** 70 tests passed; fast-forward merged (`c068be0`).
- [x] **Step 3 — Deploy `main` to Cloud Run (`vidgen-frontend`) & Verify Live Endpoints:** Active revision `vidgen-frontend-00011-hlp` serving `100%` traffic.
- [x] **Step 4 — Regenerate & Pin All 9 Showcase 30s Videos (`#1..#9`):** Completed (`26/27` shots `WER = 0.0`, Master Seam Critic `0.94–0.975 PASSED` on all Mode B/C runs).
- [x] **Step 5 — Rebuild Storyboard Composites & Update Bilingual 11-Slide Google Slides Decks (`EN` & `ZH-CN`):** Completed (`18/18` strips + `22/22` slides visually audited).

---

## [2026-11-08 02:21 UTC] Run 4 (COMPLETED): Upgrade to `gemini-omni-1.2-flash` + `gemini-3.8-flash` (with Agentic Video Understanding) & Preview `retail_uc3_beauty_extend_30s`
- [x] **Step 1 — Upgrade Video & Orchestrator/Rater Models:** Set `VIDEO_GEN_MODEL = "gemini-omni-1.2-flash"`, `VIDEO_EXTEND_MODEL = "gemini-omni-1.2-flash"`, and `ORCHESTRATOR_MODEL = "gemini-3.8-flash"` across `app/`, `src/`, `GEMINI.md`, and `README.md`.
- [x] **Step 2 — Harden & Instrument Agentic Video Understanding (`AVU`):** Normalized `types.MediaProcessing.AGENTIC`, added `avu_tool_use_tokens` telemetry extraction, and tightened `detected_internal_cuts` to flag internal soft cross-dissolves alongside abrupt jump-cuts.
- [x] **Step 3 — Automated Test Suite:** `80 passed, 0 failed` (`0` legacy model references remaining).
- [x] **Step 4 — Preview Regeneration & User Sign-Off (`new looks good`):** Rendered `retail_uc3_beauty_extend_30s_omni12` (`30.00s`, `S1..S3 = 0.98 / 1.00 / 1.00`, `WER = 0.0`, OpenCV `seam_mae = 2.12 / 2.39`, `avu_tool_use_tokens = 26,625 / 22,931 / 22,661 / 5,825`); approved by user (`2026-11-08T02:39:09Z`).

---

## [2026-11-08 01:51 UTC] Stage 1 (`/btw` Side Thread): Confirmed Final Plan — Standalone ADK-Free Multi-Shot Video Skill (`Skill/vidgen-long-video`)

### Confirmed Scope & Decisions
- **Canonical Shareable Location:** `Skill/vidgen-long-video/` in workspace root, **plus** relative symlink `.agents/skills/vidgen-long-video -> ../../Skill/vidgen-long-video` for automatic local agent discovery.
- **Storage Scope:** **Local filesystem only** (`--output-dir`, writing `shot_*.mp4`, `shot_*_last_frame.png`, `output_stitched_<N>s.mp4`, and `run_manifest.json` — zero `google-cloud-storage` dependency).
- **Zero ADK Dependency:** Pure `google-genai` SDK (`gemini-omni-1.2-flash` + `gemini-3.8-flash` with `media_processing="AGENTIC"`), `opencv-python-headless`, `numpy`, `pydantic`, and system `ffmpeg`/`ffprobe`.

### Proposed Directory Layout
```text
Skill/vidgen-long-video/
├── SKILL.md                     # Agent runbook: mode matrix (A/B/C/Hybrid), CLI usage, gotchas & validation checks
├── requirements.txt             # Minimal deps: google-genai, opencv-python-headless, numpy, pydantic (zero google-adk)
├── scripts/
│   ├── media_ops.py             # Standalone OpenCV + FFMPEG CLI & library (R2V Frame-0 guard, 5s tail, MAE seam-trim, audio RMS, 80ms xfade stitch)
│   ├── omni_direct.py           # Direct google-genai calls: gemini-omni-1.2-flash (interactions.create) + gemini-3.8-flash AVU rater & storyboarder
│   └── run_vidgen_workflow.py   # End-to-end ADK-free async CLI (Mode A parallel, Mode B I2V, Mode C extend, Hybrid, Best-of-K, Master Seam Critic)
└── references/
    └── storyboard_spec.md       # Pre-structured storyboard JSON format & continuity/TPVG prompting cheatsheet
```

### Step-by-Step Plan (COMPLETED)
- [x] **Step 1 — Bundle Deterministic OpenCV & FFMPEG Media Engine (`Skill/vidgen-long-video/scripts/media_ops.py`):** Completed & verified.
- [x] **Step 2 — Bundle Direct `google-genai` Model & AVU Rater Client (`Skill/vidgen-long-video/scripts/omni_direct.py`):** Completed & verified.
- [x] **Step 3 — Build Standalone End-to-End Orchestrator CLI (`Skill/vidgen-long-video/scripts/run_vidgen_workflow.py`):** Completed & verified.
- [x] **Step 4 — Author `SKILL.md` & `references/storyboard_spec.md` + Smoke Verification (`70 passed`):** Completed & verified.


---

## [2026-11-08 04:40 UTC] Stage 1 (COMPLETED — Run 5): Confirmed Final Plan — Deploy `gemini-omni-1.2-flash` + `gemini-3.8-flash` (AVU) to Cloud Run, Regenerate All 9 Showcase Videos & Update Bilingual 14-Slide Decks
- [x] **Step 1 — Finalize Model Metadata, Hardening (`task="image_to_video"`, `240s` AVU retry) & Git Commit (`5b0e141` on `main`):** Completed (`43/43` unit tests passed).
- [x] **Step 2 — Deploy `main` to Cloud Run (`vidgen-frontend`):** Active revision `vidgen-frontend-00013-464` serving `100%` traffic.
- [x] **Step 3 — Regenerate & Pin All 9 Canonical 30s (`3 × 10s`, 720p) Showcase Videos:** Completed (`27/27` shots `WER = 0.0`, `audit_status = OK`); `#3` (`retail_uc3_beauty_extend_30s`) scheduled for full 3-shot cap-persistence regeneration in Run 6 below.
- [x] **Step 4 — Rebuild 18 Bilingual Composites & Refresh Both 14-Slide Google Slides Decks (`EN` & `ZH-CN`):** Completed & visually audited across all 28 slides.


---

## [2026-11-08 02:54 UTC] Stage 1 (`/btw` Side Thread): Confirmed Final Plan — 90s Hierarchical 3-Scene Commercial (`retail_uc3_beauty_90s`) via `Skill/vidgen-long-video`

### Confirmed Scope & Decisions
- **Playback & Preview Upload:** Keep `Skill/vidgen-long-video` local-first (`output/retail_uc3_beauty_90s/output_master_90s.mp4`), **and** upload `output_master_90s.mp4`, the 3 `30s` scene videos, reference plates, and `run_manifest.json` to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_90s_preview/` for one-click browser viewing.
- **Scene Parallelism:** Execute up to `max_parallel_scenes=2` scenes concurrently (`asyncio.Semaphore(2)` with exponential backoff on `429`).

### Goal & Architecture
Use the standalone ADK-free skill (`Skill/vidgen-long-video/`)—extending it natively with **Hierarchical Multi-Scene + First/Last Frame Interpolation Self-Healing**—to produce a **90-second (`3 scenes × 3 shots × 10s = 90s` at `720p`, `16:9`)** luxury skincare commercial for **`retail_uc3_beauty`**:
1. **Shared Hero Character + Product Anchor:** [`uc3_beauty_anchor.png`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/output/retail_uc3_beauty_extend_30s/uc3_beauty_anchor.png) (East Asian spokesperson in champagne-ivory satin blazer holding the amber-gold AURORA dropper serum bottle on `#FFFFFF`).
2. **Generated Per-Scene Reference Plates (`gemini-nano-banana-2.1`, `16:9`, people-free architectural/prop anchors):** Paired alongside `uc3_beauty_anchor.png` on Shot 1 (`task="reference_to_video"`) of each 30s scene so every scene opens in a rich, distinct visual chapter while keeping character + bottle 100% consistent.
3. **Per-Scene 30s Synthesis (`Shot 1` R2V → `Shot 2` `video_extend` → `Shot 3` `video_extend`):** Each scene generates 3 continuous `10s` shots (`30s` total) inside its own physical environment.
4. **Scene Video Rating + Targeted First/Last Frame Interpolation Repair (`<FIRST_FRAME>` + `<LAST_FRAME>`):**
   - Rate each `30s` scene video (`evaluate_stitched_master_direct`) and its 3 individual `10s` shots (`evaluate_clip_quality_direct`, `gemini-3.8-flash` with `MediaProcessing.AGENTIC`).
   - If any shot `k` scores `< 0.80` (or is flagged by the scene seam critic), regenerate shot `k` via **10s two-frame interpolation (`<FIRST_FRAME>` + `<LAST_FRAME>`)** in `gemini-omni-1.2-flash`:
     - **Shot 2 (`10–20s`) repair:** `--first-frame shot_1_last_frame.png --last-frame shot_3_first_frame.png`.
     - **Shot 1 (`0–10s`) repair:** `--first-frame scene_i_opening_keyframe.png --last-frame shot_2_first_frame.png` (generating a clean grounded `16:9` opening keyframe from `uc3_beauty_anchor.png` + `scene_i_ref.png` if Frame 0 itself was flawed).
     - **Shot 3 (`20–30s`) repair:** `--first-frame shot_2_last_frame.png --last-frame scene_i_closing_keyframe.png` (reusing `shot_3_last_frame.png` if terminal framing passed, or generating a clean `16:9` closing hero keyframe from `uc3_beauty_anchor.png` + `scene_i_ref.png`).
   - Re-rate the interpolated shot, retain the higher-scoring clip, and re-stitch `scene_{i}_30s.mp4`.
5. **Final 90s Master Stitch & Audit:** Stitch `scene_1_30s.mp4 + scene_2_30s.mp4 + scene_3_30s.mp4` (`0.0s` clean act-break cuts between distinct locations; `80ms` `xfade`/`acrossfade` preserved inside each 30s scene) into `output/retail_uc3_beauty_90s/output_master_90s.mp4` and run a final 90s Master Continuity Audit.

### Proposed 3-Scene × 3-Shot (`90s`) Storyboard (`retail_uc3_beauty_90s`)
- **Scene 1 (`0s–30s`) — *Morning Sanctuary: Sunlit Travertine Bathroom***
  - **References:** `[uc3_beauty_anchor.png, scene1_travertine_sanctuary_ref.png]`
  - **Shot 1.1 (`0–10s`, R2V):** Spokesperson in champagne-ivory satin blazer stands beside a sunlit beige travertine vanity, unscrewing the gold dropper cap and releasing one luminous golden drop. *(VO: `"Every morning begins with one luminous golden drop."`)*
  - **Shot 1.2 (`10–20s`, Extend):** Continuous slow push-in inside the travertine sanctuary as she warms the golden elixir on her fingertips and presses it gently along her cheekbone. *(VO: `"Silky botanicals melt weightlessly into morning light."`)*
  - **Shot 1.3 (`20–30s`, Extend):** Smooth orbital close-up in the sunlit bathroom as she holds the amber glass bottle beside her radiant skin with a calm smile. *(VO: `"Pure hydration that awakens natural skin clarity."`)*
- **Scene 2 (`30s–60s`) — *Midday Botanical Atelier: Sunlit Glass & Chamomile Table***
  - **References:** `[uc3_beauty_anchor.png, scene2_botanical_atelier_ref.png]`
  - **Shot 2.1 (`30–40s`, R2V):** Spokesperson stands behind a sunlit limestone-and-glass botanical atelier counter lined with chamomile blooms and glass vessels, lifting the amber serum bottle so daylight refracts through the golden oil. *(VO: `"Cold-pressed botanicals illuminate every drop inside."`)*
  - **Shot 2.2 (`40–50s`, Extend):** Unbroken lateral tracking shot along the sunlit atelier counter as she draws golden elixir into the glass pipette in smooth close-up. *(VO: `"Delicate nourishment smooths texture without a trace."`)*
  - **Shot 2.3 (`50–60s`, Extend):** Continuous gentle dolly-in as she rests the capped amber bottle beside fresh white chamomile stems on the sunlit stone table. *(VO: `"Refined daily care crafted for lasting balance."`)*
- **Scene 3 (`60s–90s`) — *Golden-Hour Finale: Architectural Limestone Rooftop Terrace***
  - **References:** `[uc3_beauty_anchor.png, scene3_golden_terrace_ref.png]`
  - **Shot 3.1 (`60–70s`, R2V):** Spokesperson steps onto a warm sunset limestone rooftop terrace with olive-tree planters, holding the amber serum bottle as golden-hour light catches her champagne-ivory satin blazer. *(VO: `"From quiet sunlit mornings to golden-hour evenings."`)*
  - **Shot 3.2 (`70–80s`, Extend):** Continuous smooth tracking shot across the sunset terrace as a gentle breeze moves her sleek dark hair and warm light shimmers through the amber glass. *(VO: `"Effortless luminosity stays radiant through every hour."`)*
  - **Shot 3.3 (`80–90s`, Extend):** Sweeping hero close-up on the sunset terrace as she places the amber dropper bottle onto a sunlit travertine pedestal at dusk. *(VO: `"Timeless botanical radiance, from dawn until dusk."`)*

### Step-by-Step Execution Plan (COMPLETED)
- [x] **Step 1 — Extend `Skill/vidgen-long-video` with Native `<FIRST_FRAME>+<LAST_FRAME>` Interpolation & Multi-Scene `--scenes-json` Support (`omni_direct.py`, `run_vidgen_workflow.py`, `SKILL.md`, `storyboard_spec.md`):** Completed & verified (`4/4` unit tests passed).
- [x] **Step 2 — Generate Per-Scene Reference Plates & Write `scenes_storyboard.json`:** Generated 3 `16:9` architectural plates via `gemini-nano-banana-2.1` alongside `uc3_beauty_anchor.png`.
- [x] **Step 3 — Execute the 90s (`3 × 30s`) Generation, AVU Scene Rating, Interpolation Repair & Master Assembly:** Rendered `output_master_90s.mp4` (`89.42s`, `9/9` shots `PASSED` `0.88–1.00`, `WER = 0.0`, Scene 1 Shot 3 auto-healed `0.70 -> 1.00` via `<FIRST_FRAME>+<LAST_FRAME>` interpolation).
- [x] **Step 4 — Final 90s Master Quality Verification & GCS Upload:** Uploaded `output_master_90s.mp4`, `scene_1..3_30s.mp4`, `contact_sheet_90s.png`, reference plates, and `run_manifest.json` to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_90s_preview/`.

---

## [2026-11-08 03:56 UTC] Stage 1 (`/btw` Side Thread): Confirmed Final Plan — Add 3 Infographic & Diagram Slides Documenting `Skill/vidgen-long-video` (Antigravity/Jetski Harness vs. ADK) & `<FIRST_FRAME>+<LAST_FRAME>` Auto-Healing

### Confirmed Scope & Placement
- **Bilingual Deck Parity:** Update **both** the English (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`) and Simplified Chinese (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`) GTM Showcase decks (`11` $\rightarrow$ **`14` slides** each).
- **Presentation Flow Placement:** Insert the 3 new slides **immediately after Slide 10 (`Showcase Hub`) as Slides 11, 12, and 13**, shifting **`GTM Qualification Matrix & 2-Week Pilot` to closing Slide 14** (`XX / 14` updated cleanly across all 14 slide footers).

### Infographic & Native-Vector Diagram Design (`720 × 405 pt`, Material Design 3 Light)
1. **Slide 11 — *Why Agent Skill > Custom ADK: Harnessing Antigravity / Jetski for `90s` (`3 × 30s`) Production* (Architecture Contrast Infographic + Parallel Swimlane Diagram):**
   - **Left Visual Diagram — *Custom `google-adk` Stack vs. Portable `Skill` on Antigravity / Jetski Harness*:**
     - **Custom ADK Stack (Framework-Bound):** Rigid `LlmAgent` sub-agent transfers, `SessionService` state/SSE boilerplate, pinned SDK dependencies, isolated from Workspace tools and interactive visual inspection.
     - **`Skill/vidgen-long-video` + Antigravity / Jetski Harness (Harness-Native):**
       - **Upper Tier — *Antigravity / Jetski Frontier Harness*:** Acts directly as Creative Director with native multimodal Active Vision (`read_file` frame/plate inspection), dynamic storyboard adaptation, parallel background task/subagent execution, and native Workspace (`gslides`/`gdrive`/GCS) tool composition—automatically inheriting every harness & model upgrade with zero orchestration rewrites.
       - **Lower Tier — *Zero-ADK Portable Skill (`SKILL.md` + 3 `uv run` Scripts)*:** Deterministic domain primitives (`media_ops.py` [OpenCV/FFMPEG] + `omni_direct.py` [GenAI SDK] + `run_vidgen_workflow.py` [`--scenes-json`, `Semaphore(2)`]), drop-in shareable via `.agents/skills/`.
   - **Right Visual Diagram — *Hierarchical `90s` (`3 × 30s`) Multi-Scene Swimlane Topology*:**
     - Real thumbnails of the `#FFFFFF` Character+SKU Anchor (`uc3_beauty_anchor.png`) + 3 `Nano Banana 2.1` `16:9` architectural plates fanning into 3 parallel `30s` lanes (`Shot 1: R2V [10s]` $\rightarrow$ `Shot 2: 5s Extend + OpenCV MAE Trim` $\rightarrow$ `Shot 3: 5s Extend` $\rightarrow$ `80ms xfade 30s Scene`) $\rightarrow$ `0.0s` act-break stitch into **`90s` (`89.42s`) Master MP4**.

2. **Slide 12 — *Closed-Loop AVU Quality Gate & Automatic `<FIRST_FRAME> + <LAST_FRAME>` Self-Healing Engine* (Decision Flowchart + 3-Position Boundary Diagram):**
   - **Left/Top Native-Vector Decision Flowchart (`ROUND_RECTANGLE` + `DIAMOND` + Bound `FILL_ARROW` Connectors):**
     - `30s Scene & 3×10s Clips` $\rightarrow$ `Gemini 3.8 Flash AVU Audit` (`MediaProcessing.AGENTIC` + `KEY FRAME A/M/B` + `WER` + `Seam MAE`) $\rightarrow$ **Diamond Gate (`Score ≥ 0.80 & Seam OK?`)**:
       - **`YES` (Green Path):** Lock clip & proceed to `30s` scene stitch.
       - **`NO` (Amber/Red Auto-Heal Loop):** Extract/Synthesize Boundary Keyframes $\rightarrow$ **`Gemini Omni 1.2 Flash` `10s` Two-Frame Interpolation (`<FIRST_FRAME>` + `<LAST_FRAME>`)** $\rightarrow$ Re-Audit with `3.8 Flash AVU` $\rightarrow$ Monotonic Best-of-$K$ Replacement (`keep iff new_score > old_score`) & Re-Stitch `30s` Scene.
   - **Right/Bottom Infographic — *3-Position Boundary Anchor Wiring Matrix*:**
     - Visual diagram illustrating exact `<FIRST_FRAME>` and `<LAST_FRAME>` boundary locking for any shot index:
       - **Opening Shot 1 (`0–10s`):** `[Nano Banana 2.1 Grounded Opening Keyframe]` $\rightarrow$ **`<FIRST_FRAME>`** $\cdots$ **`<LAST_FRAME>`** $\leftarrow$ `[Shot 2 First Frame]`.
       - **Middle Shot 2 (`10–20s`):** `[Shot 1 Last Frame]` $\rightarrow$ **`<FIRST_FRAME>`** $\cdots$ **`<LAST_FRAME>`** $\leftarrow$ `[Shot 3 First Frame]`.
       - **Closing Shot 3 (`20–30s`):** `[Shot 2 Last Frame]` $\rightarrow$ **`<FIRST_FRAME>`** $\cdots$ **`<LAST_FRAME>`** $\leftarrow$ `[Nano Banana 2.1 Closing Hero Keyframe]`.

3. **Slide 13 — *Live `90s` (`89.42s`) Execution Proof & Scene 1 Shot 3 Auto-Healing Walkthrough* (Visual Before/After Diagram + `9/9` Telemetry Strip + Clickable MP4 Hub):**
   - **Top Infographic — *Live Auto-Heal Trace (`Scene 1 · Shot 3`, `20s–30s`)*:**
     - Visual 4-node progression diagram with real frames from `retail_uc3_beauty_90s`:
       1. **Extend Flagged (`Score 0.70 < 0.80`):** Soft framing drift caught by `Gemini 3.8 Flash` (`AVU = 14,150` tool tokens).
       2. **`<FIRST_FRAME>` Lock:** Real thumbnail of `shot_2_last_frame.png` (pixel-locked to Shot 2 exit).
       3. **`<LAST_FRAME>` Anchor:** Real thumbnail of `shot_3_interp_end.png` (synthesized via `Nano Banana 2.1` from `uc3_beauty_anchor.png` + `scene1_ref.png`).
       4. **Healed Shot Accepted (`0.70 → 1.00 ACCEPTED`):** `Omni 1.2 Flash` `10s` interpolation (`seam_mae = 3.79`, `WER = 0.0`), automatically re-stitched into `scene_1_30s.mp4`.
   - **Middle Infographic — *`90s` (`3 × 30s`) `9/9 PASSED` Score Timeline + One-Click GCS Video Pills*:**
     - Visual 9-shot timeline strip (`Scene 1: 0.98 | 0.88 | 1.00*` · `Scene 2: 1.00 | 1.00 | 0.95 [Seam 0.92]` · `Scene 3: 0.98 | 1.00 | 0.95 [Seam 0.82]`, `9/9 WER = 0.0`) + clickable buttons for **`▶ Watch 90s Master MP4`**, **`▶ Scene 1 (30s)`**, **`▶ Scene 2 (30s)`**, and **`▶ Scene 3 (30s)`**.
   - **Bottom Decision Banner — *Dual Delivery Pattern (Skill + Antigravity/Jetski vs. Hosted ADK Studio)*:**
     - Clear GTM rule of thumb: **Skill + Antigravity/Jetski Harness** for rapid bespoke `90s+` multi-scene creative engineering, visual inspection, & zero-infra portability vs. **Hosted ADK Web Studio** for fixed-workflow self-serve business portals.

### Step-by-Step Implementation Plan (COMPLETED)
- [x] **Step 1 — Prepare High-DPI Visual Frame Assets (`scratch/prepare_skill_slide_assets.py`):** Completed & verified.
- [x] **Step 2 — Build & Run Deterministic Bilingual Slide Mutator (`scratch/add_skill_3_slides.py`):** Completed across both `EN` and `ZH-CN` decks (`Slides 11–13`).
- [x] **Step 3 — 4-Quadrant Active Vision Audit & Deck Bookmarking:** Visually audited `150 DPI` PNG renders (`EN` & `ZH-CN`), surgically polished micro-wraps, and surfaced `.url.json` bookmarks.


---

## [2026-11-08 05:58 UTC] Stage 1 (COMPLETED — Run 6): Confirmed Final Plan — Regenerate All 3 Shots of `retail_uc3_beauty_extend_30s` (`0–30s`) with Explicit Dropper Cap / Handle Persistence

### Confirmed Scope & Decisions
- **Full 3-Shot Regeneration (`0–30s`):** Regenerate all 3 shots (`Shot 1` R2V $\rightarrow$ `Shot 2` `5.0s` `video_extend` $\rightarrow$ `Shot 3` `5.0s` `video_extend`) from scratch with explicit **gold collar + white rubber dropper bulb cap/handle** persistence across all 3 shots.
- **Direct Live Publish Once Verified:** After passing `gemini-3.8-flash` AVU + multi-frame visual contact-sheet inspection confirming the dropper cap/handle stays intact on the bottle through Shot 3, pin directly to live GCS (`#3`) and update Slide 9 in both `EN` & `ZH-CN` 15-slide GTM decks.

### Confirmed Step-by-Step Plan
- [x] **Step 1 — Author Cap-Persistent 3-Shot Choreography & AVU Rubric (`retail_uc3_beauty_extend_30s`):**
  - **Shot 1 (`0–10s`, R2V):** Spokesperson in champagne-ivory silk blazer releases a single golden serum droplet from the pipette and **lowers the glass pipette back into the bottle neck so the gold collar and white rubber dropper bulb cap rest cleanly atop the amber bottle** by shot end.
  - **Shot 2 (`10–20s`, `video_extend`):** Continuous slow dolly-in as she holds and gently tilts the **complete, closed amber-gold serum bottle with its gold collar and white rubber bulb dropper cap/handle intact on top** in warm morning sunbeams.
  - **Shot 3 (`20–30s`, `video_extend`):** Continuous smooth orbital close-up as she sets the **complete, fully capped amber-gold serum bottle — with its gold collar and white rubber bulb dropper handle clearly seated on top — onto the sunlit travertine counter beside white orchids**.
  - Enforce explicit AVU `evaluation_criteria` rejecting (`< 0.80`) any take where the bottle appears uncapped/bare-threaded or the gold collar + white bulb dropper cap vanishes.
- [x] **Step 2 — Execute Full 3-Shot Regeneration & Visual Contact-Sheet Verification:**
  - Completed (`30.00s`, `seam_mae = 1.98 / 2.21`, `WER = 0.0 / 0.0 / 0.0`, Master Seam `0.85 PASSED`, verified via 15-frame `contact_sheet_15f.png` and `shot_1..3_last_frame.png`).
- [x] **Step 3 — Re-Pin Canonical `#1..#9` Order in GCS + `saved_runs.json` & Refresh Slide 9 (`EN` & `ZH-CN`):**
  - Re-pinned `#1..#9` in exact canonical order to `gs://vital-octagon-19612-vidgen-showcase/showcase/{run_id}/`, synced `output/saved_runs.json`, rebuilt composites, and refreshed Slide 9 (`09 / 15`) across both 15-slide decks.


---

## [2026-11-08 06:08 UTC] Stage 1 (`/btw` Side Thread): Confirmed Final Plan — Update Slide 13 with Explicit Scene 1 Failed/Auto-Healed Callout & Add Dedicated Slide 14 (`9-Shot Visual Contact Sheet`, 15 Slides Total)

### Confirmed Scope & Layout (`EN` & `ZH-CN` 15-Slide Parity)
1. **Slide 13 (`13 / 15`) — *Dedicated Scene 1 Failed (`0.70`) → Auto-Healed (`1.00 ACCEPTED`) Case Study*:**
   - Add a high-visibility callout banner highlighting the exact live Scene 1 audit & auto-heal outcome:
     - **EN:** `Scene 1 (30s): Shots 1.00, 0.95, and Shot 3 auto-healed via <FIRST_FRAME> + <LAST_FRAME> interpolation (0.70 → 1.00, ACCEPTED).`
     - **ZH-CN:** `第一幕 (30s)：前两镜 1.00、0.95，第 3 镜经 <FIRST_FRAME> + <LAST_FRAME> 首尾双帧插值自动自愈（0.70 → 1.00，ACCEPTED）。`
   - Retain the crisp 4-stage visual frame progression (`1. Extend Flagged 0.70 < 0.80` $\rightarrow$ `2. <FIRST_FRAME> Lock` `shot_2_last_frame.png` $\rightarrow$ `3. <LAST_FRAME> Synth` `shot_3_interp_end.png` $\rightarrow$ `4. Healed: 1.00 PASS` `seam_mae = 3.79, WER = 0.0`) + Dual Enterprise Delivery takeaway banner (`Skill + Antigravity/Jetski` vs. `Hosted ADK Studio`).

2. **New Slide 14 (`14 / 15`) — *Large-Format `90s` 9-Shot Visual Contact Sheet (`S1.1..S3.3`) & Interactive Playback Hub*:**
   - **Left Large-Format `16:9` Visual Frame (`W=432, H=243`):** Embed full uncropped `contact_sheet_90s.png` (`3×3` storyboard grid `S1.1 | t=05.0s` .. `S3.3 | t=84.4s` across Morning Travertine, Botanical Atelier, and Golden-Hour Terrace) + bottom caption bar with direct link to `https://storage.cloud.google.com/vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_90s_preview/contact_sheet_90s.png`.
   - **Right Telemetry & Playback Rail (`W=204`):**
     - **Scene 1 (`29.92s`):** `1.00` · `0.95` · `0.70→1.00★` + clickable `▶ Watch Scene 1 (30s)`
     - **Scene 2 (`29.75s`):** `1.00` · `1.00` · `0.95` (`Seam 0.92`) + clickable `▶ Watch Scene 2 (30s)`
     - **Scene 3 (`29.75s`):** `0.98` · `1.00` · `0.95` (`Seam 0.82`) + clickable `▶ Watch Scene 3 (30s)`
     - **Primary CTAs:** **`🔍 Open 9-Shot Contact Sheet (PNG)`** (`contact_sheet_90s.png`) + **`▶ Watch Full 90s Master MP4`** (`output_master_90s.mp4`).
   - Shift **`GTM Qualification Matrix & 2-Week Pilot` to Slide 15 (`15 / 15`)** and sync all slide footers (`01 / 15` .. `15 / 15`) across both `EN` and `ZH-CN` decks.

### Step-by-Step Execution Plan (COMPLETED)
- [x] **Step 1 — Prepare Framed `16:9` Contact Sheet Asset:** Completed (`s14_contact_sheet_90s.png`).
- [x] **Step 2 — Update Slide 13, Insert Slide 14 & Sync `XX / 15` Footers (`EN` & `ZH-CN`):** Completed across both 15-slide decks.
- [x] **Step 3 — 4-Quadrant Active Vision Audit:** Visually verified `150 DPI` PNG renders (`Slides 11–15`, `EN` & `ZH-CN`).


---

## [2026-11-08 06:30 UTC] Stage 1: Confirmed Final Plan — Archive Pre-Heal Failed Shots in `Skill/vidgen-long-video`, Upload Failed vs. Healed Shot 1.3 MP4s & Attach Comparison Links on Slide 13

### Verification Finding (`Never Assume; Always Verify`)
- In `output/retail_uc3_beauty_90s/scene_1/`, [`run_vidgen_workflow.py:724`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/Skill/vidgen-long-video/scripts/run_vidgen_workflow.py#L724) executed `shutil.copyfile(cand_path, rec.video_path)` when `shot_3_interp.mp4` (`1.00 ACCEPTED`) beat the `0.70` `video_extend` clip—overwriting `shot_3.mp4` in-place (`MD5 = 9f99ad2185bd86a2df1bdabf4d628037` on both `shot_3.mp4` and `shot_3_interp.mp4`) without saving a `shot_3_failed_before_heal.mp4` backup first.
- All exact upstream inputs for Scene 1 Shot 3 (`scene_1/shot_2.mp4` `5.0s` tail + `scenes_storyboard.json` Shot 1.3 prompt & AVU rubric) remain intact on disk.

### Confirmed Step-by-Step Execution Plan (COMPLETED)
- [x] **Step 1 — Harden `Skill/vidgen-long-video` Pre-Heal Archival (`run_vidgen_workflow.py` + Unit Test):**
  - Before overwriting `rec.video_path` when an interpolated repair is accepted, automatically copy the original failed clip to `shot_{idx}_failed_before_heal.mp4` and store `original_video_path` in `InterpolationRepairRecord` (verified via `pytest tests/unit/test_standalone_skill.py`).
- [x] **Step 2 — Capture Failed `video_extend` Shot 1.3 & Upload Side-by-Side Comparison Clips to GCS:**
  - Reproduce a sub-`0.80` `video_extend` clip from the exact `scene_1/shot_2.mp4` `5.0s` tail (`shot_3_failed_before_heal.mp4`, audited with `gemini-3.8-flash` AVU while keeping `scene_1_30s.mp4` and `output_master_90s.mp4` untouched).
  - Upload **both** `scene_1_shot_3_failed_extend.mp4` (Before / Failed `video_extend`) and `scene_1_shot_3_healed_interp.mp4` (After / `1.00 ACCEPTED` `<FIRST_FRAME>+<LAST_FRAME>` interpolation) to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_90s_preview/`.
- [x] **Step 3 — Attach Side-by-Side Comparison Links on Slide 13 (`EN` & `ZH-CN`) & Run Active Vision Audit:**
  - Add a real frame thumbnail from the failed `video_extend` clip + clickable **`▶ Watch Failed Shot 3`** button inside **Card 1 (`1. SHOT 3 FAILED`)**, and clickable **`▶ Watch Healed Shot 3 (1.00)`** inside **Card 4 (`4. ACCEPTED`)** on Slide 13 across both `EN` and `ZH-CN` decks, then re-export and visually audit `Slide 13` PNGs.


---

## [2026-11-08 06:59 UTC] Stage 1: Confirmed Final Plan — Add All 6 ADK Agent Names & Native-Vector Multi-Agent Infographic on Slide 5 (`EN` & `ZH-CN`)

### Verified 6 ADK Agents in [`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py#L960-L1066)
1. **`vidgen_orchestrator`** (`Root Coordinator` · `MemoryBank` + `generate_video_shot_clip` [`Omni 1.2`] + `concatenate_video_clips`)
2. **`ScreenwriterAgent`** (`Gemini 3.8 Flash` · Brand brief + `character_bible` -> screenplay)
3. **`StoryboarderAgent`** (`Gemini 3.8 Flash` · Timed `10s` shot specs, dialogue `<=12w`, Hybrid A/B/C routing)
4. **`PromptOptimizerAgent`** (`Gemini 3.8 Flash` · `#FFFFFF` R2V / `<FIRST_FRAME>` I2V / `<VIDEO_0>` Extend control + retry feedback)
5. **`HealthCheckerAgent`** (`Gemini 3.8 Flash` · Brand safety, policy & speech compliance gate)
6. **`QualityRaterAgent`** (`Gemini 3.8 Flash AVU` · `MediaProcessing.AGENTIC`, WER, jump-cut & Master Seam Critic)

### Confirmed Step-by-Step Execution Plan (COMPLETED)
- [x] **Step 1 — Build Native-Vector 6-Agent ADK Architecture Infographic on Slide 5 (`EN` & `ZH-CN`):**
  - Replace the unlabeled decorative 3D image on the right of Slide 5 (`v12_s05_arch_en` / `v12_s05_arch_zh`, `05 / 15`) with a crisp, editable **native-vector 6-Agent Orchestration & Quality Flywheel Diagram** displaying all 6 exact `app/agent.py` agent names (`vidgen_orchestrator` hub + `ScreenwriterAgent` -> `StoryboarderAgent` -> `PromptOptimizerAgent` -> `HealthCheckerAgent` -> `Omni 1.2 Render` -> `QualityRaterAgent`, with the `< 0.80` Best-of-K / Dual-Anchor feedback arrow back to `PromptOptimizerAgent`).
  - Align the 3 left M3 phase cards (`W=256 pt`, freeing `W=380 pt` for the right vector diagram) so every card explicitly highlights its corresponding agent names (`1–6`) and tightens the headline onto a clean single line on `EN` as well as `ZH-CN`.
- [x] **Step 2 — Update Slide 5 Speaker Notes & Run 4-Quadrant Active Vision Audit:**
  - Sync Slide 5 speaker notes (`EN` & `ZH-CN`) with the 6-agent handoff sequence.
  - Export `Slide 5` (`EN` & `ZH-CN`) to `150 DPI` PNGs and inspect visually via `read_file` to guarantee zero text wrapping, overlap, or arrow collision.


---

## [2026-11-08 07:06 UTC] Stage 1: Confirmed Final Plan (Run 7) — Update Slide 2 (`Act I: The 8-Second Wall`) with Full-Canvas 3-Use-Case Diagonal `/` Vertical Banners (`uc1_bg / uc2_bg / uc3_bg`) + Bottom-Wide Midnight Capsule

### Confirmed Scope & Design Decisions
- **Layout (`A1`):** **Full-Canvas 3 Wide Diagonal `/` Vertical Banners (`0..720 pt`) + Bottom-Wide Midnight Capsule (`y = 234..389 pt`)** — 3 wide slanted `/` columns spanning the entire `720 × 405 pt` slide above a sleek lower-third `#0B192C` card, keeping all 3 hero SKUs/subjects 100% unobstructed across the upper `0..232 pt` panoramic stage.
- **Visual Source (`A2`):** **Actual Hero Frames from Our 3 Live `gemini-omni-1.2-flash` Showcase Commercials** (`UC1 Terracotta Alpine Down Jacket` `/` `UC2 AeroPulse Cobalt Carbon-Plate Runner` `/` `UC3 LuminaDrop Capped Golden Serum Spokesperson`), framed so faces & products sit cleanly inside the upper hero band with zero baked-in text (`Zero-Text in Image`) and native Google Slides category micro-badges (`UC1 · APPAREL`, `UC2 · FOOTWEAR`, `UC3 · BEAUTY`) at top.

### Confirmed Step-by-Step Plan (COMPLETED)
- [x] **Step 1 — Build High-DPI Full-Canvas Diagonal `/` Triptych (`s2_triptych_720x405.png`):**
  - Compose a `1920 × 1080 px` (`720 × 405 pt`) 3-panel slanted `/` vertical banner image (`uc1_bg / uc2_bg / uc3_bg`) from the live Omni 1.2 showcase frames with focal-aware vertical framing (keeping all 3 SKUs & faces inside the upper `y = 0..232 pt` hero zone), anti-aliased `/` diagonal accent dividers, and a subtle lower-third dark vignette.
- [x] **Step 2 — Surgically Rebuild Slide 2 (`v12_s02_cinema_en` & `v12_s02_cinema_zh`) with Bottom-Wide Midnight Capsule:**
  - Update **only** Slide 2 in place across both **EN (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`)** and **ZH-CN (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`)** decks (inserting `s2_triptych_720x405.png`, top native category micro-pills, bottom-wide `#0B192C` capsule with eyebrow + gold Retail Mandate pill + single-line headline + 3 crisp bullets + page counter, and updated tripartite speaker notes).
- [x] **Step 3 — 4-Quadrant Active Vision Audit (`EN` & `ZH-CN`):**
  - Export `en_slide-02.png` and `zh_slide-02.png` thumbnails and inspect via `read_file` to verify crisp `/` diagonal alignment, 100% unoccluded visibility of all 3 SKUs/faces above the bottom capsule, zero text overflow, and bilingual parity.


---

## [2026-11-08 07:19 UTC] Stage 1: Confirmed Final Plan — Insert Section `02` Break Slide (Introducing the Skill-Based Flow) Between Slides 10 & 11 (`EN` & `ZH-CN`, `16` Slides Total)

### Verified Slide 4 (`01`) Break Slide Geometry (`v12_s04_break_en` / `v12_s04_break_zh`)
- Full-bleed color background (`#4285F4` on Section `01`; `#1E8E3E` Google Green confirmed for Section `02` to pair with the green Skill theme across Slides 12–15 while preserving 100% identical coordinates and white contrast).
- Left Hero (`X=48`): `44pt` numeral (`02`), `24pt` 3-line headline (`Y=126`), `10.6pt` subtitle (`Y=258`).
- Right 4 White Rounded Cards (`X=398, W=282, H=68` at `Y=46, 126, 206, 286`) with `36×36pt` Google-4-color numbered badges (`01`, `02`, `03`, `04`).

### Confirmed Step-by-Step Execution Plan (COMPLETED)
- [x] **Step 1 — Insert Section `02` Break Slide (`v13_s11_break_skill_{lang}`) at Slide 11 (`insertionIndex=10`) & Sync `XX / 16` Footers:**
  - Insert `v13_s11_break_skill_en` and `v13_s11_break_skill_zh` immediately between Slide 10 (`3x3 All-9 MP4 Hub`) and current Slide 11 (`Skill vs. ADK Architecture`, shifting Skill slides to `12–15` and GTM Closing to `16`).
  - Mirror Slide 4's exact coordinates (`02` section numeral + 3-line Skill/Harness headline + 4 white pillar cards: `01 Frontier Harness, Zero Infra`, `02 Parallel 3×30s Scene Topology`, `03 <FIRST>+<LAST> Auto-Healing`, `04 Verified 89.42s 9-Shot Master`).
  - Dynamically update all slide footers across both decks from `XX / 15` to `XX / 16` (`01 / 16` .. `16 / 16`) and attach tripartite speaker notes.
- [x] **Step 2 — 4-Quadrant Active Vision Audit (`150 DPI`):**
  - Export the new Slide 11 (`-f 11 -l 11`) on both `EN` and `ZH-CN` decks to `150 DPI` PNGs and inspect via `read_file` alongside Slide 4 (`01`) to guarantee pixel-aligned consistency and zero text overflow.


---

## [2026-11-08 07:47 UTC] Stage 1: Confirmed Final Plan — Remove 2-Week Retail Pilot Path on Slide 16 & Full-Deck Bilingual Audit Polish (`EN` & `ZH-CN`, `16` Slides)

### Audited Presentations & Scope Choices
- **EN (`16` slides):** `1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`
- **ZH-CN (`16` slides):** `12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`
- **Slide 16 Bottom Replacement (`A1`):** Replace the removed `2-Week Retail Pilot Path` box with a concise **Dual Enterprise Delivery Summary Bar** (`Hosted ADK 2.0 Web Studio` on Cloud Run / Agent Runtime for `30s` self-serve SKU portals + `Portable Zero-ADK Skill` on Antigravity/Jetski for `90s+` bespoke multi-scene ads).
- **Selected Audit Improvements (`A2`):** All 4 narrative, metric, speaker-note, and visual/typographic polish bundles selected.

### Confirmed Step-by-Step Plan
- [x] **Step 1 — Remove `2-Week Retail Pilot Path` on Slide 16 & Add Dual Enterprise Delivery Summary Bar (`EN` & `ZH-CN`):**
  - Remove the `RECOMMENDED 2-WEEK RETAIL PILOT PATH` / `推荐两周零售客户 POC 落地路径` callout (`v14_shp_{lang}_0218`, `v14_txt_{lang}_0219`, `v14_txt_{lang}_0220`) and strip all `pilot / POC` references from Slide 16's eyebrow, headline, and speaker notes.
  - Replace the bottom band (`Y=312..372`) with a sleek **Dual Enterprise Delivery Architecture Bar** (`Hosted ADK 2.0 Web Studio [Cloud Run / Agent Runtime]` vs. `Portable Zero-ADK Skill [Antigravity / Jetski]`) and unify Slide 16's footer (`ADK 2.0 & Portable Skill + Omni 1.2 + 3.8 AVU`).
- [x] **Step 2 — Narrative, Metric & Speaker-Note Consistency Fixes (`Slides 1, 2, 7, 8, 10, 14, 15, 16`):**
  - Fix stale speaker-note `[TRANSITION]` slide numbers & pilot references (`Slide 10` -> transition to `Slide 11` Section `02`; `Slide 14` -> transition to `Slide 15` Contact Sheet + sync `ZH` Slide 14 verbal script with the unlabeled-bottle root cause; `Slide 15` -> transition to `Slide 16` GTM Playbook; `Slide 16` -> Dual Delivery closing script).
  - Unify `30s–60s` scope to **`30s–90s+`** across **Slide 1 (`Cover`)**, **Slide 2 (`8-Second Wall`)**, and **Slide 10 (`Hub`)**, updating Slide 1's subtitle & right rail (`9 × 30s Ads + 90s Auto-Healed Master`).
  - Clarify sub-`0.80` single-take AVU metrics on **Slide 7 (`UC2: 0.67`)** and **Slide 8 (`Mode B: 0.71 / 0.63 / 0.63`)** by surfacing `SKU Lock: 0.95` (multi-set hard cuts) and `Master Seam QA: 0.94–0.97 PASS` (Mode B) so they don't look like `< 0.80` failures next to Slide 13.
- [x] **Step 3 — Visual & Typographic Polish (`Slides 3, 6, 7, 8, 9, 10, 12, 15, 16`):**
  - Tighten 1–2 word orphan 2nd-line wraps on `EN` headlines (`Slides 3, 6, 7, 8, 9, 10, 16`) onto crisp single-line headers.
  - Convert tall outer `ROUND_RECTANGLE` wrapper frames (`Slides 7, 8, 9, 10, 12 [right], 15`) to clean `1pt` `RECTANGLE` frames (matching Slide 5) so inner header strips and CTA buttons never graze curved corners.
- [x] **Step 4 — 4-Quadrant Active Vision Audit & `.url.json` Bookmark Sync:**
  - Export all updated slides across both `EN` and `ZH-CN` decks at `150 DPI` PNG, visually verify zero clipping/overlap via `read_file`, and update the `.url.json` artifacts (`14 Slides` -> `16 Slides`).


---

## [2026-11-08 08:42 UTC] Stage 1: Confirmed Final Plan (Run 8) — Update Mode B (`i2v_chaining`) Prompts Only to Match Mode C's Single-Take Scenes (Zero Pipeline Code Changes)

### Confirmed Decisions (`ask_question` `A1` & `A2`)
- **Prompt-Only Scope (`A2`):** **Do NOT modify any pipeline code or rules** (`app/`, `src/`, `Skill/` untouched; **no** Cloud Run container rebuild/redeployment). Update **only** the 3 Mode B showcase storyboard prompts & voiceover scripts so they match Mode C's continuous single-location, single-take scenes (`no hard transitions`).
- **Fresh 3-Shot Generation (`A1`):** Render **all 3 shots (`Shot 1` `#FFFFFF` R2V + `Shots 2–3` `<FIRST_FRAME>` I2V)** fresh from scratch for each of the 3 Mode B commercials (`retail_uc1_apparel_lookbook_30s`, `retail_uc2_footwear_hero_30s`, `retail_uc3_beauty_regional_30s`) using Mode C's exact single-take prompts & spoken lines:
  1. **`UC1 Apparel` (`retail_uc1_apparel_lookbook_30s`):** Continuous Single-Take Winter Street & Snowfall Walk (`Boutique café exit onto misty winter sidewalk` → `Backward tracking stroll past frosted evergreens & streetlamps in light snow` → `Smooth arc to hero medium close-up beneath softly falling snow`).
  2. **`UC2 Footwear` (`retail_uc2_footwear_hero_30s`):** Continuous Single-Take Dark Basalt Studio Orbital Showcase (`Macro low-angle orbital around standalone cobalt shoe on dark basalt pedestal` → `Continuous low-angle orbital macro glide in cool mist` → `Smooth warm golden rim-light sweep into hero profile lockup`).
  3. **`UC3 Beauty` (`retail_uc3_beauty_regional_30s`):** Continuous Single-Take Sunlit Travertine Studio Journey (`Medium waist-up shot releasing one golden droplet & seating the metallic gold collar + white bulb dropper cap closed onto the bottle` → `Slow single-take dolly-in holding & tilting the closed serum bottle in morning sunbeams` → `Smooth orbital close-up setting the complete capped bottle onto the sunlit travertine counter beside white orchids`).

### Confirmed Step-by-Step Plan
- [x] **Step 1 — Update Mode B Prompts & Render All 3 × 30s (`9` Shots) Fresh via `mode="i2v_chaining"`:**
  - Create a clean scratch runner (`scratch/regenerate_mode_b_single_take.py`) using Mode C's exact single-take scene descriptions, `evaluation_criteria`, and `voice_transcript` adapted strictly to Mode B's `<FIRST_FRAME>` prompt phrasing (`Shot 1` R2V -> `Shots 2–3` `"Use this image as the starting frame. Remaining in the exact same ... in one unbroken single take with no scene cuts..."`), rendering all 3 shots fresh per run on `gemini-omni-1.2-flash` + `gemini-3.8-flash` AVU + `evaluate_stitched_master()`.
- [x] **Step 2 — Visually Audit All 3 Mode B Runs & Re-Pin All 9 Canonical Showcase Runs to GCS:**
  - Verify `WER = 0.0`, `seam_mae`, AVU scores, and visual continuity (including UC3's closed dropper cap across all 3 shots) via contact sheets / boundary frames.
  - Re-pin all 9 canonical 30s runs (`#1..#9`, keeping Mode A `#7–#9` and Mode C `#1–#3` intact while updating Mode B `#4–#6`) to `gs://vital-octagon-19612-vidgen-showcase/showcase/{run_id}/` + `output/saved_runs.json` (live `vidgen-frontend` automatically picks up the newer `pinned_at` GCS manifests).
- [x] **Step 3 — Rebuild Mode B `2×2` Composites & Surgically Refresh Slide 8 (`EN` & `ZH-CN`):**
  - Rebuild `uc{1,2,3}_strip_{en,zh}.png` (`2×2` Mode B composites) and upload to `gs://vital-octagon-19612-vidgen-showcase/showcase/composites/`.
  - Surgically update **Slide 8 (`v12_s08_i2v_en` & `v12_s08_i2v_zh`)** in place across both `EN` and `ZH-CN` decks (preserving dynamic total page count, `1pt` `RECTANGLE` card frames, updated single-take arcs & live metrics, and Mode B vs. Mode C comparison speaker notes) and verify via `read_file` PNG inspection.


---

## [2026-11-08 08:40 UTC] Stage 1: Confirmed Final Plan — Second `90s` Skill Example (`Hook → SKU Hero → Lifestyle Proof → CTA`) on Same UC3 Product & Model + New Slide 16 (`17` Slides Total)

### Confirmed Scope (`ask_question` `A1` & `A2`)
- **Product & Spokesperson Anchor:** Identical UC3 canonical `#FFFFFF` anchor (`output/retail_uc3_beauty_90s/refs/uc3_beauty_anchor.png` — East Asian spokesperson in champagne-ivory satin blazer + amber-gold AURORA dropper serum bottle).
- **Narrative Arc & Pacing (`A1`):** **Asymmetric 4-Act `90s` Commercial (`9 × 10s` shots = `20s + 20s + 30s + 20s`):**
  1. **Act 1 — `Hook` (`20s`, `2 × 10s`):** Late-night urban glass vanity tension & discovery (`act1_urban_vanity_ref.png`).
  2. **Act 2 — `SKU Hero` (`20s`, `2 × 10s`):** Backlit alabaster apothecary active drop & capped bottle refraction (`act2_alabaster_pedestal_ref.png`).
  3. **Act 3 — `Lifestyle Proof` (`30s`, `3 × 10s`):** Unfiltered mid-morning sunlit glass design studio all-day radiance (`act3_daylight_gallery_ref.png`).
  4. **Act 4 — `CTA` (`20s`, `2 × 10s`):** Golden-hour champagne-travertine flagship plinth sign-off & conversion invitation (`act4_flagship_plinth_ref.png`).
- **Deck Presentation (`A2`):** Insert a dedicated **Slide 16 (`16 / 17`, shifting GTM Playbook to `17 / 17`)** across both **EN (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`)** and **ZH-CN (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`)** decks with the `3×3` 9-Shot Contact Sheet, 4-Act breakdown, AVU scores, and clickable MP4 links.

### Confirmed Step-by-Step Plan (COMPLETED)
- [x] **Step 1 — Generate 4 Architectural Scene Plates (`gemini-nano-banana-2.1`) & Author `scenes_storyboard.json`:**
  - Create `output/retail_uc3_beauty_arc_90s/refs/`, copy `uc3_beauty_anchor.png`, generate 4 people-free `16:9` architectural plates via `Skill/vidgen-long-video/scripts/omni_direct.py generate-image`, visually inspect all 4 plates via `read_file`, and write `output/retail_uc3_beauty_arc_90s/scenes_storyboard.json` (`2 + 2 + 3 + 2 = 9` shots, `<= 10` words/shot spoken copy, capped-bottle continuity guardrails).
- [x] **Step 2 — Execute Zero-ADK `90s` 4-Act Production Pipeline (`Skill/vidgen-long-video`):**
  - Run `uv run Skill/vidgen-long-video/scripts/run_vidgen_workflow.py --scenes-json output/retail_uc3_beauty_arc_90s/scenes_storyboard.json --max-parallel-scenes 2 --quality-threshold 0.80 --output-dir output/retail_uc3_beauty_arc_90s` (`gemini-omni-1.2-flash` R2V + `5.0s` audio-intact `video_extend` + `gemini-3.8-flash` AVU + automatic `<FIRST_FRAME>+<LAST_FRAME>` interpolation self-healing + `output_master_90s.mp4`).
- [x] **Step 3 — Build Act-Labeled `3×3` Contact Sheet & Upload Preview Artifacts to GCS:**
  - Build `contact_sheet_arc_90s.png` (`3×3` grid labeled `H1.1 Hook .. C4.2 CTA`), inspect via `read_file`, and upload `output_master_90s.mp4`, all 4 act MP4s (`act_1_hook_20s.mp4`, `act_2_sku_hero_20s.mp4`, `act_3_lifestyle_proof_30s.mp4`, `act_4_cta_20s.mp4`), `contact_sheet_arc_90s.png`, and `run_manifest.json` to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_arc_90s_preview/`.
- [x] **Step 4 — Insert Slide 16 (`16 / 17`) Across EN & ZH-CN Decks & Run 4-Quadrant Active Vision Audit:**
  - Insert Slide 16 (`v17_s16_arc_90s_{en,zh}`) right after Slide 15, update Cover/Section `02` references (`2 × 90s` Skill Masters) & `01 / 17 .. 17 / 17` footers, attach speaker notes, export `150 DPI` PNGs, and verify zero overlap/overflow via `read_file`.


---

## [2026-11-08 11:09 UTC] Stage 1: Confirmed Final Plan (Run 9) — Update Single-Video Duration Limit (`15s` on Gemini Omni 1.2 Flash) Across Decks & Refocus Slide 8 Purely on Mode B

### Confirmed Decisions (`ask_question` `A1` & `A2`)
- **Single-Video Duration Limit (`A1`):** Use **`15s` (`"15-Second Clip"` / `"15 秒"`)** — official GA `gemini-omni-1.2-flash` max single-video generation/edit duration (`3s–15s` across T2V, I2V, R2V, and Video Edit).
- **Stage 1 Plan Approval (`A2`):** Approved to proceed to Stage 2 (`DEFINE.md`).

### Context & Audit Findings Across All 17 Slides (`EN` & `ZH-CN`)
- **Exact `8s` / Legacy Single-Clip Ceiling Hits Across Both 17-Slide Decks:**
  1. **Presentation Document Titles (`Drive/Slides Title`):**
     - `EN`: `'vidgen-omni: Scaling Retail Video Beyond the 8-Second Clip (GTM Showcase)'` → `'vidgen-omni: Scaling Retail Video Beyond the 15-Second Clip (GTM Showcase)'`
     - `ZH-CN`: `'vidgen-omni：突破 8 秒瓶颈，打造零售与电商长视频生成方案（GTM 实战演示）'` → `'vidgen-omni：突破 15 秒瓶颈，打造零售与电商长视频生成方案（GTM 实战演示）'`
  2. **Slide 1 (`Cover` — `v12_s01_cover_en` & `v12_s01_cover_zh`):**
     - `EN` title (`v14_txt_en_0008`): `'Scaling Retail Video Beyond\nthe 8-Second Clip'` → `'Scaling Retail Video Beyond\nthe 15-Second Clip'` + `EN` speaker notes (`'8-second wall'` → `'15-second wall'`, `'stopping at eight seconds'` → `'stopping at 15 seconds'`).
     - `ZH-CN` title (`v14_txt_zh_0008`): `'突破 8 秒短视频瓶颈\n规模化生成零售商业长视频'` → `'突破 15 秒短视频瓶颈\n规模化生成零售商业长视频'`.
  3. **Slide 2 (`Act I` — `v12_s02_cinema_en` & `v12_s02_cinema_zh`):**
     - `EN` eyebrow (`v14_txt_en_6905`): `'ACT I  ·  THE 8-SECOND WALL'` → `'ACT I  ·  THE 15-SECOND WALL'`, headline (`v14_txt_en_6907`): `'...stops at isolated eight-second clips'` → `'...stops at isolated 15-second clips'`, + `EN` speaker notes (`'5–10s'` → `'up to 15s on Gemini Omni 1.2 Flash'`, `'8-second AI clips'` → `'15-second AI clips'`).
     - `ZH-CN` eyebrow (`v14_txt_zh_9705`): `'零售营销“10 秒高墙”'` → `'第一幕  ·  零售营销“15 秒高墙”'`, headline (`v14_txt_zh_9707`): `'当生成式 AI 止步于孤立的 10 秒片段...'` → `'当生成式 AI 止步于孤立的 15 秒片段...'`, + `ZH-CN` speaker notes (`'5–10 秒'` → `'Gemini Omni 1.2 Flash 单次生成上限 15 秒'`, `'孤立的 8 秒 AI 短片'` → `'孤立的 15 秒 AI 短片'`).
- **Slide 8 (`Mode B` — `v12_s08_i2v_en` & `v12_s08_i2v_zh`):**
  - Remove all mentions comparing or highlighting similarity to Mode C across Slide 8's eyebrow (`ZH`), headline (`EN` & `ZH`), bottom takeaway banner (`EN` & `ZH`), and speaker notes (`EN` & `ZH`), describing **only** what Mode B (`i2v_chaining`) is: Shot 1 native `#FFFFFF` R2V scene entry + sequential `<FIRST_FRAME>` terminal-PNG Image-to-Video chaining (`task='image_to_video'`) + `80ms` crossfade stitch.

### Confirmed Step-by-Step Plan (COMPLETED)
- [x] **Step 1 — Update All `8s` (and `ZH` Slide 2 `10s`) Single-Clip Limit References to `15s` Across Slides 1 & 2, Speaker Notes & Deck Titles (`EN` & `ZH-CN`):**
  - Updated Slide 1 Cover titles, Slide 2 Eyebrows & Headlines, Slide 1–2 Speaker Notes, and Google Slides document titles across both `EN` and `ZH-CN` decks, verifying zero residual `8s` / `8-second` / `eight-second` / `8 秒` hits across all 17 slides and notes (`task-8403`).
- [x] **Step 2 — Refocus Slide 8 (`v12_s08_i2v_en` & `v12_s08_i2v_zh`) Purely on Mode B (`<FIRST_FRAME>` I2V Chaining):**
  - Updated Slide 8's eyebrow, single-line headline, bottom summary banner, and speaker notes across both `EN` and `ZH-CN` to cleanly explain Mode B's architecture (`Shot 1` `#FFFFFF` R2V $\rightarrow$ `Shots 2–3` OpenCV terminal-frame PNG `<FIRST_FRAME>` I2V chaining) with **zero** mention of Mode C similarity, keeping the 3 refreshed single-take Mode B video cards, links, and metrics intact.
- [x] **Step 3 — 4-Quadrant Active Vision Audit (`Slides 1, 2, 8` in `EN` & `ZH-CN`):**
  - Exported updated PNG thumbnails of Slides 1, 2, and 8 in both languages, visually verified single-line headlines and zero text clipping/wrapping via `read_file`, and synced `.url.json` deliverable bookmarks.


---

## [2026-11-08 11:57 UTC] Stage 1: Confirmed Final Plan (Run 10) — Add Author Badge with Round Moma Profile Photo on Cover Slide 1 (`EN` & `ZH-CN`)

### Confirmed Decisions (`ask_question` `A1` & `A2`)
- **Moma Photo & Author Credit (`A1`):** Moma preferred portrait (`xcyu_preferred.jpg`) rendered as a crisp circular RGBA avatar + Name, Email & Role (`Hill Yu · xcyu@google.com` / `Practice Specialist, AI Vision  |  Google Cloud`, localized cleanly on `ZH-CN`).
- **Scope (`A2`):** Cover Slide 1 (`v12_s01_cover_en` & `v12_s01_cover_zh`) across both `EN` and `ZH-CN` decks.

### Context & Discovery Findings
- **Moma Author Profile Verified (`moma_cli person xcyu` & Teams Photos API):**
  - **Name & Email:** `Hill Yu` (`xcyu@google.com`)
  - **Title:** `Practice Specialist, AI Vision` (`Google Cloud`)
  - **Moma Photos Retrieved (`512×512`):**
    1. `type=preferred` (`xcyu_preferred.jpg` — soft studio portrait displayed on Moma profile/hovercard, selected).
    2. `type=security` (`xcyu_security.jpg` — security badge photo on white background).
- **Cover Slide 1 (`v12_s01_cover_en` & `v12_s01_cover_zh`) Geometry Audit:**
  - Subtitle (`v14_txt_{lang}_0009`) ends visually around `Y = 262` (`EN`) / `Y = 248` (`ZH-CN`), leaving generous breathing room above the `Audience` pill (`X=48, Y=326, W=436, H=38`).
  - Placing a circular RGBA Moma avatar (`38 × 38 pt`, `4x` Lanczos supersampled circle mask + crisp subtle `#4285F4` / `#FFFFFF` ring) + two-line Author label at `Y = 280..318` and nudging the `Audience` pill slightly to `Y = 330..366` aligns the left column bottom cleanly with the 4th right-hand arc card (`Y = 366`) with zero crowding.

### Confirmed Step-by-Step Plan (COMPLETED)
- [x] **Step 1 — Render Anti-Aliased Round Moma Profile Avatar (`512×512` RGBA PNG):**
  - Rendered `xcyu_moma_round_512.png` via Pillow (`4x` Lanczos supersampling + `#FFFFFF` inner ring + `#4285F4` Google Blue outer ring).
- [x] **Step 2 — Insert Author Badge (Round Moma Avatar + Name/Role) on Cover Slide 1 (`EN` & `ZH-CN`):**
  - Updated `v12_s01_cover_en` and `v12_s01_cover_zh` with the circular Moma avatar + `Hill Yu · xcyu@google.com` / `Practice Specialist, AI Vision | Google Cloud` (`task-8529`).
- [x] **Step 3 — 4-Quadrant Active Vision Audit (`Slide 1` in `EN` & `ZH-CN`):**
  - Visually verified `en_slide-01.png` and `zh_slide-01.png` via `read_file` and refreshed `.url.json` deliverable bookmarks.

---

## [2026-11-08 12:01 UTC] Stage 1: Confirmed Final Plan — Remake Act 2 (`SKU Hero`, `20s`) as a Human-Free Product-Only Showcase with Formula & Effectiveness Background VO

### Goal & Constraints
- **Target Scope:** Remake **only Act 2 (`act_2_sku_hero`, `2 × 10s = 20s`)** of `output/retail_uc3_beauty_arc_90s/`, keeping **Act 1 (`Hook`, `20.00s`)**, **Act 3 (`Lifestyle Proof`, `29.88s`)**, and **Act 4 (`CTA`, `19.96s`)** untouched via `--resume`.
- **Visual Mandate:** **100% Product-Only Macro Showcase (`Zero Human Presence` — no person, face, hands, or silhouette)** featuring the exact standalone amber-gold `AURORA` dropper serum bottle (cylindrical amber glass, brushed-gold collar, white bulb cap, and label) on the warm backlit alabaster stone counter (`act2_alabaster_pedestal_ref.png`).
- **Audio Mandate:** **Off-camera background female voiceover (`VO`)** matching the warm, calm studio tone of Acts 1/3/4 and highlighting the **unique cold-pressed botanical formula** (`Shot 2.1`) and **deep-absorbing skin effectiveness** (`Shot 2.2`).
- **Deck Isolation:** Surgically refresh **only Slide 16 (`v17_s16_arc_90s_en` & `v17_s16_arc_90s_zh`)** in both 17-slide decks so concurrent edits on Slides 1–15 and 17 remain 100% untouched.

### Confirmed Step-by-Step Plan
- [ ] **Step 1 — Synthesize Standalone `#FFFFFF` Bottle-Only Anchor (`uc3_bottle_only_anchor.png`) Directly via Skill CLI (Zero Skill Code Edits):**
  - Invoke `uv run .agents/skills/vidgen-long-video/scripts/omni_direct.py generate-image --reference output/retail_uc3_beauty_arc_90s/refs/uc3_beauty_anchor.png ... --output output/retail_uc3_beauty_arc_90s/refs/uc3_bottle_only_anchor.png` as-is (keeping `Skill/vidgen-long-video/` 100% untouched) to isolate the exact closed amber-gold `AURORA` dropper serum bottle on pure `#FFFFFF` with zero humans/hands, and inspect via `read_file`.
- [ ] **Step 2 — Update `act_2_sku_hero` Storyboard & Re-Render Act 2 + 90s Master (`--resume`):**
  - Update `act_2_sku_hero` in `output/retail_uc3_beauty_arc_90s/scenes_storyboard.json` (`2 × 10s` unbroken product-macro shots on backlit alabaster stone + off-screen formula & effectiveness VO: *Shot 2.1:* `"Cold-pressed golden botanicals lock pure bio-active potency inside every drop."` / *Shot 2.2:* `"Micro-fine lipids absorb deeply to visibly plump and restore radiance."`).
  - Clear `act_2_sku_hero/` + `act_2_sku_hero_20s.mp4` and run `uv run Skill/vidgen-long-video/scripts/run_vidgen_workflow.py --scenes-json ... --resume --output-dir output/retail_uc3_beauty_arc_90s` to reuse Acts 1/3/4, render & AVU-verify Act 2 (`>= 0.80`, `WER = 0.0`, zero human presence), and re-stitch `output_master_90s.mp4`.
- [ ] **Step 3 — Rebuild `3×3` Contact Sheet & Sync Updated Artifacts to GCS:**
  - Rebuild `contact_sheet_arc_90s.png` (`upload_90s_arc_preview.py`), visually verify via `read_file` that `S2.1 SKU Hero` and `S2.2 SKU Hero` are 100% human-free product macro frames, and upload updated `act_2_sku_hero_20s.mp4`, `output_master_90s.mp4`, `contact_sheet_arc_90s.png`, `uc3_bottle_only_anchor.png`, and `run_manifest.json` to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_arc_90s_preview/`.
- [ ] **Step 4 — Surgical Slide 16 Refresh (`EN` & `ZH-CN`) & 4-Quadrant Active Vision Audit:**
  - Refresh **only** `v17_s16_arc_90s_en` and `v17_s16_arc_90s_zh` in place (replacing the embedded `contact_sheet_arc_90s.png` image, live Act 2 AVU score badge, master duration badge, and Slide 16 speaker notes while leaving Slides 1–15 & 17 untouched) and inspect exported `150 DPI` `en-16.png` & `zh-16.png` via `read_file`.


---

## [2026-11-09 01:46 UTC] Stage 1: Confirmed Final Plan (Run 11) — Add Bilingual Slide (`17 / 18`) on Gemini Omni 1.2 Flash Draft Mode (`360p Draft -> Agentic Loop -> Standalone Upscale`)

### Confirmed Decisions (`ask_question` `A1` & `A2`)
- **Slide Placement (`A1`):** Insert at **`Slide 17 / 18` (`insertionIndex = 16`)**, right before the Closing GTM Playbook (`Slide 18 / 18`), spanning both **Hosted ADK 2.0 Web Studio (`30s`)** and **Portable Zero-ADK Skill (`90s+`)**.
- **Visual Layout & Scope (`A2`):** **Split 40/60 M3 Phase Cards + Native-Vector Flowchart** (matching Slide 5's exact geometry, Google Slides only across `EN` & `ZH-CN`).

### Context & Verified GA Specifications (`gemini-omni-1.2-flash`, Nov 5, 2026 GA)
- **Official Capabilities & Unit Economics (`go/ai_omniflash_pitch` & `upscale-videos` Docs):**
  1. **Stage 1 — Fast Low-Cost Draft Generation (`360p` @ `\$0.02/s`):**
     - Render candidate `10s–15s` clips across Mode A (`reference_to_video`), Mode B (`image_to_video`), Mode C (`extend`), or two-frame interpolation at `response_format={"type": "video", "resolution": "360p"}` (`24 fps`, synchronized dialogue/SFX/score intact) — **`\$0.20` per `10s` shot** vs. `\$0.70` (`720p`), `\$1.00` (`1080p`), or `\$2.10` (`4K`).
  2. **Stage 2 — Closed-Loop Agentic QA & Iteration (`Gemini 3.8 Flash AVU` + `PromptOptimizer` / Auto-Heal):**
     - Run the entire closed-loop evaluation & Best-of-$K$ / `<FIRST_FRAME>+<LAST_FRAME>` retry loop (`MediaProcessing.AGENTIC` `QualityRaterAgent`, OpenCV seam/anchor MAE, Levenshtein `WER <= 0.35`, `score >= 0.80` gate) on `360p` drafts — **failed candidate takes are discarded at `\$0.20/clip` (`3.5×–5×` cheaper retry waste)**.
  3. **Stage 3 — Zero-Reasoning Standalone API Upscale (`task="upscale"`, `total_input_tokens: 0`):**
     - Promote **only** `PASSED (>= 0.80)` clips via `generation_config={"video_config": {"task": "upscale"}}` (`previous_interaction_id` or `gs://` video URI): `360p -> 720p / 1080p` (`2,896` / `5,792` output video tok/s) or `720p -> 1080p / 4K` (`11,584` tok/s), bypassing text reasoning (`total_input_tokens = 0`) so approved framing, SKU identity, lip-sync, and audio stay 100% locked before `80ms` stitching.
  - **End-to-End Cost Impact (`30s = 3 × 10s` Spot with `K = 3` Candidate Takes/Shot = `9` Renders, `3` Keepers at `1080p`):**
    - Naive `1080p` Agentic Loop: `9 × \$1.00 = \$9.00` (`\$6.00` spent on 6 discarded HD takes).
    - Omni 1.2 `Draft -> Agentic Loop -> Upscale`: `9 × \$0.20 (\$1.80) + 3 × Upscale = ~50%–65%` lower total compute cost (`5×` lower retry waste).

### Confirmed Step-by-Step Plan
- [ ] **Step 1 — Build Bilingual Split 40/60 M3 + Native-Vector Flowchart Slide (`v18_s17_draft_upscale_{en,zh}`):**
  - Match Slide 5's exact `720 × 405 pt` Split 40/60 geometry (`X=36, W=254` 3 M3 Phase Cards + `X=300, W=384` `1 pt` `RECTANGLE` Native-Vector Flowchart: **`① 360p Draft ($0.02/s)` $\rightarrow$ `② Gemini 3.8 AVU Agentic Loop (<0.80 Retry / Auto-Heal @ 360p)` $\rightarrow$ `③ Standalone task="upscale" (720p / 1080p / 4K, 0 Input Tokens)` $\rightarrow$ `④ 80ms Stitch Master`** + Bottom Unit Economics Banner).
- [ ] **Step 2 — Insert at `Slide 17 / 18` Across `EN` & `ZH-CN` Decks & Sync All `01 / 18 .. 18 / 18` Footers + Speaker Notes:**
  - Insert `v18_s17_draft_upscale_en` (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`) and `v18_s17_draft_upscale_zh` (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`) at `insertionIndex = 16` (shifting GTM Playbook to `18 / 18`), update all `XX / 17` slide footers to `XX / 18`, update Slide 16's `[TRANSITION]` cue to point to Slide 17, and attach tripartite speaker notes on Slide 17.
- [ ] **Step 3 — 4-Quadrant Active Vision Audit (`Slides 16, 17, 18` in `EN` & `ZH-CN`):**
  - Export PNG thumbnails of `Slide 17` (and `Slide 18` footer check) in both languages, visually verify single-line headers, arrow/connector precision, and zero text wrapping/clipping via `read_file`, and refresh `.url.json` deliverable bookmarks.


---

## [2026-11-09 01:55 UTC] Stage 1: Confirmed Final Plan (Run 12 `/btw`) — Upgrade `vidgen-long-video` Skill with Draft Mode (`360p -> Agentic Loop -> Upscale`) & Benchmark Speed on the 4-Act `90s` Beauty Commercial

### Confirmed Decisions (`ask_question` `A1` & `A2`)
- **Benchmark Baseline Method (`A1`):** **Draft Mode Run Only vs. Recorded `720p` Logs** — execute **only** the new `Draft Mode (360p -> AVU Loop -> 720p Upscale)` 4-Act beauty commercial (`output/retail_uc3_beauty_arc_90s_draft/`) via `.agents/skills/vidgen-long-video/scripts/run_vidgen_workflow.py` and compare against our recorded `720p` baseline logs (`~17.3m` / `1,039.76s` un-resumed 9-shot `720p` reference + per-act `310.84s` / `308.78s` 2-shot `720p` logs), leaving `output/retail_uc3_beauty_arc_90s/` untouched.
- **Stage 1 Plan Approval (`A2`):** Approved -> proceed to Stage 2 (`DEFINE.md`).

### Goal & Scope
- **Skill Upgrade (`Skill/vidgen-long-video` / `.agents/skills/vidgen-long-video`):** Add native **Gemini Omni 1.2 Flash Draft Mode (`360p` Draft $\rightarrow$ `Gemini 3.8 Flash` AVU Agentic Retry & `<FIRST_FRAME>+<LAST_FRAME>` Self-Healing Loop $\rightarrow$ Concurrent Standalone `task="upscale"` to `720p` / `1080p`)**, unit tests (`tests/unit/test_standalone_skill.py`), and `SKILL.md` documentation — with **zero** edits to `app/` or `src/` (ADK Studio).
- **4-Act `90s` Beauty Commercial Speed & Quality Comparison (Strictly via the Skill CLI):** Execute `.agents/skills/vidgen-long-video/scripts/run_vidgen_workflow.py` on the exact 4-Act `90s` beauty storyboard (`output/retail_uc3_beauty_arc_90s/scenes_storyboard.json`: `Hook 20s -> Product-Only SKU Hero 20s -> Lifestyle Proof 30s -> CTA 20s` = `9 × 10s` shots) into `output/retail_uc3_beauty_arc_90s_draft/` and compare **total generation wall-clock speed**, per-stage latency (`render_sec`, `avu_sec`, `repair_sec`, `upscale_sec`, `stitch_sec`), retry/auto-heal behavior, AVU quality scores, and compute cost against the `720p` baseline.

### Architectural Design (`Draft -> Agentic Loop -> Upscale`)
1. **`omni_direct.py` (`upscale_omni_clip_direct` + `upscale-clip` CLI):**
   - Implement `upscale_omni_clip_direct(video_bytes_or_b64, target_resolution="720p", source_resolution="360p", client=None) -> Tuple[bytes, Dict[str, Any]]` invoking `interactions.create` on `gemini-omni-1.2-flash` with:
     - `input=[{"type": "video", "data": video_b64, "mime_type": "video/mp4"}]`
     - `generation_config={"video_config": {"task": "upscale"}}`
     - `response_format={"type": "video", "resolution": target_resolution}`
   - Enforce supported GA upscale transitions (`360p -> 720p | 1080p`, `720p -> 1080p | 4k`; reject unsupported single-hop `360p -> 4k`) and record exact `upscale_sec` + zero-input-token telemetry.
2. **`run_vidgen_workflow.py` (`--draft-mode`, `--draft-resolution 360p`, `--max-parallel-upscales 3`):**
   - **Stage A — `360p` Draft & Closed-Loop Agentic QA (`R2V` + `5.0s` `video_extend` + `3.8 AVU` + `<FIRST_FRAME>+<LAST_FRAME>` Self-Heal):**
     - Render candidate takes, prefix-trim `video_extend` clips (`15s -> 10s`), run `QualityRaterAgent` (`gemini-3.8-flash` `MediaProcessing.AGENTIC`), and execute any `<FIRST_FRAME>+<LAST_FRAME>` scene repairs at `draft_resolution="360p"` (`$0.20` per `10s` take on the fast `368p` LDM).
   - **Stage B — Concurrent Standalone `task="upscale"` on Winning `10s` Shots Only:**
     - Archive each approved draft as `shot_{idx}_draft_360p.mp4`, then concurrently upscale **only the final winning prefix-trimmed `10s` clips** (`<= 15s` limit safe, `33%` fewer upscale tokens than untrimmed `15s` extensions, zero sequential dependency across shots) to target `resolution` (`720p` for apples-to-apples comparison with the baseline 4-act video, or `1080p`), write to `shot_{idx}.mp4`, refresh `shot_{idx}_{first,last}_frame.png`, and stitch `act_*_{dur}s.mp4` + `output_master_90s.mp4`.
   - **Stage C — Fine-Grained Stage Timing Telemetry (`run_manifest.json`):**
     - Record `draft_mode`, `draft_resolution`, `draft_and_avu_sec`, `interpolation_repair_sec`, `upscale_sec`, `stitch_and_seam_audit_sec`, and `elapsed_sec` at both scene and multi-scene levels (plus per-shot `render_sec`, `avu_sec`, `upscale_sec`).

### Confirmed Step-by-Step Plan (COMPLETED)
- [x] **Step 1 — Upgrade `Skill/vidgen-long-video` (`omni_direct.py`, `run_vidgen_workflow.py`, `SKILL.md`, `references/storyboard_spec.md`) & Unit Tests:**
  - Implement `upscale_omni_clip_direct` (`upscale-clip` subcommand), `--draft-mode` orchestration + stage timing telemetry in `run_vidgen_workflow.py`, update skill docs, and verify `100%` pass on `uv run --no-sync pytest tests/unit/test_standalone_skill.py -v` + live `10s` `360p -> 720p` smoke check.
- [x] **Step 2 — Run the 4-Act `90s` Beauty Commercial in Draft Mode via `.agents/skills/vidgen-long-video/scripts/run_vidgen_workflow.py`:**
  - Execute the 4-act `90s` beauty storyboard (`scenes_storyboard.json`, `9 × 10s` shots, `--max-parallel-scenes 2`, `--quality-threshold 0.80`) with `--draft-mode --resolution 720p` into `output/retail_uc3_beauty_arc_90s_draft/` (leaving `output/retail_uc3_beauty_arc_90s/` untouched).
- [x] **Step 3 — Visual Verification (`ffprobe` + `3×3` Contact Sheet) & Total Generation Speed / Cost / Quality Comparison Report:**
  - Verify `1280x720 @ 24fps` + intact stereo AAC audio via `ffprobe`, inspect `contact_sheet_arc_90s_draft.png` via `read_file`, log full CLI outputs & stage timings in `ACTION.md`, and present the head-to-head total speed, per-stage breakdown, retry/heal count, AVU quality score, and cost comparison against our recorded `720p` baseline logs.


---

## [2026-11-09 08:07 UTC] Stage 1: Confirmed Final Plan (Run 13) — Add 4-Act `90s` Beauty Draft Mode Speed, Quality & Cost Benchmark to Bilingual GTM Decks (`EN` & `ZH-CN`, `19` Slides Total)

### Confirmed Decisions (`ask_question` `A1` & `A2`)
- **Slide Presentation Strategy (`A1`):** **Both** — (1) enrich **Slide 17 (`17 / 19`, `v18_s17_draft_upscale_{en,zh}`)** in-place with our live measured per-clip latencies (`24.1s` R2V `3.4×` faster, `52.0s` Extend `2.1×` faster, `41.0s` `task="upscale"` `0` input tokens) & updated Unit Economics box, **AND** (2) insert a dedicated **Benchmark Proof Slide (`Slide 18 / 19`, `v19_s18_draft_bench_{en,zh}`)** immediately after Slide 17 pairing the `3×3` Draft-Mode Contact Sheet + clickable MP4 links on the left with the empirical Speed, Per-Stage Latency & Cost Comparison Table on the right (shifting Closing GTM `v12_s11_gtm_{en,zh}` to `Slide 19 / 19` and updating all `XX / 18` counters to `XX / 19`).
- **Stage 1 Plan Approval (`A2`):** Approved -> proceed to Stage 2 (`DEFINE.md`).

### Goal & Scope
- Upload the new Draft Mode 4-Act `90.33s` deliverables (`output_master_90s.mp4`, `act_{1..4}_*.mp4`, `act_2_sku_hero/shot_1_draft_360p.mp4` + `act_2_sku_hero/shot_1.mp4` `360p vs. 720p` pair, clean `contact_sheet_arc_90s_draft.png`, and `run_manifest.json`) to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_arc_90s_draft/` so clickable links work directly from Google Slides.
- Enrich `Slide 17 / 19` and insert `Slide 18 / 19` across both **English (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`)** and **Simplified Chinese (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`)** GTM decks, sync all `02 / 19 .. 19 / 19` footers + tripartite speaker notes, and pass the 4-Quadrant Active Vision Audit.

### Confirmed Step-by-Step Plan (COMPLETED)
- [x] **Step 1 — Upload Draft-Mode 4-Act `90s` Assets & Clean `3×3` Contact Sheet to GCS (`vital-octagon-19612-vidgen-showcase`):**
  - Render a clean zero-header-text `3×3` contact sheet (`H1.1..C4.2` matching Slide 16's clean aesthetic) and upload `output_master_90s.mp4`, all 4 act MP4s, `act_2_sku_hero/shot_1_draft_360p.mp4` (`360p` draft) + `act_2_sku_hero/shot_1.mp4` (`720p` upscaled), `contact_sheet_arc_90s_draft.png`, and `run_manifest.json` to `gs://vital-octagon-19612-vidgen-showcase/showcase/retail_uc3_beauty_arc_90s_draft/`.
- [x] **Step 2 — Enrich `Slide 17 / 19` & Insert Dedicated Benchmark Slide `18 / 19` Across `EN` & `ZH-CN` Decks:**
  - Rebuild `v18_s17_draft_upscale_{en,zh}` (`17 / 19`) with live measured latencies (`24.1s` R2V / `52.0s` Extend / `41.0s` Upscale) and insert `v19_s18_draft_bench_{en,zh}` at `insertionIndex = 17` (`18 / 19`, shifting Closing GTM to `19 / 19`), embedding `contact_sheet_arc_90s_draft.png`, clickable MP4 buttons (`90.33s` Draft Master, `360p` Draft vs. `720p` Upscaled Bottle Macro pair, High-Res Contact Sheet), 3 top KPI pills (`3.4×` R2V · `~1.5×` Total Speedup · `3.5×–5×` Lower Retry Waste), and the 7-row empirical comparison table, syncing all `XX / 19` footers & tripartite speaker notes.
- [x] **Step 3 — Blocking 4-Quadrant Active Vision Audit (`Slides 17, 18, 19` in `EN` & `ZH-CN`) & URL Deliverable Sync:**
  - Export PNG thumbnails (`en_slide-17.png`, `en_slide-18.png`, `en_slide-19.png`, `zh_slide-17.png`, `zh_slide-18.png`, `zh_slide-19.png`) via `gslides readonly export-thumbnail`, inspect via `read_file` to verify single-line headlines, clean padding, working links, and zero text overflow/collision, and create/update `.url.json` deliverable bookmarks (`UserFacing: true`).


---

## [2026-11-09 08:57 UTC] Stage 1: Confirmed Final Plan (Run 14) — Update Documentation (`README.md`, `doc/features.md`, `interaction_explained.md`), Run Full `72`-Test Suite, Commit & Push to `origin/main`

### Confirmed Decisions (`ask_question` `A1` & `A2`)
- **Documentation Scope (`A1`):** Update `README.md`, `doc/features.md`, and `interaction_explained.md`, run all `72` unit & integration tests, commit to `main`, and push to `origin/main`.
- **Stage 1 Plan Approval (`A2`):** Approved -> proceed to Stage 2 (`DEFINE.md`).

### Audit of Outdated Repository Docs & Current Git State
- **Git Branch & Modified Files (`main` tracking `origin/main` `git@github.com:hillxcyu/vidgen.git`):**
  - `Skill/vidgen-long-video/SKILL.md`, `Skill/vidgen-long-video/references/storyboard_spec.md`, `Skill/vidgen-long-video/scripts/omni_direct.py`, `Skill/vidgen-long-video/scripts/run_vidgen_workflow.py`, `tests/unit/test_standalone_skill.py`, plus `PLAN.md`, `DEFINE.md`, `ACTION.md`.
- **Documentation Gaps Identified:**
  1. **`README.md`:** Still shows early I2V-only architecture & stale `23/23 Passed` badge (now **`72/72` unit + integration tests**). Missing **Dual Delivery Tracks** (`Hosted ADK 2.0 Web Studio` Modes A/B/C/Hybrid + Auto-Rater v2 + Master Seam Critic **and** `Portable Zero-ADK Skill` in `Skill/vidgen-long-video` / `.agents/skills/vidgen-long-video` with `--scenes-json` `90s+` multi-act orchestration, `<FIRST_FRAME>+<LAST_FRAME>` self-healing, `--resume`, and `--draft-mode` `360p -> 3.8 AVU -> standalone task="upscale"`), plus `Skill/` in the repository tree.
  2. **`doc/features.md`:** Still lists only 12 early prototype features — missing Modes A/B/C/Hybrid (`#FFFFFF` `reference_to_video`, `5.0s` audio-intact `video_extend` + OpenCV pixel-MAE prefix trim, `80ms` `xfade`/`acrossfade`), Observation-First Auto-Rater v2 (`gemini-3.8-flash` `MediaProcessing.AGENTIC`, `WER` + `trailing_rms_db` guardrails, Best-of-$K$, Master Seam Critic), and the Standalone Zero-ADK Skill (`--scenes-json`, `<FIRST_FRAME>+<LAST_FRAME>` auto-heal, `--draft-mode` `task="upscale"`).
  3. **`interaction_explained.md`:** Still cites legacy `gemini-3.7-flash` and `gemini-omni-1.1-flash-preview` instead of GA `gemini-3.8-flash` (`MediaProcessing.AGENTIC`) and `gemini-omni-1.2-flash` (`R2V`, `<FIRST_FRAME>`, `5.0s` `extend`, `<FIRST_FRAME>+<LAST_FRAME>`, and `task="upscale"`).

### Confirmed Step-by-Step Plan
- [ ] **Step 1 — Refresh Repository Documentation (`README.md`, `doc/features.md`, `interaction_explained.md`):**
  - Update `README.md` (`72/72` Pytest badge, Dual-Track ADK 2.0 Studio + Portable Zero-ADK Skill overview, Modes A/B/C/Hybrid, Auto-Rater v2 `MediaProcessing.AGENTIC`, `--scenes-json` `90s+` auto-healing, `--draft-mode` `360p -> AVU -> task="upscale"` quickstart, and updated repo tree).
  - Update `doc/features.md` and `interaction_explained.md` to reflect GA `gemini-omni-1.2-flash`, `gemini-3.8-flash` (`MediaProcessing.AGENTIC`), Modes A/B/C/Hybrid, Auto-Rater v2, and Draft Mode upscaling (keeping all public-repo docs free of internal corp URLs or secrets).
- [ ] **Step 2 — Run Full Pre-Commit Test Suite (`72` Unit + Integration Tests) & Hygiene Audit:**
  - Execute `uv run --no-sync pytest tests/unit tests/integration -v` and confirm `72/72` pass (`100%`), plus inspect `git diff --staged` to verify zero untracked media/secrets.
- [ ] **Step 3 — Commit with Comprehensive Commit Message & Push to `origin/main`:**
  - Stage all updated skill, test, doc, and workflow files, create a detailed commit (`Done by: gemini-cli`, `TEST=uv run pytest tests/unit tests/integration`, problem & solution summary per `<RULE[user_global]>`), and push cleanly to `origin main`.
