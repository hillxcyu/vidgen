# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T07:49:00Z
*   **Target Task:** Restore Intermediate Step & Sub-Agent Messages in Chat UI
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Refactor Agent Instructions & Toolset [agent]
- [ ] `[T001]` **[agent]** Update sub-agent instructions in `app/agent.py` to mandate writing full visible messages in chat before returning control.
- [ ] `[T002]` **[agent]** Remove `generate_multi_shot_video` from `root_agent.tools` and update `root_agent` instruction to enforce step-by-step delegation with visible progress messages.

### Phase 2: Testing & CI/CD [test] [deploy]
- [ ] `[T003]` **[test]** Update `tests/unit/test_agent.py` and run test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T004]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [ ] `[T005]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 3: Verification [verify]
- [ ] `[T006]` **[verify]** Verify live reasoning engine stream query.
