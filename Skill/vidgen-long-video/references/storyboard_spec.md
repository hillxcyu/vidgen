# Storyboard, Vision Profile & Multi-Scene JSON Schemas

Use `--storyboard-json` (single-scene) or `--scenes-json` (multi-scene
`60s-120s+`) together with optional `--vision-json` to control every
cinematographic, audio/TTS, and evaluation detail deterministically.

--------------------------------------------------------------------------------

## 1. Vision Profile Schema (`VisionProfileSpec` / `--vision-json`)

Generated automatically during `--stage plan` (`director_plan.json`) or authored
manually:

```json
{
  "project_title": "Aurora Botanical Serum - Morning Ritual",
  "emotional_arc": "Crisp sunlit awakening -> tactile golden-drop intimacy -> poised all-day radiance",
  "camera_philosophy": "Companion eye-level prime camera moving gently with subject breath; locked 100mm macro on product hero beats.",
  "primary_focal_lengths_mm": [35, 85, 100],
  "lighting_motivation": "5200K directional morning sunlight through tall linen curtains, 2:1 soft fill, warm 3400K rim bounce.",
  "contrast_ratio": "2:1 high-key natural luxury",
  "color_palette": ["warm travertine ivory", "champagne satin", "burnished amber gold", "soft sage"],
  "forbidden_colors": ["neon cyan", "oversaturated magenta", "harsh pure-white cyclorama"],
  "anti_references": ["shaky handheld vlog", "letterbox black bars", "floating CGI text"],
  "audio_mode": "tpvg_tts",
  "tts_voice": "Kore",
  "tts_style": "Warm, poised, intimate luxury skincare narrator",
  "style_anchor": "Shot on large-format digital cinema sensor with vintage prime lenses, natural skin micro-texture, soft highlight roll-off, warm travertine and amber-gold palette, zero text overlays."
}
```

--------------------------------------------------------------------------------

## 2. Shot Schema (`StoryboardEntrySpec` / `--storyboard-json`)

`storyboard.json` is a JSON array of shot objects (`1..N`). All new
cinematographic fields are optional and 100% backwards-compatible:

```json
[
  {
    "scene_number": 1,
    "description": "An East Asian woman in a terracotta linen trench coat walks briskly along a sunlit Parisian limestone colonnade, morning light catching the fabric drape.",
    "camera_angle": "eye-level tracking",
    "shot_size": "MS",
    "focal_length_mm": 35,
    "lighting_spec": "5200K directional morning sun from camera-left through colonnade arches, 2:1 soft bounce fill",
    "blocking_and_temporal_flow": "Subject enters from left third at steady pace, pauses gently at colonnade pillar as breeze lifts coat lapel",
    "audio_mode": "on_camera",
    "tts_voice": "Kore",
    "tts_style": "Warm, poised editorial confidence",
    "evaluation_criteria": "Verify exact terracotta trench coat lapel, button count, and belt buckle match the #FFFFFF reference anchor.",
    "fails_if": "Frame 0 shows white studio backdrop, coat color shifts, or extra buttons appear.",
    "spoken_dialogue": "Tailored linen designed to move effortlessly through morning light.",
    "mode_override": "reference",
    "duration_sec": 10
  },
  {
    "scene_number": 2,
    "description": "Macro showcase of the woven terracotta linen belt buckle and lapel stitching resting on sunlit limestone.",
    "camera_angle": "low-angle slow push-in",
    "shot_size": "ECU",
    "focal_length_mm": 100,
    "lighting_spec": "Raking golden morning sun highlighting linen weave texture",
    "blocking_and_temporal_flow": "Zero human presence; camera glides 15cm forward focusing across stitched lapel edge",
    "audio_mode": "off_camera_vo",
    "evaluation_criteria": "100% product-only macro frame with zero human hands/faces and crisp linen weave.",
    "fails_if": "Any human hand or face appears, or camera jump-cuts.",
    "spoken_dialogue": "Breathable structure meets timeless modern craft.",
    "mode_override": "reference",
    "duration_sec": 8
  }
]
```

### Field Reference

