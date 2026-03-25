# Quick Gen v2.0 — Complete Design Specification

## Overview

Quick Gen is an enhanced Wan2GP plugin that provides a simplified, all-in-one NSFW I2V workflow.
The user uploads a reference image, picks a scene, and clicks Generate — the plugin handles
model selection, LoRA loading, prompt construction, and generation settings automatically.

**Architecture:** Enhanced Gradio plugin tab within Wan2GP (Option B).
**Target hardware:** RTX 3060 12GB VRAM.
**Base model:** wan2.2-i2v-rapid-aio-v10-nsfw-Q3_K.gguf (7.6GB)

---

## Progressive Disclosure — Three UI Modes

The plugin uses progressive disclosure to prevent overwhelm. A toggle in the header switches
between modes. The system remembers the last-used mode.

### Simple Mode (3 controls)
For first-time users or when you just want to generate quickly.
- Image upload (drag-and-drop)
- Scene dropdown (10 scenes)
- Generate button

Everything else uses smart defaults from the scene preset.

### Standard Mode (default after first use)
The day-to-day workflow with meaningful controls exposed.
- Everything in Simple, plus:
- Type panel (persistent body/appearance settings)
- Image Fidelity <-> Motion Freedom slider
- Intensity selector (Gentle / Rough / Extreme)
- Duration (scene-optimized defaults)
- Camera angle selector
- Quick modifier chips (multi-select)
- Aspect ratio (Landscape / Portrait / Square)
- Quality preset (Draft 4-step / Standard 8-step / High 12-step)
- Seed display + lock + variation buttons
- Keeper actions (star, redo, continue, different scene)
- Session history strip

### Full Mode (power users)
Everything exposed, including direct control over all parameters.
- Everything in Standard, plus:
- Environment picker (Studio / Bedroom / Bathroom / Hotel / Dark / None)
- Lighting style (Studio / Dramatic / Ring light / Natural / Low-key)
- POV / male visibility (POV hands only / POV minimal body / Third person)
- Tempo (Slow / Building / Aggressive)
- Audio generation toggle + intensity
- AI prompt enhancer toggle
- Body emphasis slider (implant size)
- Face lock toggle + strength
- Shine/oil slider (Matte -> Natural -> Glossy -> Drenched)
- Gaze direction (Camera / Looking up / Eyes closed / Eyes rolling / Away)
- Hair state (Loose / Ponytail / Gripped / Messy)
- Color temperature (Warm / Neutral / Cool)
- Background blur / DoF slider
- Realism guardian toggle
- Per-LoRA weight overrides
- Editable prompt + negative prompt
- Motion tuning sliders (amplitude, flow shift, smoothness)

---

## Component Layout (Standard Mode)

