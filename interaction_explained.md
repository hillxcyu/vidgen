# Multi-Agent & Portable Skill Interaction Architecture Explained

This document explains how the AI agents, direct model wrappers, and deterministic OpenCV/FFMPEG modules in **vidgen-omni** interact to produce continuity-locked `30s–90s+` multi-shot commercials across both the **Google ADK 2.0 Web Studio (`app/`)** and the **Portable Zero-ADK Skill (`Skill/vidgen-long-video/`)**.

---

## 🤖 End-to-End Interaction Architecture

In the hosted studio (`app/agents/pipeline.py` & `app/agent.py`), agents coordinate through typed **Shared Session State** (`PipelineState` in `app/state.py`). In the standalone skill (`Skill/vidgen-long-video/scripts/run_vidgen_workflow.py`), the exact same stage contracts execute via direct `google.genai` SDK calls and structured Pydantic manifests (`WorkflowManifest` / `MultiSceneWorkflowManifest`).

```
                            [ USER BRIEF / STORYBOARD / #FFFFFF ANCHOR ]
                                                 │
                                                 ▼
                                ┌────────────────────────────────┐
                                │   1. SCREENWRITER AGENT        │ (gemini-3.8-flash)
                                └────────────────┬───────────────┘
                                                 │ Multi-Act Narrative Script
                                                 ▼
                                ┌────────────────────────────────┐
                                │   2. STORYBOARDER AGENT        │ (gemini-3.8-flash)
                                └────────────────┬───────────────┘
                                                 │ Structured Shot Specs (JSON)
                                                 ▼
                                ┌────────────────────────────────┐
                                │   3. PROMPT OPTIMIZER AGENT    │ (gemini-3.8-flash)
                                └────────────────┬───────────────┘
                                                 │ Single-Take / Mode-Aware Prompt
                                                 ▼
                                ┌────────────────────────────────┐
                                │   4. HEALTH CHECKER AGENT      │ (Safety & Brand Guardrails)
                                └────────────────┬───────────────┘
                                                 │ Approved Shot Payload
                                                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │         5. GENERATION, CONTINUITY CHAINING & OPTIONAL 360p DRAFT LOOP          │
 │                                                                                │
 │  • Mode A (reference):    #FFFFFF Anchor ──► task="reference_to_video"         │
 │  • Mode B (i2v_chaining): shot_{k-1}_last_frame.png ──► task="image_to_video"  │
 │  • Mode C (video_extend): 5.0s <VIDEO_0> tail ──► task="extend" + MAE trim     │
 │  • Draft Mode:            Render & iterate at 360p ($0.02/s)                   │
 └───────────────────────────────────────────────┬────────────────────────────────┘
                                                 │ Candidate MP4 + Keyframes A/M/B
                                                 ▼
                                ┌────────────────────────────────┐
                                │   6. QUALITY RATER v2 (AVU)    │ (gemini-3.8-flash AGENTIC)
                                │   Score < 0.80 ──► Best-of-K   │ + WER / Trailing RMS / MAE
                                │   or <FIRST_FRAME>+<LAST_FRAME>│
                                └────────────────┬───────────────┘
                                                 │ Winning Takes (>= 0.80)
                                                 ▼
                                ┌────────────────────────────────┐
                                │   7. OPTIONAL STANDALONE       │ (gemini-omni-1.2-flash)
                                │      UPSCALE (task="upscale")  │ 360p->720p/1080p | 720p->4k
                                └────────────────┬───────────────┘
                                                 │ Final HD / 4K Shot MP4s
                                                 ▼
                                ┌────────────────────────────────┐
                                │   8. 80ms FFMPEG STITCHER &    │ xfade + equal-power acrossfade
                                │      MASTER SEAM CRITIC (AVU)  │ Audits [t_cut-1.5s, t_cut+1.5s]
                                └────────────────┬───────────────┘
                                                 ▼
                                  [ output_stitched / master.mp4 ]
```

---

## 🔄 The 5 Core Interaction Mechanisms

