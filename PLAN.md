# `PLAN.md`

## 📋 Metadata
*   **Feature:** Incorporate Gemini Agentic Video Understanding (`media_processing="agentic"`)
*   **Target Models:** `gemini-3.7-flash` (Quality Rater / Video Auditor)
*   **Created At:** 2026-09-02T01:38:00Z
*   **Status:** PENDING_USER_APPROVAL

---

## 🎯 Goal & Overview

Incorporate Google GenAI's newly released **Agentic Video Understanding** (`media_processing="agentic"`) into VidGen-Omni.

Instead of static frame-by-frame subsampling, setting `media_processing="agentic"` on video `types.Part` allows `gemini-3.7-flash` to act as an autonomous multimodal video agent. It dynamically inspects relevant video segments, zooms into character details at arbitrary timestamps, tracks physics and motion dynamics, and detects micro-discrepancies in cross-shot identity and continuity.

---

## 🛠️ Step-by-Step Implementation Plan

### 1️⃣ Dependency & Environment Upgrade
* Update `pyproject.toml` dependency from `google-genai>=0.1.0` to `google-genai>=2.21.0` (which introduces `media_processing` on `types.Part` / `types.MediaProcessing.AGENTIC`).
* Update the local virtualenv via `uv pip install "google-genai>=2.21.0"`.

### 2️⃣ Configuration & Video Part Helper
* In [`app/config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/config.py) and [`src/config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/src/config.py):
  * Add `MEDIA_PROCESSING: str = os.getenv("MEDIA_PROCESSING", "agentic")` (options: `"agentic"`, `"static"`).
* Create a dedicated utility function in [`app/tools/video_parser.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/tools/video_parser.py) (and [`src/tools/video_parser.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/src/tools/video_parser.py)):
  ```python
  def create_agentic_video_part(
      video_path_or_uri: str,
      video_bytes: Optional[bytes] = None,
      media_processing: str = "agentic"
  ) -> types.Part:
      """Builds a types.Part with explicit media_processing ('agentic' or 'static')
      supporting both GCS file_uri (gs://...) and inline byte blobs."""
  ```
  * Automatically converts GCS HTTPS showcase URLs (`https://storage.googleapis.com/<bucket>/<object>`) to `gs://<bucket>/<object>` when available, enabling zero-download streaming for Cloud Run and Vertex AI.

### 3️⃣ Quality Rater Agent Video Inspection Upgrades
* In [`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py) (`evaluate_video_clip_quality`):
  * Replace static `Part.from_bytes` with `create_agentic_video_part(video_path=video_path, video_bytes=video_bytes, media_processing=config.MEDIA_PROCESSING)`.
  * Update `QualityRaterAgent` system instructions to direct `gemini-3.7-flash` to leverage agentic video understanding:
    * Pinpoint exact timestamps of motion artifacts, speed changes, or drift.
    * Dynamically inspect character facial consistency against the reference image across all seconds of the clip.
* In [`app/agents/pipeline.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agents/pipeline.py) and [`src/agents/stitcher_graph.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/src/agents/stitcher_graph.py) (`evaluate_clip_quality`):
  * Apply `create_agentic_video_part` with `media_processing="agentic"`.

### 4️⃣ Verification & Testing
* Add unit tests in `tests/unit/test_agentic_video.py` verifying:
  * `types.Part` correctly sets `media_processing="agentic"`.
  * `create_agentic_video_part` correctly handles `gs://` URIs, HTTPS URLs, and local raw byte buffers.
  * Quality Rater executes with agentic video understanding.
* Run full test suite: `uv run pytest tests/unit tests/integration`.

### 5️⃣ Deployment & Documentation
* Build updated container image via Cloud Build and redeploy to Cloud Run (`vidgen-frontend`) in `vital-octagon-19612`.
* Deploy updated agent to Vertex AI Agent Runtime in `vital-octagon-19612`.
* Commit and push changes to GitHub `main`.
