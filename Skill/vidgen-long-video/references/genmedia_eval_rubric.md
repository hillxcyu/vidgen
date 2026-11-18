# GenMedia Video Evaluation Rubric, Defect Remedies & HITL Protocol

Every generated take and stitched master is audited by **Auto-Rater v2**
(`gemini-3.8-flash` with `MediaProcessing.AGENTIC` + captioned `KEY FRAME A/M/B`
PNGs + OpenCV/FFMPEG telemetry). Rather than vague aesthetic scores, the rater
extracts **observable facts and explicit GenMedia defect codes** *before*
computing `score` (`0.0-1.0`).

--------------------------------------------------------------------------------

## 1. 10-Category GenMedia Defect Taxonomy (`GENMEDIA_DEFECT_TAXONOMY`)

Auto-Rater v2 populates `detected_genmedia_issues: List[str]` strictly before
`reason`, `score`, and `verdict`. Whenever a take scores `< 0.80` and retries,
`format_genmedia_remedy_guidance(...)` injects the matching **Director Retry
Remedy** directly into `PromptOptimizer`:

Defect Code                             | Observable Failure (`fails_if`)                                                                                                                                              | Automatic Director Retry Remedy
:-------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------
**`r2v_white_backdrop_echo`**           | Frame 0 (`KEY FRAME A`) opens on a plain `#FFFFFF` studio backdrop (`r2v_f0_mae < 12.0` or white pixels `> 25%`) instead of the target environment.                          | Open immediately on Frame 0 inside the physical scene with concrete foreground/background set dressing; remove any mention of studio/white backgrounds.
**`identity_or_sku_drift`**             | Facial geometry, hair, wardrobe silhouette/color, or product bottle/shoe proportions drift from the `#FFFFFF` anchor across `KEY FRAME A -> M -> B`.                         | Remove competing appearance adjectives; lock medium/MCU framing, slow subject rotation, and keep the product/subject clearly facing camera.
**`text_or_logo_garbling`**             | Packaging typography warps/melts, background signs show gibberish glyphs, or unprompted third-party logos/swooshes appear.                                                   | Forbid background signage/posters, hold hero packaging steady on-axis with gentle camera motion, and prohibit third-party brand marks.
**`hand_or_anatomy_morphing`**          | Extra/fused fingers, twisted wrists, or prop-grip clipping during complex hand-object interactions (uncapping, pouring, lacing).                                             | Simplify hand choreography to a clean pre-established grip or single gentle gesture (or shift to a product-on-plinth macro shot).
**`physics_or_gravity_violation`**      | Floating objects, upward-flowing droplets, cloth/body clipping through tables, or feet sliding across the floor (`moonwalking`).                                             | Anchor contact surfaces explicitly (`"resting firmly on travertine stone"`), slow movement pace, and describe natural weight and gravity.
**`unmotivated_camera_jitter_or_cuts`** | `detected_internal_cuts > 0` (abrupt jump-cuts or mid-clip soft dissolves), whip-pan smear, or shaky drift on a static shot.                                                 | Enforce a single continuous camera verb (`"locked-off tripod"` or `"one slow continuous dolly-in"`) and remove multi-beat camera switches.
**`lighting_or_color_flicker`**         | Exposure or white-balance pumps mid-shot, key-light side flips, forbidden palette colors intrude, or background props vanish.                                                | Lock one motivated light source, fixed Kelvin temperature, and stable background set elements throughout the shot.
**`lip_sync_or_speech_mismatch`**       | Subject's mouth moves during `off_camera_vo`, lips stay frozen during `on_camera` dialogue, `transcript_wer > 0.35`, or speech clips at tail (`trailing_rms_db > -26 dBFS`). | Match `audio_mode` strictly (`closed lips` for `off_camera_vo`; clear front/three-quarter lip visibility for `on_camera`) and pace speech to finish `>= 2.0s` before clip end.
**`unwanted_music_or_audio_collision`** | Unrequested dramatic background music or camera-whoosh noise is generated inside a clip, clashing at `80ms` shot seams.                                                      | Enforce `"diegetic room tone and subtle natural foley only, zero background music; the camera movement itself is completely silent."`
**`seam_jump_or_momentum_stall`**       | `seam_mae > 28.0` pose/framing jump at Shot `k-1 -> k` boundary, or camera stalls motionless at `t=0.0s` before restarting.                                                  | Match the outgoing shot's exact framing, lighting, and motion momentum vector, or bridge via `<FIRST_FRAME> + <LAST_FRAME>` two-frame interpolation.

--------------------------------------------------------------------------------

