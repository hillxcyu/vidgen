# `PLAN.md`

## 📋 Metadata
*   **Task:** Ensure User-Provided Reference Images are Conditioned Directly on Shot 1 and Preserved
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-27
*   **Status:** IN_PROGRESS

---

## 🎯 Analysis & Objectives

### 1. Root Cause of Why User Reference Images Were Ignored on Shot 1
* **Autonomous Frame Extraction Loop**: Previously, if a user uploaded or referenced an initial character image, the pipeline was designed around auto-extracting Shot 1's first frame (`shot_1_first_frame.png`) *after* Shot 1 finished.
* **Shot 1 Fallback to Text-to-Video**: Because `tool_context.state['canonical_character_reference']` was only populated *after* Shot 1 was generated, Shot 1 defaulted to pure text-to-video if `reference_image_path` was omitted in the tool call args.
* **Downstream Propagation**: Shots 2..N then used Shot 1's newly generated face as the reference, completely discarding the user's original reference image.

### 2. Implementation Steps
- [ ] In `app/agent.py`:
  - Update `init_session_state` and `before_agent_callback` to detect user-provided image assets, file paths, or URLs and pre-populate `state["canonical_character_reference"]` before agent execution.
  - Update `vidgen_orchestrator` instructions: Mandate that when the user attaches or specifies a reference image, `reference_image_path` MUST be passed starting from **Shot 1**.
  - Update `StoryboarderAgent` and `PromptOptimizerAgent`: Enforce reference role binding (`Character A`) starting on **Shot 1** whenever a user reference image is present.
- [ ] Run full test suite: `uv run pytest tests/unit tests/integration`.
- [ ] Deploy updated agent container to Vertex AI Agent Runtime in `asia-east1`.
- [ ] Commit and push to GitHub `main`.
