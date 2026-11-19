# Multi-Act Commercial Video Studio with Gemini Omni — Seller Demo Guide

## Executive Summary & Pitch Context

- **Target Buyer Personas:** Chief Marketing Officers (CMOs), VP of Brand & Creative Operations, Retail Merchandising & E-Commerce Leads, Media Production Directors.
- **Customer Pain Point:** Enterprise marketing teams struggle to scale generative AI video beyond isolated 5–15 second clips because characters, products, lighting, and spoken audio drift across cuts—forcing expensive manual re-shoots or brittle post-production stitching.
- **Value Proposition:** **vidgen-omni** orchestrates continuity-locked `30s–90s+` multi-act commercial videos using **Gemini Omni 1.2 Flash** (`gemini-omni-1.2-flash`), **Gemini 3.8 Flash Agentic Video Understanding** (`MediaProcessing.AGENTIC`), and **Gemini 3.8 Flash TTS**. With **360p Draft Mode** (`--draft-mode`), teams iterate and self-heal at `$0.02/s` before concurrently upscaling only winning clips to `720p`/`1080p`/`4k`, cutting retry waste by `3.5×–5×`.
- **Estimated Demo Duration:** 10–15 minutes.

---

## How to Build

This section explains how **vidgen-omni** is architected and built end-to-end on Google Cloud using **Google ADK 2.0**, **Vertex AI (Gemini Omni 1.2 Flash, Gemini 3.8 Flash, Gemini 3.8 Flash TTS, Nano Banana 2.1)**, **Cloud Run**, and **Cloud Storage**.

### Step 1: Scaffold the Project & Dependencies (`pyproject.toml`, `click-to-deploy/Dockerfile`)

- Python `>=3.11,<3.14` project managed with `uv` (`pyproject.toml` and `uv.lock`).
- Core runtime dependencies: `google-adk`, `google-genai`, `google-cloud-aiplatform`, `google-cloud-storage`, `fastapi`, `uvicorn`, `opencv-python-headless`, and `pydantic`.
- System dependencies in `Dockerfile` and `click-to-deploy/Dockerfile`: `ffmpeg`, `libgl1`, and `libglib2.0-0` for frame-exact OpenCV seam analysis and FFMPEG `xfade`/`acrossfade` stitching.
- Supply-chain security (`click-to-deploy/requirements.txt`): all direct and transitive Python dependencies are pinned (`==`) with SHA-256 hashes and installed via `pip install --no-cache-dir --require-hashes -r requirements.txt`.

### Step 2: Build the Core Video Continuity & Quality-Gating Pipeline (`app/tools/`, `Skill/vidgen-long-video/scripts/`)

- **Vertex AI Client (`app/config.py`):** Configures the Google GenAI SDK (`google-genai`) with `GOOGLE_GENAI_USE_VERTEXAI=true` and `GOOGLE_CLOUD_LOCATION=global` for Gemini Omni 1.2 Flash and Gemini 3.8 Flash.
- **Omni 1.2 Generation & Extension (`app/tools/omni_client.py`):** Implements studio-white `#FFFFFF` Reference-to-Video (`task="reference_to_video"`), Image-to-Video chaining (`task="image_to_video"`), `5.0s` audio-intact Video Extension (`task="extend"`), zero-reasoning `task="upscale"`, and Third-Party Voice Generation (`tpvg_tts` with `app/tools/tts_client.py`).
- **Deterministic Seam & Audio Verification (`app/tools/video_parser.py`, `app/tools/stitcher.py`):**
  - OpenCV Frame-0 white-lock rejection (`MAE >= 12.0`) and pixel-MAE prefix trimming (`[-0.45s, +0.25s]`) to eliminate 4-frame VAE drift.
  - Trailing `0.20s` audio cutoff checks (`-26 dBFS`) and Levenshtein spoken-dialogue `WER <= 0.35`.
  - Duration-locked `80ms` `xfade` + equal-power `acrossfade` FFMPEG stitching.

### Step 3: Orchestrate the Multi-Agent ADK 2.0 Web Studio (`app/agent.py`, `app/agents/pipeline.py`, `app/fast_api_app.py`)