```
+------------------------------------------------------------------+
| Quick Gen                            [Simple|Standard|Full] Mode  |
| Upload. Pick. Generate.                                          |
+------------------------------------------------------------------+
| [VRAM: 8.2/12GB] [GPU: 72C] [Model: Ready]   [Disk: 4.2GB used] |
+------------------------------------------------------------------+
|                                                                    |
| +--LEFT COLUMN (40%)------+  +--RIGHT COLUMN (60%)-------------+ |
| |                          |  |                                  | |
| |  [IMAGE UPLOAD]          |  |  Scene: [Deepthroat / Facefuck] | |
| |   drag & drop            |  |                                  | |
| |   or click to browse     |  |  Type Panel (persistent):        | |
| |                          |  |   Body: [Skinny + Bolt-ons]      | |
| |  Image hint:             |  |   Skin: [Fair|Tan|Dark]          | |
| |  "Face-forward close-up  |  |   Hair: [Blonde|Brunette|...]    | |
| |   works best for this    |  |   Makeup: [Glam|Natural|Messy]   | |
| |   scene"                 |  |   Aesthetic: [Pornstar glam]     | |
| |                          |  |                                  | |
| |  Auto-crop:              |  |  Image Fidelity <======|=> Motion| |
| |  [Full|Face+Upper|Torso] |  |  "Looks like her" ... "More motion" |
| |                          |  |                                  | |
| |  Recent images:          |  |  Intensity: [Gentle|ROUGH|Extreme]| |
| |  [thumb][thumb][thumb]   |  |  Duration: [3s - one DT cycle]   | |
| |                          |  |  Camera: [POV above|Side|Below]  | |
| +---------------------------+  |  Quality: [Draft|Standard|High]  | |
|                                |  Aspect: [Landscape|Portrait|Sq] | |
|                                +----------------------------------+ |
|                                                                    |
| Modifiers: [Oily] [Sweaty] [Saliva] [Mascara] [Eye contact]      |
|            [Throat bulge] [Tears] [Slow-mo] [Film grain]          |
|                                                                    |
| +--------------------------------------------------------------+  |
| |  [GENERATE VIDEO]              Est: ~35s  |  [Cancel]        |  |
| |  ========================================= 45%               |  |
| +--------------------------------------------------------------+  |
|                                                                    |
| "What you're generating" preview (collapsed):                      |
| Scene: Deepthroat, 6 LoRAs loaded, 480x848 portrait, 4 steps...  |
|                                                                    |
| +------RESULT AREA-----------------------------------------+      |
| |  [Reference Image]  |  [Generated Video (looping)]       |      |
| |   (pinned left)     |   (plays right)                    |      |
| |                     |                                     |      |
| |                     |  [Play/Pause] [0.5x] [Scrub====]   |      |
| +----------------------------------------------------------+      |
|                                                                    |
| Keeper Actions:                                                    |
| [Star] [Redo (new seed)] [Redo (higher quality)]                  |
| [Continue (+2-4s)] [Same woman, different scene]                  |
| [Seed: 48291] [Lock seed] [Variations (+-1,+-2)]                  |
|                                                                    |
| Seed: 48291  |  Changed: Intensity Medium->High                   |
|                                                                    |
| Session Strip (scrollable):                                        |
| [vid1][vid2][vid3][vid4][vid5][vid6]...                           |
|  DT*   Gag   DT    Cow   DT*   Body                              |
+------------------------------------------------------------------+
```

---

## Data Architecture

### Scene Preset JSON (existing format, extended)

Each scene preset JSON file in `profiles/wan_2_2/` retains its current format:
```json
{
    "activated_loras": ["Instareal.safetensors", "..."],
    "loras_multipliers": "0.8 0.7 0.9",
    "num_inference_steps": 4,
    "guidance_phases": 2,
    "guidance_scale": 1,
    "negative_prompt": "..."
}
```

### Scene Metadata (NEW — `scene_meta.json` in plugin dir)

Extended scene metadata that the plugin owns, separate from the generation presets:
```json
{
    "Deepthroat / Facefuck": {
        "prompt": "POV from above, aggressive rough deepthroat facefuck...",
        "base_prompt": "photorealistic 8k uhd...",
        "negative_extra": "closed mouth, teeth visible, tongue wrong direction",
        "default_duration_seconds": 3,
        "default_aspect": "portrait",
        "default_fidelity": 0.5,
        "default_camera": "pov_above",
        "image_hint": "Face-forward close-up works best for this scene",
        "optimal_crop": "face_upper",
        "scene_category": "oral",
        "implant_motion": "stationary, hanging shape maintained",
        "implant_motion_negative": "independent jiggling, soft bouncing",
        "thumbnail": "thumbs/deepthroat.png",
        "lora_skip": ["Face_to_Feet_Motion_Camera"],
        "lora_warn": {"Stomach_Bulge": "designed for penetration scenes"},
        "male_default": "pov_hands",
        "auto_audio_prompt": "gagging sounds, choking, wet sounds, moaning"
    }
}
```

### Character Profile (NEW — `characters/` dir in plugin)

```json
{
    "name": "Character A",
    "reference_images": ["characters/char_a/ref1.png", "characters/char_a/ref2.png"],
    "type_settings": {
        "body": "skinny_boltons",
        "skin_tone": "fair",
        "hair": "blonde",
        "makeup": "pornstar_glam",
        "aesthetic": "pornstar"
    },
    "preferred_fidelity": 0.45,
    "proven_seeds": [48291, 12044, 77321],
    "anti_seeds": [99812],
    "notes": "Works best with POV scenes, face holds well at fidelity 0.45"
}
```

### Generation Record (NEW — metadata per output)

