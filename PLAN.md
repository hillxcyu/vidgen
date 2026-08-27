# `PLAN.md`

## 📋 Metadata
*   **Task:** Enhance Reference Image Conditioning & Role Binding in Omni Flash & Prompt Optimizer
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-27
*   **Status:** IN_PROGRESS

---

## 🎯 Objectives & Scope

### 1. Refactor `build_omni_control_string` and `generate_omni_clip` in `app/tools/omni_client.py`
- [ ] Upgrade `build_omni_control_string` to build clean, high-priority natural language role-binding directives (*"Featuring the exact subject depicted in the attached reference image, maintaining their identical facial structure, hair color, and clothing..."*) alongside MMC tags.
- [ ] Optimize the `interactions.create` payload structure to place the primed text directive first before image data parts, maximizing reference cross-attention weights.
- [ ] Ensure seamless cooperation between start frame anchors (`<FIRST_FRAME>`) and character reference assets (`# References <IMAGE_REF_0>[Character A]`).

### 2. Update `PromptOptimizerAgent` in `app/agent.py`
- [ ] Update `PromptOptimizerAgent` instructions: When a reference image is present, avoid re-inventing or competing with physical appearance descriptors in text (avoid conflicting hair colors, jawlines, clothing styles).
- [ ] Direct the optimizer to focus text descriptions on **cinematic camera angles, motion trajectory, volumetric lighting, and scene atmosphere**, explicitly anchoring the actor to the reference image.

### 3. Verification & Deployment
- [ ] Update / add unit tests in `tests/unit/test_omni_client.py` and `tests/unit/test_prompts.py`.
- [ ] Run full test suite: `uv run pytest tests/unit tests/integration`.
- [ ] Deploy updated agent to Vertex AI Agent Runtime (`agents-cli deploy`).
- [ ] Commit and push changes to `main` on GitHub.