- **Root ADK Agent (`app/agent.py`):** Defines `vidgen_orchestrator` and tool bindings for storyboarding, generation, rating, and stitching.
- **Async Pipeline & Auto-Rater v2 (`app/agents/pipeline.py`):** Executes the Screenwriter → Storyboarder → PromptOptimizer → Continuity Generator → Auto-Rater v2 (`gemini-3.8-flash` + `MediaProcessing.AGENTIC`) → Master Seam Critic loop with monotonic Best-of-K checkpointing.
- **Unified FastAPI & SSE Server (`app/fast_api_app.py`):** Serves the interactive Web Studio UI, real-time SSE trajectory streaming, manual pipeline stop (`POST /api/pipeline/stop/{session_id}`), GCS showcase persistence (`app/tools/gcs_storage.py`), and A2A agent card discovery (`app/app_utils/a2a.py`).

### Step 4: Test & Deploy to Google Cloud (`tests/`, `click-to-deploy/`)

- Run the unit and integration test suite: `uv run pytest tests/unit tests/integration`.
- Provision Cloud Run (`INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER`), External HTTPS Application Load Balancer, Serverless NEG, IAP service identity, Artifact Registry, Secret Manager, and GCS showcase bucket via `click-to-deploy/`.

---

## Pillar 1: Setup & Deployment Instructions

### 1.1 Prerequisites & IAM Permissions

- **GCP Environment:** A Google Cloud project (or Argolis sandbox) with billing enabled.
- **Required IAM Roles for Deployment:** `roles/owner` (or granular `roles/run.admin`, `roles/compute.loadBalancerAdmin`, `roles/iap.admin`, `roles/artifactregistry.admin`, `roles/storage.admin`, `roles/secretmanager.admin`, `roles/iam.serviceAccountAdmin`, `roles/serviceusage.serviceUsageAdmin`).
- **Runtime Service Account Roles (provisioned automatically by Terraform):** `roles/aiplatform.user`, `roles/logging.logWriter`, `roles/serviceusage.serviceUsageConsumer`, and bucket-scoped `roles/storage.objectAdmin`.
- **Required APIs:** `aiplatform.googleapis.com`, `artifactregistry.googleapis.com`, `cloudbuild.googleapis.com`, `compute.googleapis.com`, `iam.googleapis.com`, `iap.googleapis.com`, `logging.googleapis.com`, `run.googleapis.com`, `secretmanager.googleapis.com`, `serviceusage.googleapis.com`, `storage.googleapis.com`, `texttospeech.googleapis.com`.
- **Critical Environment Variables:** `GOOGLE_CLOUD_LOCATION=global` and `GOOGLE_GENAI_USE_VERTEXAI=true`.

### 1.2 Option A: One-Click Deployment via Click-to-Deploy (Recommended)

1. Open the demo listing on `go/demos` and click **Deploy Demo (Click-to-Deploy)**.
2. Select your target Argolis organization and project, and choose a `data_location` (default `us-central1`).
3. Wait approximately **5–8 minutes** for Terraform provisioning to complete.

### 1.3 Option B: Manual CLI / Terraform Deployment

1. Build and push the container image to Artifact Registry:

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"

gcloud artifacts repositories create vidgen-images \
  --repository-format=docker \
  --location="${REGION}" \
  --project="${PROJECT_ID}" || true

gcloud builds submit \
  --tag "${REGION}-docker.pkg.dev/${PROJECT_ID}/vidgen-images/vidgen-omni:latest" \
  --project="${PROJECT_ID}" \
  -f click-to-deploy/Dockerfile .
```

2. Deploy the infrastructure with Terraform:

```bash
cd click-to-deploy
terraform init
terraform apply \
  -var="project_id=${PROJECT_ID}" \
  -var="data_location=${REGION}" \
  -var="container_image=${REGION}-docker.pkg.dev/${PROJECT_ID}/vidgen-images/vidgen-omni:latest"
