---
name: vidgen-long-video
description: >-
  Generates, chains, audits, repairs, upscales, and stitches multi-shot and hierarchical multi-scene
  long-form commercials (`20s–90s+`, including Mode A parallel #FFFFFF Reference-to-Video,
  Mode B <FIRST_FRAME> I2V chaining, Mode C 5.0s audio-intact video_extend, Mode D hybrid
  choreography, `--scenes-json` hierarchical multi-act scenes with `<FIRST_FRAME>+<LAST_FRAME>`
  two-frame interpolation self-healing, and `--draft-mode` `360p` Draft -> Agentic Loop ->
  standalone `task="upscale"` to `720p`/`1080p`/`4k`) using direct Google GenAI SDK calls
  (gemini-omni-1.2-flash + gemini-3.8-flash with Agentic Video Understanding +
  gemini-nano-banana-2.1 reference plates) and deterministic OpenCV/FFMPEG seam & audio tools—without ADK.
---

# Standalone Multi-Shot Long-Video Production (`vidgen-long-video`)

Self-contained, **zero-ADK** workflow for producing continuity-locked multi-shot videos (`20s–60s+`) locally using direct `google-genai` SDK calls (`gemini-omni-1.2-flash` + `gemini-3.8-flash` with `MediaProcessing.AGENTIC`) and deterministic OpenCV/FFMPEG scripts.

## Prerequisites & Authentication

1. **System binaries:** `ffmpeg` and `ffprobe` on `PATH`; Python `>= 3.10` (`uv` recommended for zero-setup PEP 723 execution, or `pip install -r requirements.txt`).
2. **Authentication (either backend works automatically):**
   - **Vertex AI (ADC — recommended):**
     ```bash
     export GOOGLE_GENAI_USE_VERTEXAI=True
     export GOOGLE_CLOUD_PROJECT="{your_gcp_project}"
     export GOOGLE_CLOUD_LOCATION="global"
     ```
     *(If unset, `omni_direct.py` also checks `~/gcp.env` automatically.)*
   - **Gemini API (AI Studio):** `export GEMINI_API_KEY="{your_api_key}"`

Set `SKILL_DIR` to the folder containing this `SKILL.md` (e.g., `Skill/vidgen-long-video` or `.agents/skills/vidgen-long-video`):

```bash
SKILL_DIR="Skill/vidgen-long-video"
```

---

## Step 1: Choose the Right Continuity Mode

| Mode (`--mode`) | Shot 1 Conditioning | Shots 2..N Conditioning | When to Use | Default Stitch |
| :--- | :--- | :--- | :--- | :--- |
| **`video_extend`** *(Mode C)* | `#FFFFFF` R2V (`reference_to_video`) | `5.0s` audio-intact `<VIDEO_0>` tail + `task="extend"` + OpenCV MAE prefix trim | **Same-space single-take commercials (`20s–30s`)** needing continuous motion momentum, ambient acoustics, and locked voice timbre. | `80ms` `xfade` + `acrossfade` |
| **`i2v_chaining`** *(Mode B)* | `#FFFFFF` R2V (`reference_to_video`) | Prior shot `last_frame.png` via `<FIRST_FRAME>` | **Sequential camera progressions** starting from the exact terminal frame pixel state without echoing a `5s` video tail. | `80ms` `xfade` + `acrossfade` |
| **`reference`** *(Mode A)* | `#FFFFFF` R2V (`reference_to_video`) | Parallel `#FFFFFF` R2V (`asyncio.Semaphore`) | **Multi-location montages** (e.g., street -> cafe -> studio) keeping the same hero person/SKU across distinct scenes at ~3x wall-clock speed. | `0.0s` hard-cut |
| **`hybrid`** *(Mode D)* | Per-shot `mode_override` | Mix `video_extend` within acts + `reference` across act breaks | **Multi-act commercials** combining seamless within-room extension with clean location switches (see [storyboard_spec.md](references/storyboard_spec.md)). | `80ms` `xfade` + `acrossfade` |

---

## Step 2: Run the End-to-End Standalone Pipeline

