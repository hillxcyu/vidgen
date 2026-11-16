---
name: vidgen-long-video
description: >-
  Directs, plans, generates, audits, self-heals, upscales, and stitches continuity-locked
  multi-shot and multi-act commercials and short films (20s to 120s+) without ADK using
  Gemini Omni 1.2 Flash, Gemini 3.8 Flash Agentic Video Understanding, Gemini 3.8 Flash TTS
  (with Third-Party Voice Generation audio-reference lip-sync and formant-ducked voiceover mixing),
  Nano Banana 2.1 scene plates, and deterministic OpenCV/FFMPEG seam tools. Use when producing
  multi-shot brand commercials, product videos, spoken spokesperson films, TPVG/TTS voice-conditioned
  videos, or long-form storyboards with automated quality gating and human-in-the-loop review.
  Don't use for audio-only podcast feeds without video output or Google Slides deck editing.
---

# Director-Grade Multi-Shot Long-Video Production (`vidgen-long-video`)

Self-contained, **zero-ADK** film and commercial production skill combining **Movie & Art Director craft**, a structured **`Plan → Define → Execute (& Verify / Iterate)`** workflow, **Dual Human-in-the-Loop (HITL) Gates**, a **10-Category GenMedia Defect Taxonomy**, **Mode E (`tpvg_tts`) `gemini-3.8-flash-tts` + Omni TPVG voice synthesis**, and **Omni 1.2 Draft → Agentic Loop → Standalone Upscale**.

## Reference Manuals (Read Before Designing Prompts or Specs)
- **[director_craft_guide.md](references/director_craft_guide.md):** Vision Profile calibration, focal-length psychology (`24mm–100mm macro`), `15°` & `180°` editorial rules, motivated lighting ratios (`2:1`/`4:1`/`8:1`), 3-color + forbidden-color theory, silent-camera prompt hygiene, and the **8-Layer Director Prompt Architecture**.
- **[genmedia_eval_rubric.md](references/genmedia_eval_rubric.md):** **10-Category GenMedia Defect Taxonomy**, observable `fails_if` rules, automatic retry remedies, `--check-spec` pre-flight validation, and HITL Gate 1 & Gate 2 escalation handling.
- **[storyboard_spec.md](references/storyboard_spec.md):** Full JSON schemas for `VisionProfileSpec`, `StoryboardEntrySpec`, `SceneSpec`, and Modes A–E (`reference`, `i2v_chaining`, `video_extend`, `hybrid`, `tpvg_tts`).

## Prerequisites & Authentication
1. **System binaries:** `ffmpeg` and `ffprobe` on `PATH`; Python `>= 3.10` (`uv` recommended for zero-setup PEP 723 execution).
2. **Vertex AI ADC (recommended — required for TPVG audio-reference input):**
   ```bash
   export GOOGLE_GENAI_USE_VERTEXAI=True
   export GOOGLE_CLOUD_PROJECT="{your_gcp_project}"
   export GOOGLE_CLOUD_LOCATION="global"
   # Set SKILL_DIR to the installed skill location (~/.gemini/config/..., /google/src/files/head/depot/..., or local .agents/skills/vidgen-long-video)
   SKILL_DIR="${SKILL_DIR:-$HOME/.gemini/config/skills/vidgen-long-video}"
   ```
   *(Gemini API `GEMINI_API_KEY` is also supported for Modes A–D; note that TPVG audio input requires an allowlisted Vertex AI project.)*

---

## The 3-Stage Director Workflow (`PLAN → DEFINE → EXECUTE`)

Never jump straight from a vague one-liner to expensive multi-minute video generation. Follow the 3-stage loop (pass `--auto-approve` only when the user explicitly requests an unattended end-to-end batch run):

### Stage 1: `PLAN` — Art Direction, Vision Profile & Continuity Strategy
1. Read [director_craft_guide.md](references/director_craft_guide.md) and choose the continuity/voice mode:
   - **Mode A (`reference`):** Parallel `#FFFFFF` R2V shots (`3s–15s`, `0.0s` hard-cuts) for multi-location montages.
   - **Mode B (`i2v_chaining`):** Shot 1 R2V → Shots `2..N` `<FIRST_FRAME>` `task="image_to_video"` (`3s–15s`).
   - **Mode C (`video_extend`):** Shot 1 R2V → Shots `2..N` `5.0s` `<VIDEO_0>` tail `task="extend"` (`3s–10s`) in one room.
   - **Mode D (`hybrid`):** Per-shot `mode_override` mixing `reference` across act breaks + `video_extend` within acts.
   - **Mode E (`tpvg_tts`):** **`gemini-3.8-flash-tts`** (`--tts-model gemini-3.8-tts` / `gemini-3.8-flash-tts`, `--tts-voice Kore`) generates studio `24 kHz` WAV voice tracks first → **`on_camera`** shots pass `<= 3.0s × 5` WAV chunks as TPVG `type: "audio"` R2V references (lip-synced in exact TTS voice) + TPVG-unlocked `video_extend`, while **`off_camera_vo`** shots (e.g., zero-human product macros) render pure diegetic foley and mix `-16 LUFS` TTS audio via `1100 Hz` formant-notched ducking.
