# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-27T09:57:20Z
*   **Target Task:** Automatic User Reference Image Ingestion & Omni Flash Logging
*   **Status:** IN_PROGRESS

---

## 📝 Detailed TODO Breakdown

### Phase 1: Ingestion Callback & Omni Logging [agent] [logging]
- [ ] `[T001]` **[agent]** Update `init_session_state` in [`app/agent.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/agent.py) to extract user-attached images, file URIs, and text image paths directly into `state["canonical_character_reference"]`.
- [ ] `[T002]` **[logging]** Add verbose logging in `generate_omni_clip` ([`app/tools/omni_client.py`](file:///usr/local/google/home/xcyu/projects/reusable/vidgen/app/tools/omni_client.py)) to print the exact control string and payload structure to Cloud Logging.

### Phase 2: Testing & Verification [test]
- [ ] `[T003]` **[test]** Run full test suite (`uv run pytest tests/unit tests/integration`).

### Phase 3: Deployment & Git [deploy] [git]
- [ ] `[T004]` **[deploy]** Deploy agent container to Vertex AI Agent Runtime in `asia-east1`.
- [ ] `[T005]` **[git]** Commit all changes and push to `main` on GitHub.