`scripts/run_vidgen_workflow.py` executes storyboarding (`gemini-3.8-flash`), prompt optimization, `gemini-omni-1.2-flash` generation, OpenCV R2V/seam guards, Auto-Rater v2 (`MediaProcessing.AGENTIC`) with monotonic **Best-of-$K$** checkpointing, FFMPEG stitching, and the **Post-Stitch Master Seam Critic**—writing all MP4s, frames, and `run_manifest.json` to `--output-dir`.

### A. 30s Single-Take Hero Commercial (`mode="video_extend"`, `3 × 10s`)
```bash
uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
  --prompt "A woman in a cream satin blazer applies golden facial oil in a sunlit stone bathroom, continuous single-take camera glide" \
  --reference path/to/studio_white_anchor.png \
  --mode video_extend \
  --shots 3 \
  --duration 10 \
  --resolution 720p \
  --voice-transcript "One golden drop awakens pure radiance. Silky botanicals absorb weightlessly into skin. Effortless luminosity from morning to night." \
  --max-attempts 3 \
  --output-dir ./output/beauty_extend_30s
```

### B. Parallel Multi-Location SKU Montage (`mode="reference"`, `3 × 10s` Concurrent)
```bash
uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
  --prompt "Dynamic 3-scene urban running footwear commercial across rain-slicked asphalt, concrete stairs, and sunset track" \
  --reference path/to/shoe_white_bg.png \
  --mode reference \
  --shots 3 \
  --max-parallel 3 \
  --output-dir ./output/footwear_r2v_30s
```

### C. Pre-Structured Hybrid Storyboard (`--storyboard-json`)
Read [storyboard_spec.md](references/storyboard_spec.md) for the JSON schema, then run:
```bash
uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
  --storyboard-json path/to/storyboard.json \
  --reference path/to/studio_white_anchor.png \
  --mode hybrid \
  --output-dir ./output/apparel_hybrid_30s
```

### D. Hierarchical Multi-Scene Long Video (`90s = 3 Scenes × 30s` with `<FIRST_FRAME>+<LAST_FRAME>` Interpolation Repair)
Use `--scenes-json` when producing `60s–120s+` multi-chapter videos where each scene opens via R2V (`[hero_anchor.png, scene_i_ref.png]`), extends within-scene via `video_extend`, audits the `30s` scene + shots via `gemini-3.8-flash` (`MediaProcessing.AGENTIC`), and automatically regenerates any sub-threshold shot (`< 0.80`) using `<FIRST_FRAME> + <LAST_FRAME>` two-frame interpolation before stitching `output_master_90s.mp4`:
```bash
# Optional: generate people-free 16:9 architectural scene plates via gemini-nano-banana-2.1
uv run "$SKILL_DIR/scripts/omni_direct.py" generate-image \
  --prompt "Sunlit beige travertine spa bathroom vanity with warm morning light, architectural interior, no people" \
  --aspect-ratio 16:9 \
  --output ./output/beauty_90s/refs/scene1_ref.png

# Run 3 scenes (max 2 scenes in parallel) -> rate -> repair via <FIRST_FRAME>+<LAST_FRAME> -> stitch 90s master
uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
  --scenes-json path/to/scenes_storyboard.json \
  --max-parallel-scenes 2 \
  --quality-threshold 0.80 \
  --output-dir ./output/beauty_90s
```

### E. Fast Low-Cost Draft Mode (`--draft-mode`: `360p` Draft → Agentic Loop → Standalone `task="upscale"`)
Pass `--draft-mode` (default `--draft-resolution 360p`) to execute all candidate renders (`R2V`, `i2v_chaining`, `5.0s` `video_extend` + prefix trim), `gemini-3.8-flash` AVU evaluations, Best-of-$K$ retries, and `<FIRST_FRAME>+<LAST_FRAME>` self-heals at **`360p` (`$0.02/s`)**, then concurrently promote **only** the winning `10s` clips via zero-reasoning standalone `task="upscale"` (`total_input_tokens: 0`) to `--resolution 720p` or `1080p` (`--draft-resolution 720p --resolution 4k` for `4K`):
```bash
uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
  --scenes-json path/to/scenes_storyboard.json \
  --draft-mode \
  --draft-resolution 360p \
  --resolution 720p \
  --max-parallel-scenes 2 \
  --max-parallel-upscales 3 \
  --quality-threshold 0.80 \
  --output-dir ./output/beauty_90s_draft
```

