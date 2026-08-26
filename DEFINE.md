# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T08:59:30Z
*   **Target Task:** Refactor Architecture to ADK `AgentTool` Pattern for 100% Context Cache Alignment
*   **Status:** ✅ ALL_TASKS_COMPLETED

---

## 📝 Detailed TODO Breakdown

### Phase 1: Implement `AgentTool` Architecture in `app/agent.py` [agent]
- [x] `[T001]` **[agent]** Import `AgentTool` in `app/agent.py`.
- [x] `[T002]` **[agent]** Refactor `ScreenwriterAgent`, `StoryboarderAgent`, `PromptOptimizerAgent`, `HealthCheckerAgent`, and `QualityRaterAgent` instructions for clean tool-return execution.
- [x] `[T003]` **[agent]** Wrap the 5 sub-agents in `AgentTool(...)` and register in `root_agent.tools`, setting `sub_agents=[]` on `root_agent`.

### Phase 2: Testing & CI/CD [test] [deploy]
- [x] `[T004]` **[test]** Update `tests/unit/test_agent.py` to assert `AgentTool` names in `root_agent.tools`.
- [x] `[T005]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [x] `[T006]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [x] `[T007]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 3: Verification [verify]
- [x] `[T008]` **[verify]** Verify live reasoning engine deployment and context cache alignment.