## 2. Deterministic Post-Rater Caps (Hard Guardrails)

Even if multimodal reasoning is generous, deterministic OpenCV/FFMPEG checks cap
`score` below `0.80` (`REATTEMPT_REQUIRED`):

1.  **R2V `#FFFFFF` Studio Lock:** `r2v_f0_mae < 12.0` → immediate retry
    (`score <= 0.35`).
2.  **Extension Boundary Jump-Cut:** `peak_early_mae > 28.0` over frames `0..4`
    → immediate retry (`score <= 0.40`).
3.  **Internal Cuts / Soft Dissolves:** `detected_internal_cuts > 0` →
    `score = min(score, 0.60)`.
4.  **Trailing `0.20s` Speech Cutoff:** `trailing_rms_db > -26 dBFS` or
    `speech_end_sec > clip_dur - 0.15s` → `score = min(score, 0.65)`.
5.  **Spoken Dialogue Drift:** Word-level Levenshtein `transcript_wer > 0.35` →
    `score = min(score, 0.68)`.

--------------------------------------------------------------------------------

## 3. Pre-Flight Spec Validation (`--check-spec`)

Run `--check-spec` during **Stage 2 (`DEFINE`)** before launching paid video
renders. `validate_production_spec` verifies:

-   **Speech Pacing Budget:** Each shot's `spoken_dialogue` fits comfortably
    inside `max(1.5, duration_sec - 2.0)` seconds (`<= 2.4 words/sec`, target
    `~2.1 words/sec` / `~130 WPM`).
-   **GA Duration Ceilings:** `3s-15s` for `reference_to_video`,
    `image_to_video`, and `T2V`; `3s-10s` for `video_extend` and
    `<FIRST_FRAME>+<LAST_FRAME>` interpolation.
-   **Reference Asset Integrity:** Every path in `--reference` /
    `SceneSpec.reference_paths` exists on disk and decodes as valid
    PNG/JPEG/WebP.
-   **15-Degree Hard-Cut Check:** Adjacent Mode A (`reference`) shots with
    identical `camera_angle` and `shot_size` emit a jump-cut warning.
-   **Observable Criteria:** Every shot carries non-empty `evaluation_criteria`
    (and optional `fails_if`).

--------------------------------------------------------------------------------

## 4. Dual Human-in-the-Loop (HITL) Gates

By default, interactive runs enforce two structured director gates (bypassed
only when `--auto-approve` is passed for unattended batch execution):

### Gate 1 — Pre-Render Plan & Keyframe/Plate Contact Sheet Review (`--stage plan` & `--stage plates`)

1.  Generate `director_plan.md`, `director_plan.json`, and
    `storyboard_defined.json` via `--stage plan` and run `--check-spec`.
2.  Synthesize/collect architectural scene plates + `#FFFFFF` anchors via
    `--stage plates`, which renders `plates_contact_sheet.png`
    (`media_ops.py contact-sheet`).
3.  Inspect `plates_contact_sheet.png` yourself first (regenerating any plate
    with text, watermarks, or unwanted people), then present the plan + contact
    sheet to the user for approval before running `--stage execute`.

### Gate 2 — Post-Retry Escalation Gate (`escalation_report.json` + `qa_contact_sheet.png`)

During `--stage execute`, the pipeline automatically runs Best-of-`K` retries
with defect-specific remedies and `<FIRST_FRAME>+<LAST_FRAME>` interpolation
self-healing, then renders `qa_contact_sheet.png`. If any shot still scores
`< quality_threshold` (or the stitched master seam critic scores `< 0.75`):

-   `run_vidgen_workflow.py` writes `escalation_report.json` in `--output-dir`
    listing every unresolved shot, its `quality_score`,
    `detected_genmedia_issues`, `feedback`, and **3 concrete remediation
    options**:
    -   **Option A (`accept_best_take`):** Approve the highest-scoring
        checkpointed take as-is (`--auto-approve --resume`).
    -   **Option B (`revise_shot_and_resume`):** Delete/archive only the flagged
        `shot_k.mp4`, adjust its `StoryboardEntrySpec` (`description`,
        `camera_angle`, `audio_mode`, or `spoken_dialogue`), and re-run with
        `--resume`.
    -   **Option C (`swap_plate_or_mode`):** Regenerate the scene plate /
        `#FFFFFF` anchor or switch `mode_override` (e.g., `video_extend` →
        `reference` act break) and re-run `--resume`.
-   Unless `--auto-approve` is set, the CLI exits with return code **`2`**
    (`status: "human_review_required"`) so the calling agent pauses and asks the
    human director which option to take.