2. Generate the structured **Vision Profile + Director Plan + Initial Storyboard**:
   ```bash
   uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
     --stage plan \
     --prompt "30s luxury botanical serum commercial: morning sanctuary hook, 100mm product-only macro formula showcase, and radiant close" \
     --reference path/to/studio_white_anchor.png \
     --mode tpvg_tts \
     --tts-voice Kore \
     --shots 3 \
     --output-dir ./output/serum_spot
   ```
   Inspect `./output/serum_spot/director_plan.md` and `./output/serum_spot/storyboard_defined.json` (verifying `style_anchor`, focal lengths, `color_palette`, `forbidden_colors`, `audio_mode`, and per-shot `fails_if`).

### Stage 2: `DEFINE` — Pre-Flight Spec Validation & Keyframe/Plate Contact Sheet (**HITL Gate 1**)
1. Validate speech WPM budgets (`<= 2.4 words/s`, finishing `~2s` before clip end), GA duration bounds (`3–15s` vs. `3–10s`), `15°` hard-cut angle variety, and reference files:
   ```bash
   uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
     --storyboard-json ./output/serum_spot/storyboard_defined.json \
     --vision-json ./output/serum_spot/director_plan.json \
     --reference path/to/studio_white_anchor.png \
     --check-spec \
     --output-dir ./output/serum_spot
   ```
2. Synthesize/collect people-free `16:9`/`9:16` scene plates (and standalone product-only `#FFFFFF` anchors for zero-human acts) and render **`plates_contact_sheet.png`**:
   ```bash
   uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
     --stage plates \
     --scenes-json path/to/scenes_storyboard.json \
     --output-dir ./output/serum_90s
   ```
3. **HITL Gate 1 (Pre-Render Pause):** View `plates_contact_sheet.png` via `read_file` first (regenerate any plate containing text, logos, or unintended people), then present `director_plan.md` + `plates_contact_sheet.png` to the user and wait for approval before Stage 3 (skip pause only when `--auto-approve` is set).

### Stage 3: `EXECUTE & VERIFY` — Closed-Loop Render, GenMedia Defect Remedies & **HITL Gate 2**
1. Execute full production (combine with `--draft-mode` to iterate at `360p` `$0.02/s` and standalone `task="upscale"` only winning clips to `720p`/`1080p`/`4k`):
   ```bash
   uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
     --stage execute \
     --storyboard-json ./output/serum_spot/storyboard_defined.json \
     --vision-json ./output/serum_spot/director_plan.json \
     --reference path/to/studio_white_anchor.png \
     --mode tpvg_tts \
     --tts-model gemini-3.8-tts \
     --tts-voice Kore \
     --tts-style "Warm, poised luxury skincare narrator" \
     --draft-mode \
     --draft-resolution 360p \
     --resolution 720p \
     --max-attempts 3 \
     --output-dir ./output/serum_spot
   ```
2. **Automated Verification & Self-Healing:**
   - Every candidate clip is audited by Auto-Rater v2 (`gemini-3.8-flash` `MediaProcessing.AGENTIC`) across the **10-Category GenMedia Defect Taxonomy** ([genmedia_eval_rubric.md](references/genmedia_eval_rubric.md)), injecting targeted director remedies on retries and `<FIRST_FRAME>+<LAST_FRAME>` interpolation self-healing on `--scenes-json` runs.
   - Generates `./output/serum_spot/qa_contact_sheet.png` (labeled with shot index, AVU score, verdict, and any defect codes) and audits cross-shot seams via the Master Seam Critic.
3. **HITL Gate 2 (Unresolved Defect Escalation):**
   - Always inspect `qa_contact_sheet.png` and `run_manifest.json` via `read_file`.
   - If any shot remains `< quality_threshold` (or master seam `< 0.75`) after retries/self-healing, the runner writes `escalation_report.json` with concrete `Option A (accept)` / `Option B (targeted shot edit + --resume)` / `Option C (swap plate/mode)` choices and exits with code **`2`** (`HUMAN_REVIEW_REQUIRED`, unless `--auto-approve` is set). Pause and ask the user how they want to direct the fix, then re-run with `--resume` so approved shots are reused untouched.

---

## Granular Direct Model, TTS/TPVG & OpenCV/FFMPEG Subcommands

