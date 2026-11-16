# Film & Art Director Craft Guide (`vidgen-long-video`)

Process discipline produces a technically valid video. Art direction and cinematographic craft produce a film viewers remember. Read this guide during **Stage 1 (`PLAN`)** and **Stage 2 (`DEFINE`)** before generating scene plates or video clips.

---

## 1. Calibrating the Vision Profile (`VisionProfileSpec`)

Every multi-shot commercial or short film requires a shared `VisionProfileSpec` (`director_plan.json` / `--vision-json`) so parallel scenes, plates, and retries speak one visual language:

| Dimension | Director Decision | Concrete Example |
| :--- | :--- | :--- |
| **Emotional Arc** | Visual emotion per act (*how the frame feels*, not just plot) | `Act 1 Hook`: crisp morning clarity → `Act 2 SKU Hero`: tactile sculptural intimacy → `Act 3 Proof`: effortless warmth → `Act 4 CTA`: luminous confidence |
| **Camera Philosophy** | Relationship of lens to subject (`observer`, `companion`, `macro_showcase`) | `"Companion camera at eye-level that glides with the subject's breath, shifting to 100mm macro stillness on product hero beats."` |
| **Primary Focal Lengths** | 2–3 disciplined focal lengths across the entire film (avoid random zoom jumps) | `[35, 85, 100]` (`35mm` environmental context, `85mm` shallow-DOF portrait, `100mm` macro product detail) |
| **Motivated Lighting** | Every key light has an in-world physical source + fixed contrast ratio | `"Soft directional morning sunlight through tall architectural linen curtains (key-to-fill 2:1, 5200K daylight, subtle warm 3400K rim bounce)."` |
| **3-Color Palette (`60/30/10`)** | Dominant (`60%`), secondary (`30%`), accent (`10%`) + **forbidden colors** | Palette: `["warm travertine ivory", "sage botanical green", "burnished amber gold"]`; Forbidden: `["neon cyan", "harsh magenta", "pure studio white"]` |
| **Audio & Voice Route** | `on_camera`, `off_camera_vo`, `diegetic_only`, or `tpvg_tts` (`gemini-3.8-flash-tts`) | `"Mode E tpvg_tts with Kore voice ('Warm, poised luxury narrator'): on-camera TPVG lip-sync in Acts 1/3/4, off-camera formant-ducked VO in Act 2."` |
| **Verbatim `style_anchor`** | 1-paragraph visual signature appended verbatim to every image & video prompt | `"Shot on large-format digital cinema sensor with vintage prime glass, natural skin micro-texture, soft highlight roll-off, warm travertine and amber-gold palette, zero artificial text overlays."` |

---

## 2. Lens Psychology & Focal-Length Grammar

Choose focal lengths for emotional intent—never leave lens perspective to chance:

| Focal Length | Optical & Emotional Character | Best Use in Multi-Shot Production |
| :--- | :--- | :--- |
| **`24mm`** | Expansive spatial depth, dynamic perspective, architectural scale | Establishing shots, full-body athletic motion, modern retail interiors |
| **`35mm`** | Natural human field of view; places subject organically inside environment | Walk-and-talk hooks, lifestyle context, medium-wide storytelling (`MWS` / `MS`) |
| **`50mm`** | Neutral, composed, honest proportion with zero facial distortion | Balanced waist-up dialogue coverage (`MS` / `MCU`), tabletop demonstrations |
| **`85mm`** | Flattering compression, creamy shallow depth-of-field isolation | Intimate beauty/apparel close-ups (`MCU` / `CU`), emotional reaction beats |
| **`100mm` Macro** | Extreme tactile surface detail, specular micro-highlights, compressed backdrop | Zero-human product SKU hero acts (`CU` / `ECU`), fabric weave, serum droplets, watch/footwear craft |

---

## 3. Editorial & Staging Rules That Prevent Amateur Cuts

