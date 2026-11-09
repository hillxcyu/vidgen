# 🎬 vidgen — Feature List & Technical Implementation

This document maintains a comprehensive list of all implemented features in **vidgen-omni** (across both the **Hosted Google ADK 2.0 Web Studio** and the **Portable Zero-ADK `vidgen-long-video` Skill**), along with a concise technical description of how each capability is realized.

---

## 🚀 Core Architecture & Dual Delivery Tracks

1. **Google ADK 2.0 Multi-Agent Studio (`app/`)**
   - **Technical Implementation:** Coordinates specialized ADK 2.0 `LlmAgent` instances (`ScreenwriterAgent`, `StoryboarderAgent`, `PromptOptimizerAgent`, `HealthCheckerAgent`, `QualityRaterAgent`, and `vidgen_orchestrator`) on `gemini-3.8-flash` with isolated sub-agent fallback so sub-agent sessions never accidentally trigger parent `transfer_to_agent` loops.

2. **Portable Zero-ADK Long-Video Skill (`Skill/vidgen-long-video/` & `.agents/skills/vidgen-long-video`)**
   - **Technical Implementation:** Packages standalone PEP-723 `uv run` scripts (`media_ops.py`, `omni_direct.py`, `run_vidgen_workflow.py`) with zero `google.adk` or `google.cloud.storage` dependencies, enabling local `20s–90s+` multi-shot and multi-scene production directly via `google-genai`.

3. **Decoupled Async Session Management & Cross-Instance Persistence**
   - **Technical Implementation:** Runs long-lived generation pipelines inside background `asyncio.Task` workers bound to `InMemorySessionService`, persisting state snapshots to disk and GCS for seamless page-refresh reconnection.

4. **Vertex AI Application Default Credentials (`location="global"`)**
   - **Technical Implementation:** Authenticates `google.genai.Client(vertexai=True, location="global")` via ADC / IAM service accounts (with automatic `.env` / `GEMINI_API_KEY` fallback) and `240s` rater / `600s` video generation HTTP timeouts plus exponential backoff on `429`/`503`/`504`.

---

## 🎥 Continuity Modes & Generative Video Engineering (`gemini-omni-1.2-flash` GA)

5. **Mode A — Parallel `#FFFFFF` Studio-White Reference-to-Video (`reference`)**
   - **Technical Implementation:** Passes explicit `generation_config={"video_config": {"task": "reference_to_video"}}` + `response_format` across concurrent `asyncio.Semaphore` workers, paired with OpenCV `detect_r2v_first_frame_lock` (`Frame-0 MAE >= 12.0`) to guarantee scenes open inside the target environment rather than echoing the white backdrop.

6. **Mode B — Pixel-Locked `<FIRST_FRAME>` Image-to-Video Chaining (`i2v_chaining`)**
   - **Technical Implementation:** Anchors Shot 1 via `#FFFFFF` R2V, then extracts each shot's terminal PNG via OpenCV and passes `generation_config={"video_config": {"task": "image_to_video"}}` (stripping `# References` and `Character A` tags to prevent R2V override and lock `Frame-0 MAE < 4.5`).

7. **Mode C — `5.0s` Audio-Intact Temporal Video Extension (`video_extend`)**
   - **Technical Implementation:** Extracts a `5.0s` (`120f @ 24fps`, `48kHz` stereo AAC) trailing subclip for `task="extend"`, aligns prefix trimming (`[-0.45s, +0.25s]`) via OpenCV pixel MAE against the prior shot's `last_frame.png` to eliminate 4-frame VAE chunking drift, and automatically loops the final `1.4s` ambient room-tone bed if prior dialogue triggers speech-edit blocks.

8. **Mode D & Hierarchical Multi-Scene `90s+` Orchestration (`hybrid` / `--scenes-json` / `--resume`)**
   - **Technical Implementation:** Choreographs multi-act commercials combining `gemini-nano-banana-2.1` architectural scene plates (filtering `part.thought == True` drafts), product-only or spokesperson `#FFFFFF` anchors, within-scene `video_extend`, and `--resume` per-scene/per-shot checkpoint recovery.

