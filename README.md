# 🎬 vidgen-omni: Dual-Track Multi-Agent & Portable Skill Long-Video Pipeline

[![Google ADK 2.0](https://img.shields.io/badge/Google%20ADK-2.6.2-blue)](https://github.com/hillxcyu/vidgen)
[![Gemini Omni 1.2 Flash](https://img.shields.io/badge/Video%20Model-gemini--omni--1.2--flash%20(GA)-4285F4)](https://cloud.google.com/vertex-ai)
[![Gemini 3.8 Flash AVU](https://img.shields.io/badge/Rater%20%26%20Orchestrator-gemini--3.8--flash%20(AVU)-34A853)](https://cloud.google.com/vertex-ai)
[![Vertex AI Agent Runtime](https://img.shields.io/badge/Vertex%20AI-Agent%20Runtime%20%26%20Cloud%20Run-green)](https://cloud.google.com/vertex-ai)
[![Pytest](https://img.shields.io/badge/Pytest-72%2F72%20Passed%20(100%25)-brightgreen)](https://pytest.org)

**vidgen-omni** is a production-grade generative long-video orchestration system powered by **Gemini Omni 1.2 Flash (GA)** (`gemini-omni-1.2-flash`), **Gemini 3.8 Flash** with server-side **Agentic Video Understanding** (`MediaProcessing.AGENTIC`), and **Gemini Nano Banana 2.1** (`gemini-nano-banana-2.1`).

It delivers **two complementary execution tracks** from a single codebase:
1. **Hosted Google ADK 2.0 Web Studio (`app/`):** A 6-agent interactive browser & A2A studio deployed on Cloud Run and Vertex AI Agent Runtime for `20s–30s+` multi-shot commercials with real-time SSE trajectory streaming and GCS showcase pinning.
2. **Portable Zero-ADK Skill (`Skill/vidgen-long-video/` & `.agents/skills/vidgen-long-video`):** A self-contained, local-only PEP-723 `uv run` workflow skill scaling to **`60s–90s+` hierarchical multi-scene commercials** (`--scenes-json`) with autonomous `<FIRST_FRAME> + <LAST_FRAME>` two-frame interpolation self-healing, `--resume` checkpoint recovery, and **Omni 1.2 Draft Mode** (`360p` Draft → `3.8 AVU` Agentic Loop → concurrent standalone `task="upscale"` to `720p` / `1080p` / `4k`).

---

## 🏗️ Dual-Track Architecture & Closed-Loop DAG

```
                              [ USER BRIEF / STORYBOARD / #FFFFFF ANCHOR ]
                                                   │
                     ┌─────────────────────────────┴─────────────────────────────┐
                     ▼                                                           ▼
      ┌──────────────────────────────┐                            ┌──────────────────────────────┐
      │ Track 1: ADK 2.0 Web Studio  │                            │ Track 2: Portable Zero-ADK   │
      │ (app/ · Cloud Run & Runtime) │                            │ Skill (Skill/vidgen-long-    │
      │ Screenwriter -> Storyboarder │                            │ video · --scenes-json 90s+)  │
      │ -> PromptOptimizer -> Health │                            │ Direct GenAI SDK + PEP 723   │
      └──────────────┬───────────────┘                            └──────────────┬───────────────┘
                     └─────────────────────────────┬─────────────────────────────┘
                                                   ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
  │                 4 CONTINUITY MODES + OPTIONAL 360p DRAFT -> UPSCALE FLYWHEEL                │
  │                                                                                             │
  │  • Mode A (reference):     Parallel #FFFFFF R2V (task="reference_to_video") across sets     │
  │  • Mode B (i2v_chaining):  Shot 1 R2V ──► OpenCV last_frame.png ──► <FIRST_FRAME> I2V       │
  │  • Mode C (video_extend):  Shot 1 R2V ──► 5.0s audio-intact <VIDEO_0> ──► task="extend"     │
  │                            + OpenCV pixel-MAE prefix trim (eliminates 4-frame VAE drift)    │
  │  • Mode D (hybrid):        Per-shot mode_override + <FIRST_FRAME>+<LAST_FRAME> self-heal    │
  │  • Draft Mode (--draft-mode): Draft & retry at 360p ($0.02/s) ──► parallel task="upscale"   │
  └────────────────────────────────────────────────┬────────────────────────────────────────────┘
                                                   │ Candidate MP4 + High-Res Keyframes A/M/B
                                                   ▼
                                    ┌──────────────────────────────┐
                                    │  Auto-Rater v2 (3.8 AVU)     │ MediaProcessing.AGENTIC +
                                    │  Score < 0.80 ──► Retry /    │ Levenshtein WER <= 0.35 +
                                    │  <FIRST_FRAME>+<LAST_FRAME>  │ Trailing RMS & Seam MAE
                                    └──────────────┬───────────────┘
                                                   │ Winning Clips (Best-of-K / Healed / Upscaled)
                                                   ▼
                                    ┌──────────────────────────────┐
                                    │  80ms xfade + acrossfade     │ Duration-Locked FFMPEG Stitch
                                    │  + Master Seam Critic (AVU)  │ Audits [t_cut-1.5s, t_cut+1.5s]
                                    └──────────────┬───────────────┘
                                                   ▼
                                 [ 30s–90s+ Broadcast-Ready Master MP4 ]
```

---

## ✨ Core Capabilities

- **4 Multi-Shot Continuity Modes (`Mode A / B / C / D`):**
  - **Mode A (`reference`):** Parallel `asyncio.Semaphore` `#FFFFFF` studio-white Reference-to-Video (`task="reference_to_video"`) with OpenCV Frame-0 white-lock rejection (`MAE >= 12.0`).
  - **Mode B (`i2v_chaining`):** Shot 1 `#FFFFFF` R2V followed by terminal-frame PNG `<FIRST_FRAME>` `task="image_to_video"` chaining (automatically stripping colliding `# References` tags so Frame-0 MAE stays `< 4.5`).
  - **Mode C (`video_extend`):** Shot 1 `#FFFFFF` R2V followed by `5.0s` (`120f @ 24fps`, `48kHz` stereo AAC) `<VIDEO_0>` `task="extend"` continuation, frame-exact OpenCV pixel-MAE prefix trimming (`[-0.45s, +0.25s]`), and automatic room-tone sanitization on speech-edit blocks.
  - **Mode D (`hybrid` & `--scenes-json`):** Combines within-act `video_extend` with act-break R2V scene plates (`gemini-nano-banana-2.1`) and autonomous `<FIRST_FRAME> + <LAST_FRAME>` two-frame interpolation repair for `60s–90s+` multi-act commercials.
- **Observation-First Auto-Rater v2 (`gemini-3.8-flash` + `MediaProcessing.AGENTIC`):** Pairs server-side `google:load_video` dynamic inspection with captioned high-res PNG keyframes (`KEY FRAME A/M/B`), canonical reference anchors, Levenshtein spoken-dialogue `WER <= 0.35`, trailing `0.20s` audio cutoff checks (`-26 dBFS`), monotonic **Best-of-$K$** checkpointing, and a **Post-Stitch Master Seam Critic**.
- **Omni 1.2 Draft Mode (`--draft-mode`: `360p` Draft → Agentic Loop → Standalone `task="upscale"`):** Renders candidate clips and runs all `3.8 AVU` retries/repairs at `360p` (`24.1s` mean R2V / `52.0s` mean Extend — up to `3.4×` faster per shot and `3.5×–5×` lower retry waste), then concurrently promotes **only** winning prefix-trimmed `10s` clips via zero-reasoning `task="upscale"` (`total_input_tokens: 0`) to `720p`, `1080p`, or `4k`.
- **Google ADK 2.0 Native + A2A + Cloud Run & Agent Runtime:** Full ADK `Agent`, `Runner`, `FunctionTool`, `AdkApp`, SSE live trajectory visualizer, manual workflow stop (`POST /api/pipeline/stop/{session_id}`), and GCS showcase pinning.

---

## ⚡ Quickstart: Portable Zero-ADK Skill (`Skill/vidgen-long-video`)

Run multi-shot or `90s+` multi-scene commercials locally without ADK or GCS using `uv`:

```bash
export GOOGLE_GENAI_USE_VERTEXAI=True
export GOOGLE_CLOUD_PROJECT="{your_gcp_project}"
export GOOGLE_CLOUD_LOCATION="global"

SKILL_DIR=".agents/skills/vidgen-long-video"

# 1. 30s Single-Take Commercial (Mode C: Shot 1 R2V + 5.0s audio-intact video_extend)
uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
  --prompt "A spokesperson showcases an amber botanical serum bottle in a sunlit stone bathroom, continuous single-take dolly" \
  --reference path/to/studio_white_anchor.png \
  --mode video_extend \
  --shots 3 \
  --duration 10 \
  --resolution 720p \
  --output-dir ./output/beauty_extend_30s

# 2. 90s Multi-Act Commercial in Draft Mode (360p Draft -> 3.8 AVU Loop -> Parallel 720p/1080p Upscale)
uv run "$SKILL_DIR/scripts/run_vidgen_workflow.py" \
  --scenes-json path/to/scenes_storyboard.json \
  --draft-mode \
  --draft-resolution 360p \
  --resolution 720p \
  --max-parallel-scenes 2 \
  --max-parallel-upscales 3 \
  --quality-threshold 0.80 \
  --output-dir ./output/beauty_90s_draft

# 3. Standalone Zero-Reasoning Video Upscale (360p -> 720p/1080p, or 720p -> 1080p/4k; <= 15s)
uv run "$SKILL_DIR/scripts/omni_direct.py" upscale-clip \
  --video ./output/draft_360p.mp4 \
  --source-resolution 360p \
  --target-resolution 720p \
  --output ./output/upscaled_720p.mp4
```

See [`Skill/vidgen-long-video/SKILL.md`](Skill/vidgen-long-video/SKILL.md) and [`Skill/vidgen-long-video/references/storyboard_spec.md`](Skill/vidgen-long-video/references/storyboard_spec.md) for full CLI flags and JSON schemas.

---

## 🛠️ Google ADK 2.0 Web Studio & `agents-cli` Workflow

Install the CLI:
```bash
uv tool install google-agents-cli
```

| Command | Description |
|---------|-------------|
| `agents-cli playground` | Launch local interactive ADK web playground with live tracing |
| `agents-cli run "prompt"` | Smoke test the ADK agent directly in terminal |
| `agents-cli eval run` | Run evaluation datasets and score agent traces |
| `agents-cli deploy` | Deploy agent to Vertex AI Agent Runtime or Cloud Run |
| `agents-cli publish gemini-enterprise` | Register agent in Gemini Enterprise Agent Registry |

### Cloud Deployment Targets
1. **Vertex AI Agent Runtime (`asia-east1`):** Managed Reasoning Engine supporting native `:streamQuery` and A2A agent card discovery (`/api/a2a/vidgen-omni/.well-known/agent-card.json`).
2. **Google Cloud Run (`asia-east1`):** Containerized FastAPI + SSE Web Studio (`Dockerfile` + `cloudbuild.yaml`). Set `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION="global"` with `roles/aiplatform.user` granted to the runtime service account.

---

## 🧪 Testing & Verification

Run the complete unit and integration test suite (covering both the ADK 2.0 Web Studio and the zero-ADK `Skill/vidgen-long-video` pipeline):
```bash
uv run pytest tests/unit tests/integration
```
*Current Status: **72/72 tests passing (100%)**.*

---

## 📁 Repository Structure

```
├── Dockerfile                       # Containerized Python build with FFMPEG & OpenCV
├── cloudbuild.yaml                  # Google Cloud Build CI/CD pipeline
├── pyproject.toml                   # Project dependencies (ADK 2.0, GenAI SDK, FastAPI)
├── agents-cli-manifest.yaml         # Agents CLI configuration & deployment metadata
├── Skill/
│   └── vidgen-long-video/           # Portable Zero-ADK Long-Video Skill (PEP 723 + uv run)
│       ├── SKILL.md                 # Skill workflow, modes, Draft->Upscale & guardrails
│       ├── requirements.txt         # Minimal standalone dependencies (no google-adk)
│       ├── references/
│       │   └── storyboard_spec.md   # Single-scene & --scenes-json 90s+ storyboard schemas
│       └── scripts/
│           ├── media_ops.py         # OpenCV/FFMPEG seam trim, R2V lock, audio RMS/WER, xfade
│           ├── omni_direct.py       # Direct Omni 1.2 (R2V/I2V/Extend/Upscale) + 3.8 AVU CLI
│           └── run_vidgen_workflow.py # Multi-shot, --scenes-json auto-heal & --draft-mode CLI
├── .agents/skills/
│   └── vidgen-long-video            # Workspace auto-discovery symlink -> ../../Skill/vidgen-long-video
├── app/
│   ├── agent.py                     # Root ADK 2.0 agent (vidgen_orchestrator) & tools
│   ├── fast_api_app.py              # Unified FastAPI app (ADK SSE, Web Studio, GCS proxy, A2A)
│   ├── config.py                    # GenAI client & Vertex AI ADC configuration (global)
│   ├── state.py                     # Pydantic PipelineState, VideoShot, StoryboardEntry
│   ├── agents/
│   │   └── pipeline.py              # Multi-agent async DAG, Auto-Rater v2 & Master Seam Critic
│   ├── tools/
│   │   ├── omni_client.py           # Gemini Omni 1.2 Flash video generation & extension
│   │   ├── video_parser.py          # OpenCV frame/tail extraction, MAE seam trim & AVU parts
│   │   ├── stitcher.py              # Duration-locked 80ms xfade + equal-power acrossfade stitcher
│   │   └── gcs_storage.py           # Showcase run persistence & GCS sync
│   └── app_utils/
│       ├── a2a.py                   # A2A Agent Card Builder & JSON-RPC executor
│       └── reasoning_engine_adapter.py # Vertex AI Reasoning Engine adapter
├── deployment/
│   └── terraform/                   # Infrastructure-as-Code (IAM, Service, Storage)
└── tests/
    ├── unit/                        # Unit tests (ADK agents, Auto-Rater v2, Omni client, Skill)
    ├── integration/                 # E2E pipeline, cross-session memory & FastAPI server tests
    └── eval/                        # ADK evaluation datasets
```

---

## 📜 License

Apache License 2.0.
