# `PLAN.md`

## 📋 Metadata
*   **Task:** Make Reference Image Explicit in Tool Calling Arguments & Telemetry Response
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-27
*   **Status:** IN_PROGRESS

---

## 🎯 Objectives & Scope

### 1. Root Cause Analysis of Missing `reference_image_path` in Span Tool Arguments
* **Shot 1 Behavior**: In standard text-to-video prompt workflows where no prior image is uploaded, Shot 1 generates text-to-video and extracts the first frame as the canonical reference (`tool_context.state['canonical_character_reference']`).
* **Shot 2+ Auto-Resolution**: While `generate_video_shot_clip` auto-resolves `ref_img_path` from `tool_context.state['canonical_character_reference']` internally, `vidgen_orchestrator` was not explicitly passing `reference_image_path` as an explicit tool call argument in its JSON schema call, and the tool return response did not expose `"reference_image_path"`.

### 2. Implementation Steps
- [ ] Upgrade `generate_video_shot_clip` in `app/agent.py`:
  - Search state across `canonical_character_reference`, `reference_image_path`, and `user:character_bible['main_character_frame']`.
  - Include `"reference_image_path": ref_img_path` in the tool response dictionary so it is clearly logged in Cloud Trace telemetry spans (`gcp.vertex.agent.tool_response`).
- [ ] Update `vidgen_orchestrator` instruction in `app/agent.py`:
  - Explicitly mandate passing `reference_image_path` in `generate_video_shot_clip` whenever a canonical reference is established (for shots $k \ge 2$, or on shot 1 if user supplied an initial image).
- [ ] Run full test suite (`uv run pytest tests/unit tests/integration`).
- [ ] Deploy to Vertex AI Agent Runtime in `asia-east1`.
- [ ] Commit and push to GitHub `main`.
