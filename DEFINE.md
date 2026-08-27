# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-27T09:38:30Z
*   **Target Task:** User-Provided Reference Image Ingestion for Shot 1
*   **Status:** IN_PROGRESS

---

## 📝 Detailed TODO Breakdown

### Phase 1: Callback & Agent Instructions [agent] [callback]
- [ ] `[T001]` **[callback]** Update `init_session_state` in [`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py) to parse user prompt / input events for attached images or referenced image paths and store into `state["canonical_character_reference"]`.
- [ ] `[T002]` **[agent]** Update `vidgen_orchestrator`, `StoryboarderAgent`, and `PromptOptimizerAgent` in [`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py) to explicitly bind Shot 1 to `reference_image_path`.

### Phase 2: Testing & Verification [test]
- [ ] `[T003]` **[test]** Run full test suite (`uv run pytest tests/unit tests/integration`).

### Phase 3: Deployment & Git [deploy] [git]
- [ ] `[T004]` **[deploy]** Deploy agent container to Vertex AI Agent Runtime in `asia-east1`.
- [ ] `[T005]` **[git]** Commit all changes and push to `main` on GitHub.