### 1. Communication via Typed State & Structured Schemas
Agents and workflow stages exchange validated Pydantic models rather than free-form prose:
- **Screenwriter → Storyboarder:** Expands high-level commercial intent into chronological scenes (`StoryboardEntry` / `StoryboardEntrySpec` with `description`, `camera_angle`, `evaluation_criteria`, `spoken_dialogue`, and optional `mode_override`).
- **Prompt Optimizer → Omni 1.2 Flash:** Rewrites shot specs into single-take camera trajectories (`<= 12` spoken words per `10s` shot so narration finishes cleanly before `8.0s`).
- **Auto-Rater v2 → Prompt Optimizer / Interpolation Healer:** Emits `QualityEvaluationResult` with enforced `property_ordering` (`opening_environment_observed`, `heard_transcript`, `speech_end_sec`, `detected_internal_cuts`, `reason`, `score`, `verdict`, `feedback`).

---

### 2. Cross-Modal Continuity Hand-Offs (`gemini-omni-1.2-flash`)
Depending on the selected continuity mode, OpenCV/FFMPEG (`video_parser.py` / `media_ops.py`) prepares the exact conditioning payload for `interactions.create`:
1. **Mode A (`reference`):** Passes `#FFFFFF` isolated subject/SKU anchors with `generation_config={"video_config": {"task": "reference_to_video"}}`; `detect_r2v_first_frame_lock` verifies Frame 0 opens inside the target scene (`MAE >= 12.0`).
2. **Mode B (`i2v_chaining`):** Extracts `shot_{k-1}_last_frame.png` via OpenCV and passes it with `generation_config={"video_config": {"task": "image_to_video"}}` while omitting `# References` tags to prevent R2V override.
3. **Mode C (`video_extend`):** Extracts the final `5.0s` (`48kHz` stereo AAC intact) of Shot $k-1$ for `task="extend"`, then scans `[-0.45s, +0.25s]` on the returned `15s` clip via OpenCV pixel MAE against `shot_{k-1}_last_frame.png` to trim the echoed `5s` prefix with frame-level precision.
4. **Two-Frame Interpolation Self-Heal (`<FIRST_FRAME> + <LAST_FRAME>`):** In `--scenes-json` multi-scene workflows, any shot scoring `< 0.80` after initial generation is re-bridged between `shot_{k-1}_last_frame.png` and `shot_{k+1}_first_frame.png` (`task=None`, `3s–10s`) and accepted if its AVU score improves.

---

### 3. Closed-Loop Agentic Video QA (`gemini-3.8-flash` `MediaProcessing.AGENTIC`)
- Each candidate clip is audited with **both** `MediaProcessing.AGENTIC` (`google:load_video` dynamic temporal/spatial zoom) **and** full-resolution PNG stills (`KEY FRAME A` start, `KEY FRAME M` mid, `KEY FRAME B` end) plus ground-truth reference/boundary frames.
- Deterministic OpenCV/FFMPEG guardrails cap scores below `0.80` (`REATTEMPT_REQUIRED`) whenever `detected_internal_cuts > 0`, spoken `transcript_wer > 0.35`, or trailing `0.20s` audio RMS exceeds `-26 dBFS`, routing targeted feedback back into `PromptOptimizerAgent` while preserving the highest-scoring attempt (**Best-of-$K$**).

---

### 4. Draft-First Iteration & Zero-Reasoning Standalone Upscaling (`--draft-mode`)
- When `--draft-mode` is enabled, Stages 5–6 execute entirely at `resolution="360p"` (`$0.02/s`), allowing sub-threshold takes to be generated and discarded up to `3.4×` faster and `3.5×–5×` cheaper.
- Once all shots in a scene pass the Agentic Loop, Stage 7 invokes `gemini-omni-1.2-flash` concurrently with `generation_config={"video_config": {"task": "upscale"}}` (`total_input_tokens: 0`) on the prefix-trimmed `10s` winners to produce `720p`, `1080p`, or `4k` clips with locked SKU geometry, lip-sync, and audio.

---

### 5. Duration-Locked Stitching & Post-Stitch Master Seam Critic
- `stitch_videos` locks audio/video stream durations and applies `80ms` `xfade` + equal-power `acrossfade` across within-scene shots.
- Finally, `evaluate_stitched_master` inspects every `[t_cut - 1.5s, t_cut + 1.5s]` window in the stitched master MP4 via `gemini-3.8-flash` (`MediaProcessing.AGENTIC`) to certify visual, vocal, and acoustic continuity.