### 1. Direct Model, TTS, TPVG & AVU CLI (`scripts/omni_direct.py`)
```bash
# Synthesize a 24kHz studio WAV voice track via gemini-3.8-flash-tts (alias: gemini-3.8-tts)
uv run "$SKILL_DIR/scripts/omni_direct.py" synthesize-tts \
  --text "Cold-pressed golden botanicals lock pure bio-active potency inside every drop." \
  --tts-model gemini-3.8-tts \
  --voice Kore \
  --style "Warm, poised luxury narrator" \
  --output ./output/vo_shot_1.wav

# Generate a single R2V clip with #FFFFFF image anchor + TPVG voice audio reference
uv run "$SKILL_DIR/scripts/omni_direct.py" generate-clip \
  --prompt "50mm medium close-up at eye level inside sunlit travertine bathroom. The camera movement itself is completely silent." \
  --reference path/to/anchor.png \
  --audio-ref ./output/vo_shot_1.wav \
  --dialogue "Every morning begins with one luminous golden drop." \
  --output ./output/shot_1_tpvg.mp4

# Re-voice / lip-sync an existing video clip via untasked TPVG V2V speech dubbing
uv run "$SKILL_DIR/scripts/omni_direct.py" dub-clip \
  --video ./output/shot_1.mp4 \
  --voice ./output/vo_shot_1.wav \
  --dialogue "Every morning begins with one luminous golden drop." \
  --output ./output/shot_1_dubbed.mp4

# Generate a 16:9/9:16 scene plate, audit a clip/master, or standalone upscale (<= 15s, 0 input tokens)
uv run "$SKILL_DIR/scripts/omni_direct.py" generate-image --prompt "Sunlit travertine vanity, no people" --output ./output/plate.png
uv run "$SKILL_DIR/scripts/omni_direct.py" rate-clip --video ./output/shot_1_tpvg.mp4 --prompt "..." --dialogue "..." --reference path/to/anchor.png
uv run "$SKILL_DIR/scripts/omni_direct.py" rate-master --video ./output/master.mp4 --shots 3 --shot-durations 10 8 10 --crossfade 0.08
uv run "$SKILL_DIR/scripts/omni_direct.py" upscale-clip --video ./output/draft_360p.mp4 --source-resolution 360p --target-resolution 720p --output ./output/up_720p.mp4
```

### 2. Deterministic OpenCV, Audio Duck-Mix & Contact Sheet CLI (`scripts/media_ops.py`)
```bash
# Mix off-camera TTS WAV (-16 LUFS) over diegetic video with 1100Hz vocal-formant notch + ducking
uv run "$SKILL_DIR/scripts/media_ops.py" mux-voiceover \
  --video ./output/macro_diegetic.mp4 \
  --voice ./output/vo_shot_2.wav \
  --output ./output/macro_voiced.mp4

# Build labeled plate or QA contact sheet (PNGs or MP4s)
uv run "$SKILL_DIR/scripts/media_ops.py" contact-sheet \
  --inputs ./output/shot_1.mp4 ./output/shot_2.mp4 ./output/shot_3.mp4 \
  --labels "S1 | 0.96 PASS" "S2 | 0.95 PASS" "S3 | 0.94 PASS" \
  --cols 3 \
  --output ./output/qa_contact_sheet.png

# Seam alignment, R2V/jump-cut checks, audio tail telemetry & 80ms xfade stitch
uv run "$SKILL_DIR/scripts/media_ops.py" extract-tail --video shot_1.mp4 --seconds 5.0 --output shot_1_tail.mp4
uv run "$SKILL_DIR/scripts/media_ops.py" trim-seam --video raw_ext.mp4 --trim-seconds 5.0 --ref-last-frame shot_1_last.png --output shot_2.mp4
uv run "$SKILL_DIR/scripts/media_ops.py" stitch --videos shot_1.mp4 shot_2.mp4 shot_3.mp4 --crossfade 0.08 --output master.mp4
```

---

## Top Empirical Guardrails
1. **Keep `#FFFFFF` R2V, `<FIRST_FRAME>` (`task="image_to_video"`), and `<VIDEO_0>` (`task="extend"`) Mutually Exclusive:** Combining `# References` with `<FIRST_FRAME>` overrides frame-locking (`MAE` jumps `~2.5 → 55–99`); attaching images or audio to `task="extend"` fails Vertex AI validation.
2. **TPVG Audio-Reference Chunking (`<= 3.0s × 5`):** Omni's `task="reference_to_video"` audio conditioning accepts up to `5 × 3.0s` WAV reference chunks (`split_wav_reference_chunks` slices longer `gemini-3.8-flash-tts` tracks automatically) and requires a TPVG-enabled Vertex AI project (`GOOGLE_CLOUD_LOCATION="global"`).
3. **OpenCV Pixel-MAE Prefix Trim Over Blind `-ss 5.0`:** 4-frame VAE chunking places the echoed `5.0s` tail boundary across frames `117..120`; always trim via `trim_video_prefix` (`select='gte(n,best_idx)'`).
4. **Upscale Trimmed Winners Only (`<= 15s`):** Standalone `task="upscale"` (`total_input_tokens: 0`) supports `360p → 720p|1080p` and `720p → 1080p|4k` (not single-hop `360p → 4k`). Always upscale prefix-trimmed clips (`3s–15s`).
