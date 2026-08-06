# `plan.md`

## 📋 Metadata
*   **Project Title:** Multi-Agent Generative Media Pipeline (GenMedia-Omni)
*   **Target Framework:** Google Agent Development Kit (ADK) 2.0
*   **Orchestrator Model:** `gemini-3.6-flash` (Orchestrator, Screenwriter, Storyboarder, Optimizer, Rater)
*   **Video Generation Model:** `gemini-omni-flash-preview` (Gemini Omni Flash via Interactions API)
*   **Core Feature:** 30s Video Stitcher (3x 10s Shots) via Reference Consistency and Sequential Chaining
*   **Workspace Root:** `sdd-adk-agents-agy/`

---

## 🎯 System Architecture
The pipeline is designed as an event-driven, three-tier architecture orchestrated via ADK 2.0 session states.

```
       [ CLIENT / USER INTERFACE ]
                   │
                   ▼ (1. Raw Prompt / Mode Selection)
       [ ORCHESTRATION LAYER (Cloud Run / Agent Engine) ]
                   │
                   ├─► [ ADK Session State Manager (state.py) ]
                   │
                   ├─► [ Sequential Block (gemini-3.6-flash) ]
                   │     ├── Screenwriter Agent
                   │     └── Storyboarder Agent
                   │
                   ├─► [ Production Loop Block (gemini-3.6-flash) ]
                   │     ├── Prompt Optimizer Agent
                   │     ├── Health Checker Agent (Guardrails)
                   │     └── Quality Rater Agent (Feedback Loop)
                   │
                   ▼ (2. Video / Image Payload)
       [ SERVICE & UTILITY LAYER ]
                   │
                   ├─► [ Gemini Omni Flash API ] (Video Gen / I2V)
                   ├─► [ OpenCV Parser ] (Terminal Frame Extraction)
                   ├─► [ FFMPEG Engine ] (MP4 Stitching)
                   └─► [ Google Cloud Storage (GCS) ] (Asset Bucket)
```

### Architectural Component Responsibilities

| Component Layer | Module / File | Tech Stack | Primary Responsibility |
| :--- | :--- | :--- | :--- |
| **Client Interface** | GCR AgentHub | `go/gcr-agenthub` Web UI | Exposes self-service triggering, mode configuration, and final MP4 playback. |
| **Orchestrator** | `src/main.py` | ADK 2.0 Engine | Entry point. Reads configurations, executes routing logic, and initializes execution paths. |
| **State Manager** | `src/state.py` | Python / Pydantic | Maintains global schema consistency across agents, keeping track of scripts, storyboard blocks, extracted frame paths, and run parameters. |
| **Pre-Production Block** | `src/agents/pre_production.py` | `gemini-3.6-flash` | Executes linear workflow: generates multi-scene screenplay from user prompt, then partitions them into storyboard specs. |
| **Production Loop Block** | `src/agents/production_loop.py`| `gemini-3.6-flash` | Runs the iterative generation. Compiles feedback and increments attempt counters if quality rating thresholds are missed. |
| **Generation Backend** | `src/tools/omni_client.py` | `gemini-omni-flash-preview` | Consumes optimized prompts alongside I2V/Reference payloads to output high-fidelity raw MP4 clips. |
| **Video Utility** | `src/tools/video_parser.py` | OpenCV (`cv2`) | Handles binary stream seeking to isolate the exact terminal frame of generated video clips. |
| **File Processor** | `src/tools/stitcher.py` | FFMPEG (`concat` binary) | Executes direct stream copy stitching to combine individual 10-second parts into a final 30-second video without re-encoding. |
| **Asset Storage** | `src/tools/gcs_helper.py` | Google Cloud Storage | Stores static input reference images, intermediate extracted png frames, individual clips, and final outputs. |

---

## 🎯 Dual-Mode Stitching Implementation Specifics

To maintain absolute character, asset, and motion consistency across shots, your pipeline implements two execution tracks using **Gemini Omni Flash's native multimodal input capability**:

| Mode | Mechanism | Target Parameters | Core Strength |
| :--- | :--- | :--- | :--- |
| **a) Reference Mode** | "Ingredients-to-Video". Feeds up to 10 shared static character/style reference images along with prompt instructions. | List of dictionaries with `type: "image"` inside `input` payload. | Excellent identity lock-in for character, clothing, and environment across shifting camera perspectives. |
| **b) Sequential I2V Mode** | Chaining. Programmatically extracts the absolute last frame of Shot $N$, converts it to Base64, and passes it as the first input item of Shot $N+1$. | First item in `input` is the base64-encoded PNG, followed by the motion prompt. | Seamless physical motion, pose transition, and scene permanence across cut-less sequences. |

