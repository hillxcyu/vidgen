# `PLAN.md`

## 📋 Metadata
*   **Task:** Automatic User Reference Image Ingestion and Omni Flash Verbose Payload Logging
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-27
*   **Status:** IN_PROGRESS

---

## 🎯 Analysis & Objectives

### 1. Root Cause: Why `reference_image_path` was `null` on Shot 1
* When a user attaches an image in chat or mentions an image file in text, ADK delivers it via `callback_context.user_content.parts` (as inline image data, file URI, or text).
* Because the agent previously lacked an automatic extraction hook in `init_session_state`, `state["canonical_character_reference"]` remained empty before Shot 1 ran, causing Shot 1 to execute without reference conditioning (`reference_image_path: null`).

### 2. Implementation Steps
- [ ] In `app/agent.py`:
  - Enhance `init_session_state` to inspect `callback_context.user_content` for inline image data (`part.inline_data`), file URIs (`part.file_data`), and file paths in text, saving uploaded images to `/tmp/vidgen_output/user_uploaded_reference.png` and pre-populating `state["canonical_character_reference"]`.
- [ ] In `app/tools/omni_client.py`:
  - Add comprehensive verbose logging in `generate_omni_clip` that logs the exact model, control string, payload count, reference image count, and frame anchors directly to stdout / Cloud Logging.
- [ ] Run full test suite: `uv run pytest tests/unit tests/integration`.
- [ ] Deploy updated agent container to Vertex AI Agent Runtime in `asia-east1`.
- [ ] Commit and push to GitHub `main`.