### Output Deliverables in `--output-dir`
- `shot_1.mp4 .. shot_N.mp4`: Best-of-$K$ winning clips at target `--resolution` (plus `shot_1_draft_360p.mp4 ..` archived alongside when `--draft-mode` is active).
- `shot_1_first_frame.png`, `shot_1_last_frame.png ..`: Boundary stills for visual inspection or downstream chaining.
- `output_stitched_<Total>s.mp4` / `output_master_<Total>s.mp4`: Final duration-locked, audio-normalized master MP4.
- `run_manifest.json`: Full per-shot scores, `transcript_wer`, `seam_mae`, `avu_tool_use_tokens`, stage timing breakdown (`draft_and_avu_sec`, `interpolation_repair_sec`, `upscale_sec`, `stitch_and_seam_audit_sec`, `elapsed_sec`), and `master_seam_report`.

---

## Step 3: Granular Direct Model & OpenCV/FFMPEG Subcommands

When debugging a single shot, re-trimming a seam, or running Auto-Rater v2 standalone on an existing MP4, invoke the modular scripts directly:

### Direct Model & AVU Rater CLI (`scripts/omni_direct.py`)
```bash
# 1. Generate a single R2V, <FIRST_FRAME>, or extended clip
uv run "$SKILL_DIR/scripts/omni_direct.py" generate-clip \
  --prompt "Smooth close-up tracking shot in sunlit loft" \
  --reference path/to/anchor.png \
  --dialogue "Crafted for modern movement." \
  --output ./output/single_shot.mp4

# 2. Run Auto-Rater v2 (gemini-3.8-flash + MediaProcessing.AGENTIC + KEY FRAME A/M/B + WER/RMS caps)
uv run "$SKILL_DIR/scripts/omni_direct.py" rate-clip \
  --video ./output/single_shot.mp4 \
  --prompt "Smooth close-up tracking shot in sunlit loft" \
  --dialogue "Crafted for modern movement." \
  --reference path/to/anchor.png

# 3. Audit a stitched multi-shot master across [t_cut - 1.5s, t_cut + 1.5s] seam windows
uv run "$SKILL_DIR/scripts/omni_direct.py" rate-master \
  --video ./output/beauty_extend_30s/output_stitched_30s.mp4 \
  --shots 3 \
  --reference path/to/anchor.png

# 4. Standalone zero-reasoning video upscale (360p -> 720p/1080p, or 720p -> 1080p/4k; <= 15s)
uv run "$SKILL_DIR/scripts/omni_direct.py" upscale-clip \
  --video ./output/single_shot_360p.mp4 \
  --source-resolution 360p \
  --target-resolution 720p \
  --output ./output/single_shot_720p.mp4
```

### Deterministic OpenCV & FFMPEG CLI (`scripts/media_ops.py`)
```bash
# Extract 5.0s 48kHz stereo AAC tail for task="extend"
uv run "$SKILL_DIR/scripts/media_ops.py" extract-tail --video shot_1.mp4 --seconds 5.0 --output shot_1_tail.mp4

# Frame-exact OpenCV pixel-MAE prefix trim (eliminates 4-frame VAE chunking seam drift)
uv run "$SKILL_DIR/scripts/media_ops.py" trim-seam --video raw_ext.mp4 --trim-seconds 5.0 \
  --ref-last-frame shot_1_last_frame.png --output shot_2_trimmed.mp4

# Check R2V #FFFFFF Frame-0 lock (MAE < 12.0) or post-seam jump-cut (peak MAE > 28.0)
uv run "$SKILL_DIR/scripts/media_ops.py" check-r2v --video shot_1.mp4 --reference anchor.png
uv run "$SKILL_DIR/scripts/media_ops.py" check-seam --video shot_2_trimmed.mp4 --ref-last-frame shot_1_last_frame.png

# Measure trailing 0.20s RMS speech cutoff (-26 dBFS threshold) & stitch clips with 80ms xfade/acrossfade
uv run "$SKILL_DIR/scripts/media_ops.py" analyze-audio --video shot_1.mp4
uv run "$SKILL_DIR/scripts/media_ops.py" stitch --videos shot_1.mp4 shot_2.mp4 shot_3.mp4 \
  --crossfade 0.08 --output output_stitched_30s.mp4
```

