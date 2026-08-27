# `PLAN.md`

## 📋 Metadata
*   **Task:** Implement Full ADK State Management with All Scopes (Session, Temp, User, App)
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-27
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Session-Scoped State (`state["key"]`)**:
   - Capture screenplay in `state["screenplay"]` via `output_key="screenplay"` on `ScreenwriterAgent`.
   - Capture storyboard in `state["storyboard"]` via `output_key="storyboard"` on `StoryboarderAgent`.
   - Record generated shot clips in `state["shots"]` dictionary in `generate_video_shot_clip`.
   - Record final stitched video URL and path in `state["stitched_video_url"]` and `state["stitched_video_path"]` in `concatenate_video_clips`.
   - Record rater feedback and quality metrics in `state["quality_rating"]`, `state["quality_verdict"]`, and `state["rater_feedback"]`.
   - Track pipeline lifecycle in `state["pipeline_stage"]` (`"pre_production"`, `"production"`, `"post_production"`, `"delivered"`).

2. **Temporary / Turn-Scoped State (`state["temp:key"]`)**:
   - Store transient frame paths and intermediate render data in `state["temp:latest_shot_index"]`, `state["temp:first_frame_anchor"]`, and `state["temp:last_frame_anchor"]` during the current turn.

3. **User-Persistent State (`state["user:key"]`)**:
   - Store user preferences that persist across sessions for the same user:
     - `state["user:preferred_aspect_ratio"]` (e.g. `"16:9"` or `"9:16"`)
     - `state["user:preferred_resolution"]` (e.g. `"720p"` or `"1080p"`)
     - `state["user:default_mode"]` (`"i2v_chaining"`)
     - `state["user:total_videos_created"]` (user video counter)

4. **App-Wide State (`state["app:key"]`)**:
   - Store application-level global metrics across all users:
     - `state["app:total_videos_rendered"]` (cumulative counter)
     - `state["app:total_shots_generated"]` (cumulative counter)

5. **Dynamic Prompt State Injection & Tool Context Binding**:
   - Update `app/agent.py` to equip `generate_video_shot_clip`, `parse_initial_frame`, `parse_terminal_frame`, `concatenate_video_clips`, and `evaluate_video_clip_quality` with `tool_context: ToolContext` to write to `tool_context.state`.
   - Configure `output_key` on `ScreenwriterAgent` and `StoryboarderAgent`.
   - Use `{rater_feedback}` and `{storyboard}` placeholders where appropriate.

6. **Testing & Deployment**:
   - Update unit tests in `tests/unit/test_agent.py` to verify state keys and tool context state mutations.
   - Run unit and integration tests (`uv run pytest tests/unit tests/integration`).
   - Commit & push to `main` (Cloud Run deployment).
   - Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

7. **Verification**:
   - Verify that the State tab in the ADK Dev UI clearly renders the rich hierarchical session state, user settings, app counters, and transient artifacts.