9. **Autonomous `<FIRST_FRAME> + <LAST_FRAME>` Two-Frame Interpolation Self-Healing**
   - **Technical Implementation:** Automatically regenerates any sub-threshold scene shot (`score < 0.80` or rough scene seam) via `10s` two-frame keyframe interpolation locked between `shot_{k-1}_last_frame.png` and `shot_{k+1}_first_frame.png` (or synthesized grounded opening/closing plates), archiving `shot_{k}_failed_before_heal.mp4` whenever the healed take improves the AVU score.

10. **Omni 1.2 Draft Mode (`--draft-mode`: `360p` Draft → Agentic Loop → Standalone `task="upscale"`)**
    - **Technical Implementation:** Executes all candidate renders (`R2V`, `I2V`, `extend`, and interpolation heals) and `3.8 AVU` evaluations at `360p` (`$0.02/s`, up to `3.4×` faster per R2V shot), archives `shot_{k}_draft_360p.mp4`, and concurrently promotes only winning prefix-trimmed `10s` clips via zero-reasoning `task="upscale"` (`total_input_tokens: 0`) to `720p`, `1080p`, or `4k`.

11. **Duration-Locked `80ms` Equal-Power Audio/Video Crossfade Stitching**
    - **Technical Implementation:** Normalizes clip frame rates/timebases, pads/trims audio streams to exact video duration, and stitches multi-shot sequences with synchronized `80ms` `xfade=transition=fade` and `acrossfade=d=0.08:c1=qsin:c2=qsin` (defaulting to `0.0s` clean cuts across multi-location R2V montages and scene boundaries).

---

## 🔍 Observation-First Auto-Rater v2 & Audio/Visual Guardrails (`gemini-3.8-flash` AVU)

12. **Server-Side Agentic Video Understanding (`MediaProcessing.AGENTIC`) + High-Res Keyframes**
    - **Technical Implementation:** Attaches `types.Part(..., media_processing=types.MediaProcessing.AGENTIC)` (`google:load_video` dynamic frame zoom, verified via `avu_tool_use_tokens`) alongside captioned `CANONICAL REFERENCE ANCHOR`, `PRIOR SHOT TERMINAL FRAME`, and `KEY FRAME A/M/B` PNG stills.

13. **Observation-First Schema & Deterministic Speech/Cut Score Caps**
    - **Technical Implementation:** Enforces `property_ordering` (`opening_environment_observed`, `heard_transcript`, `speech_end_sec`, `detected_internal_cuts` populated before `score`), applies deterministic Levenshtein `transcript_wer <= 0.35`, trailing `0.20s` `trailing_rms_db <= -26 dBFS` speech-cutoff caps, and internal jump-cut/dissolve penalties, and checkpoints the monotonic **Best-of-$K$** clip.

14. **Post-Stitch Master Seam Critic (`evaluate_stitched_master`)**
    - **Technical Implementation:** Inspects every `[t_cut - 1.5s, t_cut + 1.5s]` transition window in the stitched MP4 via `gemini-3.8-flash` (`MediaProcessing.AGENTIC`) to audit visual smoothness, voice timbre consistency, and loudness continuity.

---

## 📊 Cloud Storage, Real-Time Web Studio & Controls

15. **Showcase Run Pinning & Timestamp-Aware GCS Manifest Merging**
    - **Technical Implementation:** Uploads MP4s, frames, and `run_manifest.json` with `cache_control="no-cache, max-age=0"` and merges GCS manifests over container seed manifests using `pinned_at` recency comparison, proxying media through `/api/gcs/{bucket}/{blob_path}`.

16. **Real-Time SSE Trajectory Visualizer & Manual Workflow Cancellation**
    - **Technical Implementation:** Streams live agent hand-offs, AVU scores, and stage timings over SSE while exposing `POST /api/pipeline/stop/{session_id}` to cancel active `asyncio.Task` pipelines cleanly on user stop.

---

*Note: Update this document whenever new features or technical components are added to the codebase.*