---

## Critical Gotchas & Empirical Guardrails (Why Each Exists)

1. **Isolate Reference Subjects on `#FFFFFF` + Pass `task="reference_to_video"` Explicitly:**
   - Attaching a `#FFFFFF` portrait/SKU image to `interactions.create` *without* `generation_config={"video_config": {"task": "reference_to_video"}}` and `response_format={"type": "video", ...}` causes Omni to treat the image as `<FIRST_FRAME>`, locking Frame 0 onto the white studio backdrop (`MAE = 2.9–4.8`). `omni_direct.py` sets both fields automatically and `detect_r2v_first_frame_lock` rejects any clip with `Frame-0 MAE < 12.0`.
2. **Never Combine `# References` (`reference_images_b64`) with `<FIRST_FRAME>` or `<VIDEO_0>`:**
   - Passing `reference_images_b64` alongside `<FIRST_FRAME>` on Shots `2..N` causes Omni to override first-frame pixel locking with fresh R2V synthesis (`seam MAE` jumps from `~2.5` to `55–99`). Passing `type: "image"` alongside `type: "video"` on Vertex AI `task="extend"` returns empty outputs (`outputs: []`). Always anchor Shot 1 via R2V, then condition Shots `2..N` solely on `<FIRST_FRAME>` or `<VIDEO_0>`.
3. **Never Blind-Trim `video_extend` Clips with `-ss 5.0`:**
   - Because Omni's video tokenizer operates in 4-frame VAE chunks, the echoed terminal frame of a `5.0s` (`120f @ 24fps`) tail lands anywhere in frames `117..120` (`4.875s–5.000s`). Blind `-ss 5.0` cuts miss the boundary (`MAE = 16–70`); `trim_video_prefix` scans `[-0.45s, +0.25s]` via OpenCV pixel MAE and cuts with `select='gte(n,best_idx)'` (`MAE = 2.7–8.1`).
4. **Keep Spoken Dialogue `<= 12` Words/Shot & Preserve `5.0s` Tail Audio:**
   - Pacing each `10s` shot's line under `12` words ensures speech completes before `8.0s` (`analyze_clip_audio_tail` flags cutoffs when trailing `0.20s` `trailing_rms_db > -26 dBFS`). Keeping `strip_audio=False` on `<VIDEO_0>` preserves speaker voice timbre across shots; if earlier speech triggers `"unable to process speech edits"`, `omni_direct.py` automatically loops the tail's final `1.4s` ambient room tone before retrying.
5. **Verify AVU Execution via `avu_tool_use_tokens`:**
   - On `gemini-3.8-flash`, `create_agentic_video_part(..., media_processing="AGENTIC")` triggers server-side `google:load_video` coarse-to-fine inspection while captioned `KEY FRAME A/M/B` PNG stills overcome low-token video spatial quantization for fine SKU/logo checks. Confirm `deterministic_telemetry.avu_tool_use_tokens > 0` in `run_manifest.json` on live runs.
6. **Standalone Upscale (`task="upscale"`) Resolution Hops & `15s` Trim Rule:**
   - `gemini-omni-1.2-flash` standalone upscaling (`generation_config={"video_config": {"task": "upscale"}}`, `total_input_tokens: 0`) supports `360p -> 720p | 1080p` and `720p -> 1080p | 4k` (`<= 15s` input duration; single-hop `360p -> 4k` and `1080p -> 4k` are unsupported). In `--draft-mode`, `run_vidgen_workflow.py` always upscales **prefix-trimmed `~10s` winning clips** rather than untrimmed `15s` raw `video_extend` outputs—saving `33%` upscale output tokens while staying safely below the `15.0s` cap.