---

## ⛔ Non-Goals & Guardrails
*   **No Multi-Track/Parallel Editing:** The pipeline is limited to linear stitching (joining shots 1, 2, and 3 back-to-back into a continuous 30-second timeline). We will not implement complex multi-track layering, B-roll overlays, or custom visual transitions (like wipes or cross-dissolves).
*   **No Custom Model Training:** We utilize pre-trained Google GenAI API endpoints natively. No local LoRA fine-tuning will be implemented.
*   **Token Optimization:** All sub-agents must utilize cached contexts (`CONTEXT.md` / `STATE.json`) to minimize conversation bloat and stay under rate limits.

---

## 📋 Direct Implementation Tasklist

- [x] **[T001] Setup Development Scaffolding**
  *   Create standard Python configuration, lockfiles, and workspace directory layout.
  *   *File path:* `pyproject.toml`, `Makefile`, `.env`

- [x] **[T002] Implement Configuration Module**
  *   Load environment variables and authenticate the Vertex GenAI / Google GenAI SDK.
  *   *File path:* `src/config.py`

- [x] **[T003] Establish Shared Session State**
  *   Implement a Pydantic-based state class managing script drafts, storyboard entries, extracted frame metrics, and mode metadata (Reference vs. I2V Chaining).
  *   *File path:* `src/state.py`

- [x] **[T004] Build Video Processing Parser**
  *   Write OpenCV-based frame capture routine to read the terminal frame of generated mp4s and write to GCS / local temp file.
  *   *File path:* `src/tools/video_parser.py`

- [x] **[T005] Implement Gemini Omni Flash Wrapper Tool**
  *   Create model interaction client supporting `gemini-omni-flash-preview` via the `interactions.create` endpoint.
  *   Add parameters mapping both `reference_images_b64` (Reference Mode) and `input_image_b64` (I2V Chaining Mode).
  *   *File path:* `src/tools/omni_client.py`

- [x] **[T010] Build File Concatenator Utility**
  *   Build high-performance FFMPEG stream-copy stitcher wrapper to combine individual 10s video segments into a consolidated 30s video.
  *   *File path:* `src/tools/stitcher.py`

- [x] **[T006] Program Agent System Prompts**
  *   Define instruction files for Screenwriter, Storyboarder, Prompt Optimizer, Health Checker, and Quality Rater using `gemini-3.6-flash`.
  *   *File path:* `src/prompts/pre_prod_system.txt`, `src/prompts/prod_loop_system.txt`

- [x] **[T007] Orchestrate Multi-Agent Routing Graph**
  *   Write main ADK 2.0 execution sequence mapping Pre-Production (Linear) and Production (Loop) blocks.
  *   *File path:* `src/agents/stitcher_graph.py`

- [x] **[T008] Write Unit & Integration Evals**
  *   Build Pytest suite mocking Omni Flash responses, validating OpenCV frame grabs, and verifying FFMPEG outputs.
  *   *File path:* `tests/test_pipeline.py`

- [x] **[T009] Configure GCR AgentHub Publication**
  *   Create the standardized directory configuration to package the ADK high-code pipeline for publication.
  *   *File path:* `agent.yaml`, `Dockerfile`

- [x] **[T011] Implement Manual Workflow Cancellation & Stop Button**
  *   Expose `POST /api/pipeline/stop/{session_id}` endpoint to cancel background `asyncio.Task` and persist stopped state.
  *   Add "⏹ Stop Workflow" button in Web Studio UI to gracefully terminate in-flight executions and close EventSource SSE streams.
  *   *File path:* `src/server.py`, `src/templates/index.html`

---

## 🧪 Verification & Commands

Run these verification steps to test implementation:

```bash
# 1. Run full Pytest coverage suite
uv run pytest tests/

# 2. Run test execution on a local mock prompt
uv run python3 src/main.py --prompt "A red panda skiing in Hakuba" --mode "i2v_chaining"

# 3. Compile final FFMPEG test verification
ffmpeg -i output_stitched_30s.mp4 2>&1 | grep Duration
```
