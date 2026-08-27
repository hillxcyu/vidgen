# `ACTION.md`

## 📋 Metadata
*   **Execution Task:** Fix KeyError ('Context variable not found: `k`') in Agent Instruction Templating
*   **Started At:** 2026-08-27T07:37:00Z
*   **Completed At:** 2026-08-27T07:38:15Z
*   **Status:** COMPLETED_SUCCESSFULLY

---

## 📜 Execution Log

### Root Cause Analysis & Fix
* **Issue**: Google ADK treats raw curly braces `{k}`, `{score}`, `{user:...}` inside `Agent.instruction` as state/context variable template references. Since `k` was used as a natural language loop indicator in our instructions rather than an ADK state variable, ADK raised `KeyError: 'Context variable not found: k'`.
* **Fix**:
  * Removed raw curly braces from all prompt and instruction strings in `app/agent.py` (replaced with descriptive text `Shot k`, `Shot k+1`, `user:character_bible`, `user:cinematic_style`).
* **Verification**:
  * Ran all 31 unit and integration tests (`uv run pytest tests/unit tests/integration`): **31/31 passed (100%)**.
  * Committed and pushed to `main` (`commit 371f271`).