```

3. **(Optional) Local Zero-ADK Skill Execution (`Skill/vidgen-long-video`):**

```bash
export GOOGLE_GENAI_USE_VERTEXAI=True
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export GOOGLE_CLOUD_LOCATION="global"

uv run Skill/vidgen-long-video/scripts/run_vidgen_workflow.py \
  --prompt "A spokesperson showcases an amber botanical serum bottle in a sunlit stone bathroom, continuous single-take dolly" \
  --reference path/to/studio_white_anchor.png \
  --mode video_extend \
  --shots 3 \
  --duration 10 \
  --resolution 720p \
  --output-dir ./output/beauty_extend_30s
```

### 1.4 Deployment Verification

Verify the Cloud Run service and Load Balancer endpoint are healthy before your customer call:

```bash
gcloud run services list --project="${PROJECT_ID}" --region="${REGION}"
terraform -chdir=click-to-deploy output -raw app_url
```

### 1.5 Teardown & Cost Cleanup

To avoid ongoing compute, load balancer, and storage charges after your customer session:

```bash
cd click-to-deploy
terraform destroy \
  -var="project_id=${PROJECT_ID}" \
  -var="data_location=${REGION}"
```

---

## Pillar 2: How to Access the Demo

### 2.1 Retrieving Entry Point URLs

- **Hosted Internal Live Demo (Fastest for Sellers):** Open `https://vidgen-frontend-440790012685.asia-east1.run.app` in your corporate Chrome profile.
- **Self-Deployed via Click-to-Deploy:** Copy the `app_url` from the C2D completion notification or run `terraform -chdir=click-to-deploy output -raw app_url`.

### 2.2 Credentials & Test Personas

- **Authentication Method:** Identity-Aware Proxy (IAP) SSO. Sign in with your `@google.com` corporate account (or Argolis admin account for self-deployed sandboxes). No separate username or password is required.
- **In-App Experience:** All users land directly in the **vidgen-omni Studio** workspace with access to pre-pinned `30s–90s+` showcase runs and live generation controls.

### 2.3 Expected Initial Landing State

Upon opening the application URL, confirm you see:
- The **vidgen-omni** studio header with active Vertex AI project status.
- The **Showcase Gallery** populated with pre-rendered `30s` and `90s` multi-act commercial runs (Mode A/B/C/D).
- The **Prompt & Continuity Mode** composer (`reference`, `i2v_chaining`, `video_extend`, `hybrid`, `tpvg_tts`) and the **Live Agent Trajectory** panel.

---

## Demo Walkthrough (Pillar 3 & Pillar 4: Step-by-Step Walkthrough & Seller Talking Script)

### Opening Discovery Hook (Before Sharing Screen)

> **What to Say:** *"Most brands we speak with are excited about generative video for 5-second social clips, but hit a wall when they try to produce a 30-to-90 second product commercial—the talent changes face, the product label warps, and audio cuts off mid-sentence. How is your creative team currently handling multi-shot consistency and QA when testing AI video?"*

### Step 1: Showcase Pinned 30s–90s+ Multi-Act Commercials & Draft Mode Economics

- **What to Do (Click Sequence):**
  1. In the **Showcase Gallery**, click a pinned `90s` 4-Act Beauty Commercial run (e.g., `retail_uc3_beauty_arc_90s_draft`).
  2. Play the stitched master MP4 and expand the **Shot & Seam Diagnostics** drawer to show the `360p` draft vs. `720p` upscaled pair and `Auto-Rater v2` scores.
- **Expected Visual Outcome:** The browser plays a seamless `90s` multi-act commercial with consistent product packaging, natural voiceover, and zero jump-cuts across acts, alongside per-shot quality scores (`>= 0.80`).
- **What to Say (Seller Script):** *"Instead of burning 720p or 1080p tokens on every failed take, vidgen-omni runs all creative retries and self-healing at 360p Draft Mode—about two cents a second—and only promotes winning, prefix-trimmed clips to 720p or 1080p via zero-reasoning upscaling. That cuts retry waste by 3.5x to 5x."*
- **Why Google Cloud (Differentiator Callout):** *"This combines Gemini Omni 1.2 Flash's native Reference-to-Video, 5-second audio-intact Extend, and standalone Upscale tasks with Gemini 3.8 Flash Agentic Video Understanding—all through one unified Vertex AI endpoint."*