Sidecar JSON saved alongside every generated video:
```json
{
    "timestamp": "2026-03-24T14:32:01",
    "seed": 48291,
    "scene": "Deepthroat / Facefuck",
    "character": "Character A",
    "reference_image": "path/to/ref.png",
    "fidelity": 0.5,
    "intensity": "rough",
    "duration_frames": 81,
    "resolution": "480x848",
    "steps": 4,
    "quality": "draft",
    "loras": {"Instareal": 0.8, "General_NSFW": 0.7, "...": "..."},
    "prompt": "full prompt text...",
    "negative_prompt": "full negative...",
    "modifiers": ["oily", "mascara_running", "eye_contact"],
    "camera": "pov_above",
    "aspect": "portrait",
    "starred": false,
    "continuation_depth": 0,
    "parent_video": null,
    "generation_time_seconds": 35.2,
    "peak_vram_gb": 10.8
}
```

### Analytics Store (NEW — `analytics.json` in plugin data dir)

Aggregated stats from generation records, used for adaptive learning:
```json
{
    "scene_stats": {
        "Deepthroat / Facefuck": {
            "total_generations": 47,
            "starred_count": 12,
            "avg_starred_fidelity": 0.45,
            "avg_starred_intensity": "rough",
            "best_seeds": [48291, 12044],
            "avg_generation_time": 38.2
        }
    },
    "global_stats": {
        "total_generations": 203,
        "total_starred": 41,
        "avg_session_length": 18,
        "most_used_modifiers": ["oily", "eye_contact", "mascara_running"]
    }
}
```

---

## Prompt Construction Pipeline

The prompt is built in layers, each appending to the final string:

```
Layer 1: Base body prompt (from Type panel)
  "extremely underweight, dangerously thin, anorexic body type, visible rib cage,
   protruding hip bones, concave stomach, thigh gap, skeletal frame,
   rigid spherical silicone breast implants, bolt-on, gravity-defying,
   implant edges visible under stretched taut skin, breasts maintain round
   shape in all positions, minimal natural bounce, implants move as rigid
   unit with torso, visible implant contour, skin stretched thin over implant"

Layer 2: Appearance tags (from Type panel, persistent)
  + "fair skin, blonde hair, heavy glamorous makeup, false lashes, acrylic nails"

Layer 3: Scene prompt (from scene_meta.json)
  + "POV from above, aggressive rough deepthroat facefuck, throat bulge visible..."

Layer 4: Scene-specific implant motion
  + "stationary implants, hanging shape maintained during oral"

Layer 5: Camera instruction
  + "POV camera from above, looking down"

Layer 6: Modifiers (from chip selection)
  + "oily glistening skin, mascara running from tears, direct eye contact"

Layer 7: Gaze / Hair / Environment / Lighting
  + "looking up at camera, hair gripped in fist, studio setting, ring light"

Layer 8: Quality / Style
  + "photorealistic 8k uhd, cinematic, sharp focus, pore detail, skin texture,
     natural skin imperfections, subsurface scattering, f/1.4 shallow depth of field"

Layer 9: Skin shine (from slider)
  + "oily glistening skin, highlights on curves, shiny taut skin over implants"

Layer 10: Color temperature
  + "warm amber tones, golden lighting"

Layer 11: Film grain (if enabled)
  + "subtle film grain, 35mm film texture"
```

**Negative prompt construction (also layered):**
```
Base negatives (always):
  "cartoon, anime, 3d render, cgi, painting, illustration, blurry, low quality,
   pixelated, watermark, text, logo, morphing artifacts, flickering,
   natural breasts, saggy, droopy, soft breasts, pendulous, teardrop shape,
   natural bounce, average body, normal weight, thick, curvy, voluptuous,
   healthy weight, medium build, deformed fingers, extra fingers, missing fingers,
   mutated hands, fused fingers, three hands, extra hands, extra person,
   duplicate woman, multiple women, extra limbs, stretching body, elongated limbs,
   rubber limbs, distorted proportions, floating, hovering, gap between bodies,
   changing appearance, inconsistent details, morphing accessories"

Scene-specific negatives (from scene_meta.json):
  + "closed mouth, teeth visible, tongue wrong direction, no throat contact"

Implant-specific negatives:
  + "independent jiggling, soft bouncing, deflating breasts, flattening chest,
     breast shape change, implant deformation"
```

---

## Feature Specifications (71 features, organized by system)

