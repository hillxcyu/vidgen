# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T09:30:15Z
*   **Target Task:** Restore Conversational Sub-Agents with Unified Cache-Aligned System Instruction
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Implement Unified System Instruction & Sub-Agent Architecture [agent]
- [ ] `[T001]` **[agent]** Define `UNIFIED_BASE_SYSTEM_INSTRUCTION` in `app/agent.py` establishing global pipeline rules and roles.
- [ ] `[T002]` **[agent]** Attach unified prefix to `ScreenwriterAgent`, `StoryboarderAgent`, `PromptOptimizerAgent`, `HealthCheckerAgent`, and `QualityRaterAgent` with strict visibility directives.
- [ ] `[T003]` **[agent]** Register sub-agents in `root_agent.sub_agents` and keep render/stitch tools in `root_agent.tools`.

### Phase 2: Testing & CI/CD [test] [deploy]
- [ ] `[T004]` **[test]** Update `tests/unit/test_agent.py` to assert sub-agents and tools.
- [ ] `[T005]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T006]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [ ] `[T007]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 3: Verification [verify]
- [ ] `[T008]` **[verify]** Verify live reasoning engine deployment and chat stream output.