Field                        | Type          | Req | Description
:--------------------------- | :------------ | :-: | :----------
`scene_number`               | `int`         | Yes | `1`-based shot index (`1`, `2`, `3`, ...).
`description`                | `str`         | Yes | Visual setting, subject action, and material detail (single unbroken camera take).
`camera_angle`               | `str`         | Yes | Angle + movement descriptor (e.g., `"eye-level smooth dolly-in"`, `"low-angle lateral tracking"`).
`shot_size`                  | `str \| null` | No  | Framing scale: `"WS"`, `"MWS"`, `"MS"`, `"MCU"`, `"CU"`, or `"ECU"`.
`focal_length_mm`            | `int \| null` | No  | Prime lens focal length in mm (e.g., `24`, `35`, `50`, `85`, `100`).
`lighting_spec`              | `str \| null` | No  | Motivated key light source, Kelvin temperature, and contrast ratio.
`blocking_and_temporal_flow` | `str \| null` | No  | Beat-by-beat physical progression from `t=0s` to `duration_sec`.
`audio_mode`                 | `str \| null` | No  | `"auto"` (default), `"on_camera"` (lip-synced speech), `"off_camera_vo"` (closed lips + ducked VO mix in `tpvg_tts`), or `"diegetic_only"` (no speech).
`tts_voice` / `tts_style`    | `str \| null` | No  | Per-shot override for `--mode tpvg_tts` (`gemini-3.8-flash-tts` voice name & acting style).
`evaluation_criteria`        | `str`         | Yes | Shot-specific checklist passed to Auto-Rater v2 (`gemini-3.8-flash` AVU).
`fails_if`                   | `str \| null` | No  | Concrete observable failure condition appended to the Auto-Rater v2 rubric.
`spoken_dialogue`            | `str \| null` | No  | Verbatim spoken line (paced `<= 2.2 words/sec` so speech finishes `~2s` before `duration_sec`).
`mode_override`              | `str \| null` | No  | Per-shot override: `"reference"`, `"i2v_chaining"`, `"video_extend"`, or `"tpvg_tts"`.
`duration_sec`               | `int \| null` | No  | Per-shot duration (`3-15s` for R2V/I2V/T2V; auto-clamped to `3-10s` for `video_extend` and two-frame interpolation).

--------------------------------------------------------------------------------

## 3. Continuity & Voice Modes (`--mode`)

Mode (`--mode`)               | Visual & Voice Conditioning                                                                                                                                                                                                                                                                                                                                          | Best Use Case
:---------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------
**`reference`** *(Mode A)*    | Concurrent `#FFFFFF` `task="reference_to_video"` (`3s-15s`, `0.0s` hard-cuts)                                                                                                                                                                                                                                                                                        | Fast multi-location montages (`~3x` wall-clock speed)
**`i2v_chaining`** *(Mode B)* | Shot 1 R2V → Shots `2..N` `<FIRST_FRAME>` `task="image_to_video"` (`3s-15s`)                                                                                                                                                                                                                                                                                         | Controlled sequential camera progressions
**`video_extend`** *(Mode C)* | Shot 1 R2V → Shots `2..N` `5.0s` `<VIDEO_0>` tail `task="extend"` (`3s-10s`)                                                                                                                                                                                                                                                                                         | Same-room unbroken single-take commercials
**`hybrid`** *(Mode D)*       | Per-shot `mode_override` mixing `reference` act breaks + `video_extend`                                                                                                                                                                                                                                                                                              | Multi-act commercials across distinct rooms
**`tpvg_tts`** *(Mode E)*     | **`gemini-3.8-flash-tts` (`gemini-3.8-tts`)** synthesizes `shot_k_tts.wav` first → **`on_camera`** shots pass `<= 3.0s × 5` WAV chunks as TPVG `type: "audio"` R2V voice refs (lip-synced in exact TTS voice) + TPVG-unlocked `video_extend`; **`off_camera_vo`** shots render pure diegetic video and mux `-16 LUFS` TTS WAV with `1100 Hz` formant notch + ducking | Studio-grade consistent voice acting, multilingual/accent control, custom replicated voices, and hybrid spokesperson + product-macro ads

--------------------------------------------------------------------------------

## 4. Hierarchical Multi-Scene Schema (`--scenes-json` for `60s-120s+`)

```json
{
  "original_intent": "90s 4-act botanical serum commercial combining spokesperson chapters and product-only macro showcase",
  "vision_profile": {
    "project_title": "Aurora Botanical Serum",
    "primary_focal_lengths_mm": [35, 85, 100],
    "color_palette": ["warm travertine ivory", "champagne satin", "amber gold"],
    "forbidden_colors": ["neon cyan", "harsh magenta"],
    "tts_voice": "Kore",
    "tts_style": "Warm, poised luxury skincare narrator",
    "style_anchor": "Shot on large-format cinema sensor with vintage prime lenses, soft natural daylight, warm travertine and amber-gold palette, zero text overlays."
  },
  "scenes": [
    {
      "scene_id": "act_1_hook",
      "title": "Act 1 - Morning Sanctuary Hook",
      "mode": "tpvg_tts",
      "duration_sec": 10,
      "scene_plate_prompt": "Sunlit beige travertine spa bathroom vanity with tall linen curtains, 16:9 architectural interior, zero people, zero text",
      "reference_paths": [
        "output/beauty_90s/refs/hero_anchor.png",
        "output/beauty_90s/refs/act1_plate.png"
      ],
      "shots": [
        {
          "scene_number": 1,
          "shot_size": "MCU",
          "focal_length_mm": 50,
          "camera_angle": "eye-level slow dolly-in",
          "audio_mode": "on_camera",
          "description": "Spokesperson holds the closed amber dropper bottle beside sunlit travertine vanity.",
          "evaluation_criteria": "Exact spokesperson, satin blazer, and closed amber bottle in sunlit travertine room.",
          "fails_if": "White studio backdrop appears or bottle cap detaches.",
          "spoken_dialogue": "Every morning begins with one luminous golden drop."
        }
      ]
    }
  ]
}
```