### System 1: Core Generation Flow

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 1 | Image upload (drag-and-drop) | Simple | `gr.Image(type="filepath", sources=["upload","clipboard"])` |
| 2 | Scene dropdown (10 scenes) | Simple | `gr.Dropdown` loading from `SCENE_PRESETS` keys |
| 3 | Generate button | Simple | Calls `apply_settings_and_generate()` |
| 4 | Video result display | Simple | `gr.Video(autoplay=True, loop=True)` |
| 5 | Cancel button | Simple | Calls abort mechanism, visible only during generation |

### System 2: Subject & Character Control

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 6 | Persistent Type panel | Standard | `gr.Column` with dropdowns, saved to `type_settings.json` |
| 7 | Body emphasis slider | Full | Maps to `Huge_Breasts_Large_Breasts_HN` weight (0.4-1.3) |
| 8 | Face lock toggle + strength | Standard | Adds/removes `Consistent_Face` LoRA, weight slider 0.3-1.0 |
| 9 | Image Fidelity <-> Motion Freedom | Standard | Maps to `denoising_strength` (0.2-0.8) |
| 10 | Shine/oil slider | Full | 4-level slider appending shine prompt fragments |
| 11 | Aesthetic preset | Full | Radio: Pornstar glam / Natural / Instagram / Custom |
| 12 | Tattoo control | Full | Dropdown: Match reference / No tattoos / Add tattoos |
| 13 | Character profiles (save/load) | Standard | JSON files in `characters/` dir |
| 14 | Multi-reference images per character | Full | Uses Wan2GP's `image_refs` parameter |

### System 3: Scene & Action Control

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 15 | Camera angle selector | Standard | Radio: POV above / Side / Below / Static wide / Slow pan |
| 16 | Intensity (Gentle/Rough/Extreme) | Standard | Multiplier on LoRA weights: 0.7x / 1.0x / 1.3x |
| 17 | Tempo (Slow/Building/Aggressive) | Full | Adjusts `flow_shift` + motion prompt wording |
| 18 | Duration (scene-optimized) | Standard | `gr.Slider` with scene-specific default + tooltip |
| 19 | Environment picker | Full | Dropdown: Studio / Bedroom / Bathroom / Hotel / Dark / None |
| 20 | Lighting style | Full | Radio: Studio / Dramatic / Ring light / Natural / Low-key |
| 21 | Gaze direction | Full | Radio: Camera / Up / Closed / Rolling / Away |
| 22 | Hair state | Full | Dropdown: Loose / Ponytail / Gripped / Messy |
| 23 | Quick modifier chips | Standard | `gr.CheckboxGroup` for oily, sweaty, saliva, mascara, etc. |
| 24 | Color temperature | Full | Radio: Warm / Neutral / Cool |
| 25 | Background blur / DoF | Full | Slider mapping to DoF prompt fragment |
| 26 | POV / male visibility | Full | Radio: POV hands / POV minimal / Third person |
| 27 | Scene blending | Full | Two scene dropdowns + blend ratio slider |
| 28 | Custom scene creation | Full | Save current settings as new scene preset |

### System 4: Quality & Technical

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 29 | Quality preset (Draft/Standard/High) | Standard | Maps to `num_inference_steps`: 4/8/12 |
| 30 | Aspect ratio | Standard | Radio: Landscape 848x480 / Portrait 480x848 / Square 640x640 |
| 31 | VRAM monitor bar | Standard | Background thread polling `torch.cuda.memory_allocated()` |
| 32 | Generation time estimate | Standard | Pre-computed from: resolution * steps * frames / benchmark |
| 33 | Audio generation toggle | Full | Enables MMAudio post-generation with scene-aware prompts |
| 34 | Film grain toggle + intensity | Full | Uses Wan2GP's `film_grain_intensity` param |
| 35 | Auto-resolution based on VRAM | Full | Suggests max resolution given current LoRA count + model |
| 36 | GPU temperature display | Standard | Polls `nvidia-smi` or `pynvml` |