1. **The 15-Degree Rule (Hard Cuts in Mode A / Scene Breaks):**
   - Consecutive shots joined by a `0.0s` hard cut **must** shift camera angle by at least `15°` or step framing by at least one shot size (e.g., `35mm MS` → `85mm CU`). Cutting between two near-identical `MS` eye-level angles reads as an accidental jump-cut glitch (`--check-spec` flags duplicate adjacent angles on hard cuts).
2. **The 180-Degree Axis of Action:**
   - Establish a consistent left-to-right screen axis within each scene (e.g., key window light from camera-left, subject moving left-to-right). Reversing light direction or eyeline mid-scene disorients the viewer.
3. **Motivated Camera Movement Only:**
   - Move the camera because the subject or story beat moves:
     - **Dolly-in (`push-in`):** Focusing attention, quiet realization, hero reveal.
     - **Lateral tracking:** Paralleling stride energy (footwear, apparel lookbooks).
     - **Locked-off tripod (`static`):** Composed luxury stillness; explicitly write `"locked-off tripod, stationary frame"` so the model does not drift.
4. **Non-Literal Idiom Staging:**
   - Never turn figures of speech in dialogue into literal props (e.g., if VO says *"unlocking radiant mornings"*, do **not** render a physical brass key). Stage only grounded physical props that belong naturally in the scene and produce coherent foley.

---

## 4. The 8-Layer Director Prompt Architecture

`optimize_shot_prompt_direct` compiles every shot into an 8-layer temporal prompt under ~75 words while enforcing strict GenMedia prompt hygiene:

```text
[1. SHOT SIZE, LENS & ANGLE]  35mm medium close-up at eye level,
[2. FRAME ROLE ANCHOR]        ("Use this image as the starting frame." | "Extend this video: continue seamlessly..." | R2V immediate scene-opening)
[3. ENVIRONMENT & DEPTH]      inside a sunlit travertine sanctuary with soft linen curtains in the background,
[4. BLOCKING & PERFORMANCE]   the subject holds the closed amber dropper bottle at chest height and turns smoothly toward the window light,
[5. TEMPORAL PROGRESSION]     gradually raising the bottle as morning sunbeams catch the glass collar over the shot,
[6. MOTIVATED LIGHTING]       lit by 5200K directional window key light (2:1 soft fill, warm amber rim),
[7. AUDIO / VOICE ROUTE]      (On-camera dialogue | TPVG voice ref | Off-camera VO -> closed lips + diegetic foley only) + "The camera movement itself is completely silent."
[8. VERBATIM STYLE ANCHOR]    <VisionProfileSpec.style_anchor>
```

### Prompt Hygiene Guardrails
- **Avoid Letterbox Triggers:** Never write `"widescreen"`, `"2.39:1"`, `"anamorphic black bars"`, or `"cinema letterbox"` inside video prompts—those tokens cause video models to burn black letterbox bars into `16:9` frames. Use concrete optical terms (`"35mm prime lens"`, `"shallow depth of field"`, `"natural highlight roll-off"`).
- **Silent Camera Mechanics:** Always include `"The camera movement itself is completely silent."` on dolly/crane/tracking shots so the audio decoder does not hallucinate mechanical servo whirring or wind whooshes.
- **Separate On-Camera Speech vs. Off-Camera VO:**
  - When `audio_mode="off_camera_vo"` (e.g., product-only macro shots or lifestyle B-roll narrated in `--mode tpvg_tts`), **omit spoken dialogue from the Omni prompt** and explicitly state `"subject's lips remain naturally closed; subtle diegetic room tone and natural foley only, zero background music"`, then mux the `-16 LUFS` `gemini-3.8-flash-tts` WAV via `media_ops.py mux-voiceover` (`1100 Hz` vocal-formant notch + speech-envelope ducking).
  - When `audio_mode="on_camera"` in `--mode tpvg_tts`, attach the `gemini-3.8-flash-tts` `<= 3.0s` WAV reference chunks (`type: "audio"`) under `task="reference_to_video"` so Omni lip-syncs the actor natively in that exact TTS voice timbre.
