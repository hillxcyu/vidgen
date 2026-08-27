# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-27T08:50:50Z
*   **Target Task:** Reference Image Conditioning, Role Binding & Prompt Optimizer Synergy
*   **Status:** IN_PROGRESS

---

## 📝 Detailed TODO Breakdown

### Phase 1: Omni Client & Control String Refinement [backend] [omni]
- [ ] `[T001]` **[omni]** Enhance `build_omni_control_string` in `app/tools/omni_client.py` to generate explicit subject role-binding directives that instruct Gemini Omni Flash to lock character appearance to the attached reference image.
- [ ] `[T002]` **[omni]** Update `generate_omni_clip` payload in `app/tools/omni_client.py` to prioritize the text instruction first in the `interactions.create` payload list before image items.

### Phase 2: Prompt Optimizer Role-Binding Guidelines [agent] [prompt]
- [ ] `[T003]` **[agent]** Update `PromptOptimizerAgent` instruction in `app/agent.py` to enforce reference-image anchoring rules (preventing competing text physical descriptors).

### Phase 3: Automated Testing & Verification [test]
- [ ] `[T004]` **[test]** Update `tests/unit/test_omni_client.py` to verify new reference directive strings and payload ordering.
- [ ] `[T005]` **[test]** Run full test suite (`uv run pytest tests/unit tests/integration`).

### Phase 4: Deployment & Git [deploy] [git]
- [ ] `[T006]` **[deploy]** Deploy agent update to Vertex AI Agent Runtime in `asia-east1`.
- [ ] `[T007]` **[git]** Commit all changes and push to `main` on GitHub.