### System 5: Iteration Workflow

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 37 | Seed display | Standard | `gr.Number` showing current seed after generation |
| 38 | Lock seed toggle | Standard | Checkbox, reuses seed on next generation |
| 39 | Seed variations (+-1, +-2) | Standard | Button generating 3 adjacent seed videos |
| 40 | Seed range scan | Full | Batch generate seeds N to N+10 at draft quality |
| 41 | Star / favorite | Standard | Button copying to `outputs/favorites/`, updates metadata |
| 42 | Redo (new seed) | Standard | Button: same settings, random new seed |
| 43 | Redo (higher quality) | Standard | Button: same seed, bumps to 8+ steps |
| 44 | Continue video | Standard | Button: takes last frame, extends by duration |
| 45 | Same woman different scene | Standard | Button: keeps image + type, opens scene picker |
| 46 | Session history strip | Standard | Horizontal scrollable `gr.Gallery` of session videos |
| 47 | Reference vs result comparison | Standard | Side-by-side: pinned reference image + playing video |
| 48 | "What changed" diff | Standard | `gr.Markdown` showing settings changed since last gen |
| 49 | Batch scene sweep ("Try All") | Standard | Generates all 10 scenes at draft, returns grid |
| 50 | Continuation depth tracking | Standard | Counter + auto-boost face LoRA per depth |
| 51 | Mess escalation on continuation | Full | Auto-appends progressive mess descriptors per depth |
| 52 | Quick Compare grid (2x2) | Full | 4 variations across 2 dimensions, pick best |
| 53 | Reroll queue ("Generate until N good") | Full | Loop: generate -> thumbs up/down -> repeat until target |
| 54 | Settings snapshot per generation | Standard | Full config saved to sidecar JSON per output |

### System 6: Post-Processing Pipeline

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 55 | One-click upscale (2x Real-ESRGAN) | Standard | Post-process: 848x480 -> 1696x960 |
| 56 | Frame interpolation (RIFE 2x) | Full | Post-process: 25fps -> 50fps |
| 57 | Auto-trim warm-up frames | Standard | Trim first 0.5s of settling frames |
| 58 | Smooth start (fade from reference) | Full | Cross-dissolve from still to motion over first 0.5s |
| 59 | Video stabilization | Full | Lightweight de-jitter post-process |
| 60 | Export format presets | Standard | Dropdown: Original / Share-ready / Phone / GIF / Frames |

### System 7: Production Features

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 61 | Storyboard / sequence mode | Full | Define sequence of scenes, generate all, auto-stitch |
| 62 | "She morphed" face drift detector | Standard | Perceptual hash compare first vs last frame |
| 63 | Generation metadata embedding | Standard | Sidecar JSON + optional MP4 metadata |
| 64 | Video-to-reference extraction | Standard | Click any frame in scrubber -> becomes new reference |
| 65 | Timeline choreography | Full | Per-second prompt editor for longer videos |
| 66 | Inpainting fix for sections | Full | Mark bad frame range, mask, regenerate those frames |

### System 8: Infrastructure & UX

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 67 | Progressive disclosure (3 modes) | All | Toggle button in header: Simple/Standard/Full |
| 68 | Friendly error messages | All | Intercept Python errors, show human-readable solutions |
| 69 | Model pre-loading | All | "Warm Up" button + auto-warm on tab open option |
| 70 | Keyboard shortcuts | All | JS event listeners: Enter=gen, Esc=cancel, S=star, R=redo |
| 71 | Tooltips on every control | All | Plain-language `info=` on every Gradio component |
| 72 | Per-control reset to default | All | Right-click context or small reset icon per control |
| 73 | Scene preview thumbnails | All | Small example images in scene dropdown |
| 74 | Smart scene suggestions | Standard | Badge on 2-3 scenes best matching uploaded image |
| 75 | Reference image quality gate | Standard | Warn on low-res, watermark, blur, no face detected |
| 76 | Background removal toggle | Full | Uses Wan2GP's `remove_background_images_ref` param |
| 77 | Graceful OOM fallback | All | Auto-retry at lower resolution on CUDA OOM |
| 78 | Disk space monitoring | Standard | Show output folder size in status bar |
| 79 | Settings diagnostic ("Why?") | Full | Heuristic analysis of settings that produced bad result |
| 80 | Generation performance breakdown | Full | Time breakdown: model load, LoRA load, inference, post |
| 81 | Adaptive learning from favorites | Full | Suggest settings based on starred video statistics |
| 82 | "What am I generating?" preview | Standard | Text summary of full config before clicking Generate |
| 83 | Discovery mode vs Production mode | Full | Toggle: Discovery (fast/batch) vs Production (quality) |

### Implant-Specific Systems

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 84 | Scene-specific implant motion prompts | All | Auto-appended per scene from scene_meta.json |
| 85 | Implant size control slider | Full | Adjusts both LoRA weight and prompt descriptors |
| 86 | Skinny body reinforcement | All | Aggressive base prompt + negatives for body normalization |

