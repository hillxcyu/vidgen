# 🎬 vidgen: Multi-Agent Generative Media Pipeline

[![Google ADK 2.0](https://img.shields.io/badge/Google%20ADK-2.6.2-blue)](https://github.com/hillxcyu/vidgen)
[![Docker](https://img.shields.io/badge/Docker-Containerized-blue)](https://docker.com)
[![Pytest](https://img.shields.io/badge/Pytest-27%2F27%20Passed-green)](https://pytest.org)

**vidgen** is a high-code multi-agent generative video pipeline built with **Google Agent Development Kit (ADK 2.0)**, **Gemini 3.6 Flash**, and **Gemini Omni Flash** (`gemini-omni-flash-preview`).

It coordinates a team of 5 specialized AI agents to expand raw user prompts into multi-shot videos with unbroken visual identity and motion continuity via **Sequential Image-to-Video (I2V) Prompt Chaining**.

---

## 🤖 Multi-Agent Architecture & DAG Workflow

```
                             [ USER PROMPT ]
                                    │
                                    ▼
                     ┌──────────────────────────────┐
                     │   ORCHESTRATOR AGENT        │ (gemini-3.6-flash)
                     └──────────────┬───────────────┘
                                    │
       ┌────────────────────────────┴────────────────────────────┐
       ▼                                                         ▼
┌──────────────────────────────┐          ┌──────────────────────────────┐
│  1. SCREENWRITER AGENT       │          │  2. STORYBOARDER AGENT       │
└──────────────┬───────────────┘          └──────────────┬───────────────┘
               │ 3-Act Narrative Script                  │ Structured JSON Specs
               └────────────────────────────┬────────────┘
                                            ▼
                             ┌──────────────────────────────┐
                             │  3. PROMPT OPTIMIZER AGENT   │
                             └──────────────┬───────────────┘
                                            │ Enhanced Multimodal Prompt
                                            ▼
                             ┌──────────────────────────────┐
                             │  4. HEALTH CHECKER AGENT     │ (Guardrails Audit)
                             └──────────────┬───────────────┘
                                            │ Approved Prompt Payload
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 5. GENERATION & I2V CHAINING LOOP                           │
│                                                                             │
│  [Shot 1 Prompt] ──► (Gemini Omni Flash) ──► shot_1.mp4                      │
│                                                    │                        │
│  shot_1.mp4 ──► (OpenCV Parser) ──► shot_1_last_frame.png (Base64)           │
│                                                    │                        │
│  [Shot 2 Prompt + Frame 1 Base64] ──► (Omni Flash) ──► shot_2.mp4           │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │ Individual MP4 Clips
                                     ▼
                             ┌──────────────────────────────┐
                             │  6. QUALITY RATER AGENT      │ (Score < 0.8 Feedback Loop)
                             └──────────────┬───────────────┘
                                            │ Certified Clips
                                            ▼
                             ┌──────────────────────────────┐
                             │  7. FFMPEG STITCHER TOOL     │ (Direct Stream Copy)
                             └──────────────┬───────────────┘
                                            │
                                            ▼
                               [ output_stitched_30s.mp4 ]
```

---

## ✨ Key Features

- **Google ADK 2.0 Integration (`google.adk`):** Built natively using ADK `LlmAgent`, `Workflow`, `FunctionNode`, `Edge`, `Event`, and `Session` abstractions.
- **Sequential Image-to-Video (I2V) Chaining:** Uses OpenCV to extract the terminal frame (Frame #100) of Shot $N$ as a Base64 payload, supplying it as the starting visual anchor for Shot $N+1$ in Gemini Omni Flash.
- **5-Category Major Subject Drift Detection:** `QualityRaterAgent` audits clips across Face Identity, Product, Clothing, Accessories/Props, and Environment/Background stability. If `score < 0.8` or drift is detected, actionable feedback is routed back to `PromptOptimizerAgent` for a re-attempt.
- **Showcase Run Pinning & GCS Sync:** Allows pinning showcased video runs to a slide-out drawer panel and syncing stitched MP4s, shot clips, last frames, and manifest JSON to Google Cloud Storage (`gs://...`).
- **Real-Time Audit Trajectory Visualizer:** Server-Sent Events (SSE) stream live agent communication logs and audit verdicts to a Web Studio UI with folded message cards and hidden control strings.

---

## 🚀 Quick Start (Docker Environment)

### 1. Environment Setup
Create a `.env` file in the root directory:
```bash
GOOGLE_CLOUD_PROJECT=universal-trail-492014-n5
GOOGLE_CLOUD_LOCATION=global
```

### 2. Build Docker Container
```bash
docker compose build
```

### 3. Run Web Studio (Port 3000)
```bash
docker compose up -d web
```
Open **[http://localhost:3000](http://localhost:3000)** in your browser to prompt the pipeline, track real-time agent trajectories, and watch the generated video output.

### 4. Run Pytest Suite
```bash
docker compose run --rm test
```

### 5. Run CLI Execution
```bash
docker compose run --rm app --prompt "A red panda skiing in Hakuba" --shots 3 --mode i2v_chaining --output ./output
```

---

## 📁 Repository Structure

```
├── Dockerfile                  # Containerized Python 3.11 build with FFMPEG & OpenCV
├── docker-compose.yml          # Web, app, and test service definitions
├── pyproject.toml              # Dependencies (google-adk, google-genai, fastapi, uvicorn)
├── README.md                   # Project documentation
├── agent.yaml                  # ADK 2.0 agent deployment manifest
├── cloudbuild.yaml             # Google Cloud Build CI/CD deployment pipeline
├── src/
│   ├── agents/
│   │   └── stitcher_graph.py   # ADK Workflow graph & agent definitions
│   ├── prompts/                # Agent system prompt instructions
│   │   ├── pre_prod_system.txt
│   │   └── prod_loop_system.txt
│   ├── tools/                  # Python primitives registered as ADK FunctionTools
│   │   ├── omni_client.py      # Gemini Omni Flash wrapper (interactions.create)
│   │   ├── video_parser.py     # OpenCV terminal frame extractor
│   │   ├── gcs_storage.py      # Showcase run pinning & GCS bucket manager
│   │   └── stitcher.py         # FFMPEG stream-copy video concatenator
│   ├── config.py               # Vertex AI ADC authentication
│   ├── state.py                # PipelineState & VideoShot Pydantic models
│   ├── main.py                 # CLI entry point
│   └── server.py               # FastAPI Web Studio & SSE streaming server
└── tests/                      # 27 Pytest unit & integration tests
```

---

## 📜 License

Apache License 2.0. Developed by Hill Yu (`xcyu@google.com`).