### Step 2: Launch a Live Continuity-Locked Multi-Shot Commercial

- **What to Do (Click Sequence):**
  1. Scroll to the **New Production** composer.
  2. Select Continuity Mode **`video_extend` (Mode C)** (or **`hybrid` (Mode D)** with **Draft Mode** toggled ON).
  3. Paste the following verified prompt into the brief box:
     ```text
     A warm, sunlit 30-second commercial for an amber glass botanical serum bottle on a travertine bathroom counter. Shot 1 opens with a slow macro dolly-in on the embossed bottle. Shot 2 transitions smoothly as a presenter picks up the bottle and speaks naturally: "Pure botanical hydration, bottled for your morning ritual." Shot 3 closes on a serene counter hero frame with soft morning light.
     ```
  4. Set **Shots** to `3`, **Duration** to `10s`, and click **Start Production**.
- **Expected Visual Outcome:** The **Live Agent Trajectory** panel streams real-time SSE events as `Screenwriter` → `Storyboarder` → `PromptOptimizer` → `Generator` → `Auto-Rater v2` execute.
- **What to Say (Seller Script):** *"Watch the ADK 2.0 multi-agent pipeline in real time. The Screenwriter and Storyboarder lock the visual anchor first, then each 10-second shot is extended from the previous 5 seconds of video and stereo audio—trimmed at the exact frame where OpenCV detects minimal pixel MAE so there is zero VAE drift at the cut."*

### Step 3: Inspect Automated Quality Gating (`Auto-Rater v2`) & Seam Critic

- **What to Do (Click Sequence):**
  1. While generation runs (or on the completed run), click the **Auto-Rater v2** badge on Shot 1 or Shot 2.
  2. Highlight the **Keyframes A/M/B**, **WER** (Word Error Rate), and **Trailing Audio dBFS** telemetry.
- **Expected Visual Outcome:** A breakdown showing multimodal critique from `gemini-3.8-flash` (`MediaProcessing.AGENTIC`), confirming `WER <= 0.35` and clean audio tail without mid-word clipping.
- **What to Say (Seller Script):** *"Before any clip reaches your creative director, Gemini 3.8 Flash inspects the actual video frames and spoken audio. If a shot scores below 0.80, the pipeline automatically heals it using first-and-last frame interpolation—no human babysitting required."*

### Closing & Next-Step Transition

- **Common Customer Objection & Response:**
  - *Objection:* *"Can our creative ops team run this as an automated CLI batch job without a web UI?"*
  - *Response:* *"Yes—the exact same continuity engine ships as a zero-ADK portable Python skill (`Skill/vidgen-long-video`) using `uv run` and JSON storyboards, so you can integrate it straight into your existing CI/CD or DAM pipelines."*
- **Call to Action:** *"Let's schedule a 60-minute creative tech workshop next week where we bring one of your hero product SKUs, generate a studio-white anchor, and produce a 30-second continuity-locked spot live in your GCP sandbox."*

---

## Troubleshooting & Live-Demo Recovery Tips

- **Cloud Run Cold-Start Latency:** If the live studio hasn't been accessed recently, open `https://vidgen-frontend-440790012685.asia-east1.run.app` 5 minutes before the customer call to warm the container.
- **Generation Timeouts During Live Calls:** Full 3-shot `10s` video generation takes ~2–4 minutes. Start the live generation during Step 2, narrate the **Live Agent Trajectory** SSE stream, and switch to a pre-pinned **Showcase Gallery** `90s` run while the live job finishes.
- **IAP 403 / Sign-In Prompt:** Ensure you are signed into Chrome with your `@google.com` corporate profile (or authorized Argolis user) and not an incognito window without corp SSO.
- **Quota or Model Region Errors:** Confirm `GOOGLE_CLOUD_LOCATION=global` is set in the Cloud Run environment variables and the runtime service account holds `roles/aiplatform.user`.
