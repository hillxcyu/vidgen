# `PLAN.md`

## 📋 Metadata
*   **Task:** Implement Advanced Multi-Agent Features (3. HITL Directing Checkpoints ➔ 4. Long-Term Directing Memory ➔ 5. A2A Fleet Collaboration & MCP)
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-27
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

### 3. Human-in-the-Loop (HITL) Interactive Directing Checkpoints
- [ ] **Directing Modes (`state["user:directing_mode"]`)**:
  - `"interactive"` (Default for user creative control): Pauses at key milestones (post-storyboard, post-shot critique) for user review and approval.
  - `"autonomous"` (For automated batch/A2A rendering): Runs end-to-end without pausing.
- [ ] **Pre-Production Storyboard Approval Milestone**:
  - After `StoryboarderAgent` outputs the shot breakdown table, `vidgen_orchestrator` presents the plan and allows the user to approve all shots or adjust individual camera angles, dialogue, or visual prompts before launching video generation.
- [ ] **Interactive Shot Revision & Feedback Trigger**:
  - After `QualityRaterAgent` audits each clip, users can seamlessly direct immediate dual-anchor shot modifications before final assembly.

---

### 4. Long-Term Directing Memory (`MemoryBank` & Character Bible)
- [ ] **ADK Memory Integration**:
  - Register `PreloadMemoryTool` (or `LoadMemoryTool`) in `root_agent.tools`.
  - Add `after_agent_callback` to sync conversational events with ADK `MemoryBank` via `callback_context.add_session_to_memory()`.
- [ ] **Directorial Preferences & Style Memory**:
  - Automatically recall user visual preferences (e.g. *"2.39:1 widescreen, cyber-noir lighting, volumetric fog, orchestral mood"*).
- [ ] **Persistent Character & Universe Bible (`state["user:character_bible"]`)**:
  - Retain character profiles, visual descriptions, and costume details across distinct sessions for recurring characters and multi-episode series.

---

### 5. Agent-to-Agent (A2A) Fleet Collaboration & MCP Ecosystem
- [ ] **A2A Agent Card & Capabilities Declaration**:
  - Enhance `app/app_utils/a2a.py` with structured Agent Card metadata, exposing capabilities (`multi_shot_cinematic_generation`, `dual_anchor_shot_revision`, `multimodal_video_quality_rating`).
- [ ] **MCP Ecosystem Readiness**:
  - Provide MCP tool integrations and exported schemas for external marketing agents, autonomous publishers, and content pipeline orchestrators.

---

## 🧪 Testing & Verification Plan

1. **Unit & Integration Tests**:
   - Test interactive directing mode toggle and state handling.
   - Test memory tools and memory callbacks.
   - Test A2A card generation and endpoint handling.
2. **Regression Testing**:
   - Run full pytest test suite (`uv run pytest tests/unit tests/integration`).
3. **Deployment**:
   - Commit & push to `main` for Cloud Run CI/CD.
   - Deploy to Vertex AI Agent Runtime in `asia-east1`.
