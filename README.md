# 🎬 vidgen-omni: Multi-Agent Generative Video Pipeline (Google ADK 2.0)

[![Google ADK 2.0](https://img.shields.io/badge/Google%20ADK-2.6.2-blue)](https://github.com/hillxcyu/vidgen)
[![Vertex AI Agent Runtime](https://img.shields.io/badge/Vertex%20AI-Agent%20Runtime%20(asia--east1)-green)](https://cloud.google.com/vertex-ai)
[![Docker](https://img.shields.io/badge/Docker-Containerized-blue)](https://docker.com)
[![Pytest](https://img.shields.io/badge/Pytest-23%2F23%20Passed%20(100%25)-brightgreen)](https://pytest.org)

**vidgen-omni** is a production-grade multi-agent generative video orchestration system built with **Google Agent Development Kit (ADK 2.0)**, **Gemini 3.7 Flash**, and **Gemini Omni Flash** (`gemini-omni-1.1-flash-preview`).

It coordinates a specialized team of 5 AI agents to transform high-level natural language prompts into cohesive multi-shot cinematic videos with character identity preservation and motion continuity via **Sequential Image-to-Video (I2V) Prompt Chaining**.

---

## 🤖 Multi-Agent Architecture & DAG Workflow

```
                             [ USER PROMPT / INTENT ]
                                        │
                                        ▼
                      ┌────────────────────────────────────┐
                      │    vidgen_orchestrator (Root)      │ (gemini-3.7-flash)
                      └─────────────────┬──────────────────┘
                                        │
        ┌───────────────────────────────┴───────────────────────────────┐
        ▼                                                               ▼
 ┌──────────────────────────────┐                       ┌──────────────────────────────┐
 │  1. ScreenwriterAgent        │                       │  2. StoryboarderAgent        │
 └──────────────┬───────────────┘                       └──────────────┬───────────────┘
                │ Multi-Scene Narrative Screenplay                      │ Structured JSON Shot Specs
                └───────────────────────────────┬───────────────────────┘
                                                ▼
                                 ┌──────────────────────────────┐
                                 │  3. PromptOptimizerAgent     │
                                 └──────────────┬───────────────┘
                                                │ Enhanced Omni Flash Prompt
                                                ▼
                                 ┌──────────────────────────────┐
                                 │  4. HealthCheckerAgent       │ (Guardrails & Compliance)
                                 └──────────────┬───────────────┘
                                                │ Approved Shot Prompt
                                                ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
 │                       5. GENERATION & I2V CHAINING PRODUCTION LOOP                          │
 │                                                                                             │
 │  [Shot 1 Prompt] ──► (Gemini Omni Flash) ──► shot_1.mp4                                     │
 │                                                    │                                        │
 │  shot_1.mp4 ──► (OpenCV Video Parser) ──► shot_1_last_frame.png (Base64 Anchor)             │
 │                                                    │                                        │
 │  [Shot 2 Prompt + Frame 1 Base64] ──► (Gemini Omni Flash) ──► shot_2.mp4                    │
 └──────────────────────────────────────┬──────────────────────────────────────────────────────┘
                                        │ Individual MP4 Clips
                                        ▼
                                 ┌──────────────────────────────┐
                                 │  5. QualityRaterAgent        │ (Rubric Score < 0.8 Retry Loop)
                                 └──────────────┬───────────────┘
                                                │ Verified Clips
                                                ▼
                                 ┌──────────────────────────────┐
                                 │  6. FFMPEG Stitcher Tool     │ (Direct Stream Copy Concat)
                                 └──────────────┬───────────────┘
                                                │
                                                ▼
                                 [ output_stitched_30s.mp4 ]
                                 [ GCS Showcase Sync ]
```

---

## ✨ Core Capabilities

- **Google ADK 2.0 Native (`google.adk`):** Built on ADK 2.0 `Agent`, `Runner`, `FunctionTool`, `AdkApp`, and `Session` abstractions.
- **Sequential Image-to-Video (I2V) Chaining:** Uses OpenCV to extract the terminal frame (Frame #100) of Shot $N$ as a Base64 visual anchor, supplying it as the starting frame for Shot $N+1$ in Gemini Omni Flash.
- **5-Category Major Subject Drift Detection:** `QualityRaterAgent` evaluates clips across Face Identity, Product, Clothing, Accessories/Props, and Background Stability. If score $< 0.8$, actionable feedback is passed to `PromptOptimizerAgent` for automatic prompt refinement.
- **Vertex AI Agent Runtime:** Deployed to managed Vertex AI Reasoning Engines in `asia-east1` (Taiwan), supporting native `:streamQuery` and `/api` passthrough.
- **Agent-to-Agent (A2A Protocol):** Implements the A2A standard with automated agent card generation and JSON-RPC dispatching.
- **Persistent GCS Showcase:** Automatically syncs generated videos, clips, and metadata to Google Cloud Storage (`gs://universal-trail-492014-n5-vidgen-showcase`).
- **Interactive Web Studio UI:** Real-time Server-Sent Events (SSE) stream trajectory logs, screenplays, and live video previews directly to the browser.

---

## 🛠️ Google Agents CLI Workflow (`agents-cli`)

Install the CLI:
```bash
uv tool install google-agents-cli
```

### Development Commands

| Command | Description |
|---------|-------------|
| `agents-cli playground` | Launch local interactive web playground with live tracing |
| `agents-cli run "prompt"` | Smoke test the agent directly in terminal |
| `agents-cli eval run` | Run evaluation datasets and score agent traces |
| `agents-cli deploy` | Deploy agent to Vertex AI Agent Runtime or Cloud Run |
| `agents-cli publish gemini-enterprise` | Register agent in Gemini Enterprise Agent Registry |

---

## 🚀 Deployment Targets

### 1. Vertex AI Agent Runtime (`asia-east1`)
Deployed as a managed Reasoning Engine with automatic session state persistence and IAM-governed API access:
* **Resource ID:** `projects/456465962826/locations/asia-east1/reasoningEngines/5283399662068301824`
* **Agent Card URL:**
  ```
  https://asia-east1-aiplatform.googleapis.com/reasoningEngines/v1/projects/456465962826/locations/asia-east1/reasoningEngines/5283399662068301824/api/a2a/vidgen-omni/.well-known/agent-card.json
  ```

### 2. Google Cloud Run (Frontend & Web Studio)
Automated CI/CD via Google Cloud Build:
* **Region:** `asia-east1`
* **Artifact Registry:** `asia-east1-docker.pkg.dev/universal-trail-492014-n5/vidgen-repo/vidgen-app`

---

## 🧪 Testing & Verification

Run the full unit and integration test suite:
```bash
uv run pytest tests/unit tests/integration
```
*Current Status: 23/23 tests passing (100%).*

---

## 📁 Repository Structure

```
├── Dockerfile                  # Containerized Python 3.11 build with FFMPEG & OpenCV
├── cloudbuild.yaml             # Google Cloud Build CI/CD pipeline for asia-east1
├── pyproject.toml              # Project dependencies (ADK 2.0, GenAI SDK, FastAPI)
├── agents-cli-manifest.yaml    # Agents CLI configuration & deployment metadata
├── deployment_metadata.json    # Live Agent Runtime resource mapping
├── app/
│   ├── agent.py                # Root ADK agent (vidgen_orchestrator) & tools
│   ├── fast_api_app.py         # Unified FastAPI app (ADK SSE, Web Studio, A2A)
│   ├── config.py               # GenAI client & Vertex AI ADC configuration
│   ├── state.py                # Pydantic PipelineState, VideoShot, StoryboardEntry
│   ├── agents/
│   │   └── pipeline.py         # Multi-agent async DAG & evaluation loop
│   ├── tools/
│   │   ├── omni_client.py      # Gemini Omni Flash video generation
│   │   ├── video_parser.py     # OpenCV terminal frame extractor
│   │   ├── stitcher.py         # FFMPEG direct stream copy concatenator
│   │   └── gcs_storage.py      # Showcase run persistence & GCS sync
│   └── app_utils/
│       ├── a2a.py              # A2A Agent Card Builder & JSON-RPC executor
│       └── reasoning_engine_adapter.py # Vertex AI Reasoning Engine adapter
├── deployment/
│   └── terraform/              # Infrastructure-as-Code (IAM, Service, Storage)
└── tests/
    ├── unit/                   # Unit test suite
    ├── integration/            # E2E pipeline & FastAPI integration tests
    └── eval/                   # ADK evaluation datasets
```

---

## 📜 License

Apache License 2.0.
