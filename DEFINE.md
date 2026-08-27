# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-27T09:26:25Z
*   **Target Task:** Explicit Reference Image Tool Arguments & Telemetry Response Expose
*   **Status:** IN_PROGRESS

---

## 📝 Detailed TODO Breakdown

### Phase 1: Tool Output & State Scope Refinement [agent] [tool]
- [ ] `[T001]` **[tool]** In `generate_video_shot_clip` ([`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py)), broaden state lookup for reference image paths (`canonical_character_reference`, `reference_image_path`, `user:character_bible['main_character_frame']`) and return `"reference_image_path": ref_img_path` in tool response dictionary.
- [ ] `[T002]` **[agent]** In `vidgen_orchestrator` instructions ([`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py)), add explicit instructions to pass `reference_image_path` when invoking `generate_video_shot_clip`.

### Phase 2: Testing & Verification [test]
- [ ] `[T003]` **[test]** Run full test suite (`uv run pytest tests/unit tests/integration`).

### Phase 3: Deployment & Git [deploy] [git]
- [ ] `[T004]` **[deploy]** Deploy agent update to Vertex AI Agent Runtime in `asia-east1`.
- [ ] `[T005]` **[git]** Commit all changes and push to `main` on GitHub.
