# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-27T03:16:25Z
*   **Target Task:** Implement Full ADK State Management with All Scopes (Session, Temp, User, App)
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Agent Output Keys & Dynamic State Binding [agent]
- [ ] `[T001]` **[agent]** Add `output_key="screenplay"` to `ScreenwriterAgent` and `output_key="storyboard"` to `StoryboarderAgent` in `app/agent.py`.
- [ ] `[T002]` **[agent]** Update agent instructions to reference `{screenplay}`, `{storyboard}`, `{rater_feedback}` where appropriate while preserving cache-aligned prefix.

### Phase 2: Tool Context State Mutations Across All 4 Scopes [tools] [agent]
- [ ] `[T003]` **[tools]** Update `generate_video_shot_clip` to write `state["shots"]`, `state["temp:latest_rendered_shot"]`, increment `state["app:total_shots_generated"]` and `state["user:total_shots_generated"]`.
- [ ] `[T004]` **[tools]** Update `parse_initial_frame` and `parse_terminal_frame` to write `state["temp:first_frame_anchor"]` and `state["temp:last_frame_anchor"]`.
- [ ] `[T005]` **[tools]** Update `evaluate_video_clip_quality` to accept `tool_context: Optional[ToolContext]` and record `state["quality_rating"]`, `state["quality_verdict"]`, and `state["rater_feedback"]`.
- [ ] `[T006]` **[tools]** Update `concatenate_video_clips` to record `state["stitched_video_url"]`, `state["stitched_video_path"]`, set `state["pipeline_stage"] = "delivered"`, and increment `state["app:total_videos_rendered"]` and `state["user:total_videos_created"]`.

### Phase 3: Testing & CI/CD [test] [deploy]
- [ ] `[T007]` **[test]** Update `tests/unit/test_agent.py` and `tests/unit/test_state.py` to test state mutations and keys.
- [ ] `[T008]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T009]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [ ] `[T010]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 4: Verification [verify]
- [ ] `[T011]` **[verify]** Verify live reasoning engine deployment and state tab visualization.