### Video Playback

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 87 | Loop playback (default on) | All | `gr.Video(loop=True)` |
| 88 | Slow-motion playback (0.5x) | Standard | JS playback rate control |
| 89 | Frame scrubber | Standard | Slider for frame-by-frame navigation |
| 90 | First/last frame comparison | Full | Quick button showing first and last frame side by side |

### Content-Specific Mitigations

| # | Feature | Mode | Implementation |
|---|---------|------|----------------|
| 91 | Hand/mouth artifact negatives | All | Always-on scene-aware hand and mouth negatives |
| 92 | "Floaty bodies" prevention | All | Always-on physical contact prompt reinforcement |
| 93 | "Rubber band" stretch prevention | All | Always-on negative for body stretching |
| 94 | "Second person" prevention | All | Always-on negative for extra people/limbs |
| 95 | Temporal consistency enforcement | All | Negatives for changing appearance mid-video |

---

## Plugin API Usage

### Components Requested
```python
self.request_component("state")              # Generation state dict
self.request_component("main_tabs")          # Tab container for switching
self.request_component("refresh_form_trigger")  # Triggers form refresh
```

### Globals Requested
```python
self.request_global("get_current_model_settings")  # Read/write gen settings
self.request_global("get_lora_dir")                # LoRA directory path
self.request_global("refresh_lora_list")           # Refresh LoRA dropdown
self.request_global("server_config")               # Server configuration
self.request_global("get_model_def")               # Current model definition
self.request_global("args")                        # CLI arguments
```

### Generation Flow

The plugin does NOT implement its own generation pipeline. Instead, it:

1. Constructs all settings (prompt, LoRAs, weights, resolution, etc.)
2. Writes them into the `state` dict via `get_current_model_settings(state)`
3. Sets `image_start` in the state
4. Triggers the Video Generator tab's generation pipeline
5. Monitors for completion via output trigger
6. Retrieves the generated video from the output path

This ensures compatibility with all Wan2GP features (GGUF quantization, attention modes,
compile options, etc.) without reimplementing any of them.

For v2 features that need deeper integration (continuation, inpainting, batch):
- Continuation: Set `video_source` in state, switch to continuation mode
- Inpainting: Set `image_mask` and `masking_strength` in state
- Batch: Queue multiple generation requests via Wan2GP's queue system

---

## File Structure

```
plugins/wan2gp-nsfw-quickgen/
    __init__.py
    plugin.py                    # Main plugin (rewrite)
    scene_meta.json              # Extended scene metadata
    type_defaults.json           # Default type panel settings
    characters/                  # Character profiles
        char_example.json
    thumbs/                      # Scene preview thumbnails (optional)
    analytics.json               # Adaptive learning data (auto-created)
    SPEC.md                      # This document
```

---

## Implementation Priority

### Phase 1: Core (MVP)
- Features 1-5, 9, 16, 18, 23, 29-30, 37-38, 41-43, 45-47, 67-68, 71
- Estimated: ~600 lines of Python + JSON configs
- Deliverable: Fully functional Quick Gen with scene presets, fidelity slider,
  intensity control, seed management, and session history

### Phase 2: Character & Polish
- Features 6-8, 10-13, 15, 17, 19-22, 24-26, 28, 31-36, 39-40, 44, 48-54, 69-70, 72-78, 84-95
- Estimated: ~1200 additional lines
- Deliverable: Full Standard + Full mode, character system, all monitoring,
  all mitigations, all playback controls

### Phase 3: Production Pipeline
- Features 14, 27, 55-66, 79-83, 85-86
- Estimated: ~800 additional lines + external dependencies (Real-ESRGAN, RIFE)
- Deliverable: Post-processing, storyboard, inpainting, adaptive learning,
  advanced generation modes

---

## Technical Notes

- All persistent data (characters, analytics, type settings) stored in plugin directory
- Generation metadata stored as sidecar JSON next to output videos
- VRAM monitoring uses `torch.cuda.memory_allocated()` and `pynvml` for temperature
- Time estimates pre-computed from a benchmark run on first generation
- Progressive disclosure implemented via `gr.Column(visible=mode >= threshold)`
- Keyboard shortcuts injected via `add_custom_js()`
- Session history maintained as a list in the Gradio `state` dict
- Type panel persistence: save to JSON on every change, load on plugin init
