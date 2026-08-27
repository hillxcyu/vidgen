# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-27T06:20:35Z
*   **Target Task:** Implement Advanced Multi-Agent Features (3. HITL Directing Checkpoints ➔ 4. Long-Term Directing Memory ➔ 5. A2A Fleet Collaboration)
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Human-in-the-Loop (HITL) Directing Checkpoints [agent] [backend]
- [ ] `[T001]` **[agent]** Add `user:directing_mode` (`"interactive"` vs `"autonomous"`) to `init_session_state` in `app/agent.py`.
- [ ] `[T002]` **[agent]** Update `vidgen_orchestrator` instructions to support interactive pre-production review (pausing after storyboard for director feedback when in interactive mode, or auto-proceeding when approved/autonomous).
- [ ] `[T003]` **[agent]** Update `StoryboarderAgent` and `PromptOptimizerAgent` to accept interactive revisions smoothly.

### Phase 2: Long-Term Directing Memory (`MemoryBank` & Character Bible) [memory] [agent]
- [ ] `[T004]` **[memory]** Import and configure `PreloadMemoryTool` from `google.adk.tools.preload_memory_tool` (or `LoadMemoryTool`) in `root_agent.tools`.
- [ ] `[T005]` **[memory]** Add `after_agent_callback=sync_session_to_memory` to `root_agent` to send completed video sessions to ADK `MemoryBank`.
- [ ] `[T006]` **[agent]** Add `user:character_bible` and `user:cinematic_preferences` handling in `init_session_state` and agent instructions for cross-session character & universe persistence.

### Phase 3: Agent-to-Agent (A2A) Fleet Collaboration [a2a] [backend]
- [ ] `[T007]` **[a2a]** Enhance `app/app_utils/a2a.py` with structured skills declaration (`multi_shot_cinematic_generation`, `dual_anchor_shot_revision`, `multimodal_video_quality_rating`) and Agent Card metadata.
- [ ] `[T008]` **[a2a]** Verify A2A endpoint and runner integration in `app/fast_api_app.py`.

### Phase 4: Testing & Verification [test] [deploy]
- [ ] `[T009]` **[test]** Add unit tests for memory tools, directing mode toggles, and A2A card in `tests/unit/test_agent.py` and `tests/unit/test_a2a.py`.
- [ ] `[T010]` **[test]** Run full test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T011]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [ ] `[T012]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1`.
