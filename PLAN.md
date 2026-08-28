# `PLAN.md`

## 📋 Metadata
*   **Task:** Upgrade Video Generation Model to `gemini-omni-1.1-flash-preview` & Integrate New I2V / R2V Capabilities
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-28
*   **Status:** PENDING_USER_APPROVAL

---

## 🎯 Technical Analysis: What's New in `gemini-omni-1.1-flash-preview`

Based on official documentation from Google Cloud / Gemini Enterprise Agent Platform:

### 1. New I2V (Image-to-Video) & Keyframing Capabilities
* **Dual-Anchor Keyframe Interpolation**:
  * Seamless continuous generation between first and last frames (`<FIRST_FRAME>` and `<LAST_FRAME>`).
  * Enables fluid camera orbits, 360-degree rotations, zoom transitions, and seamless looping clips.
* **360p Draft Mode**:
  * New `resolution="360p"` option in `response_format` for 2x faster prototyping and pre-visualization at lower token cost before rendering the final 720p/1080p/4K take.
* **Scene Extension**:
  * Natively extend scenes in 10-second increments up to 40 seconds total while preserving physical scene persistence.

### 2. New R2V (Reference-to-Video) Capabilities
* **Expanded Reference Limits**:
  * Supports up to **5 image references** (and up to 10 total multimodal images per prompt) for multi-character and prop locking.
* **Video References (New in 1.1)**:
  * In addition to static image references, Omni 1.1 now supports referencing up to **3 seconds of video clips** (`<VIDEO_REF_0>[Scene Reference]`) for motion and style transfer.
* **Native Audio & Action Synchronization**:
  * Generates synchronized dialogue, ambient soundscapes, and foley effects directly matched to character movement.

---

## 📋 Proposed Step-by-Step Plan

1. **Update Default Model Configuration**:
   * Update `Config.VIDEO_GEN_MODEL` in [`app/config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/config.py) and [`src/config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/src/config.py) to `"gemini-omni-1.1-flash-preview"`.
   * Update [`agent.yaml`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/agent.yaml), [`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py), and documentation (`GEMINI.md`, `README.md`, `interaction_explained.md`).

2. **Update Tests**:
   * Update unit test assertions in [`tests/unit/test_config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/tests/unit/test_config.py), [`tests/test_config.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/tests/test_config.py), and [`tests/test_omni_client.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/tests/test_omni_client.py).

3. **Verify via Pytest**:
   * Run `uv run pytest tests/unit tests/integration` to verify that all 31 unit and integration tests pass with `gemini-omni-1.1-flash-preview`.

4. **Deploy & Commit**:
   * Deploy the updated agent container to Vertex AI Agent Runtime in `asia-east1`.
   * Commit all changes and push to GitHub `main`.
