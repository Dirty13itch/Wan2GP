import os
import json
import time
import random
import datetime
import hashlib
import shutil
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import gradio as gr
from shared.utils.plugins import WAN2GPPlugin

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

try:
    import pynvml
    pynvml.nvmlInit()
    HAS_PYNVML = True
except Exception:
    HAS_PYNVML = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PlugIn_Name = "Quick Gen"
PlugIn_Id = "QuickGen"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PRESETS_DIR = os.path.join(PLUGIN_DIR, "..", "..", "profiles", "wan_2_2")
LORA_DIR = os.path.join(PLUGIN_DIR, "..", "..", "loras", "wan")
OUTPUT_DIR = os.path.join(PLUGIN_DIR, "..", "..", "outputs")
FAVORITES_DIR = os.path.join(OUTPUT_DIR, "favorites")
CHARACTERS_DIR = os.path.join(PLUGIN_DIR, "characters")
ANALYTICS_PATH = os.path.join(PLUGIN_DIR, "analytics.json")
TYPE_SETTINGS_PATH = os.path.join(PLUGIN_DIR, "user_type_settings.json")

EXPECTED_MODEL_TYPE = "nsfw_i2v_rapid"
EXPECTED_MODEL_NAME = "NSFW I2V Rapid AIO (GGUF Q3_K)"

SCENE_PRESETS = {
    "Deepthroat / Facefuck": "Deepthroat Facefuck - 4 Steps.json",
    "Gagging / Choking": "Gagging Choking - 4 Steps.json",
    "POV Oral": "POV Oral - 4 Steps.json",
    "Rough Doggy Style": "Rough Sex Doggy - 4 Steps.json",
    "Rough Cowgirl": "Rough Sex Cowgirl - 4 Steps.json",
    "Missionary POV": "Rough Sex Missionary POV - 4 Steps.json",
    "Choking / Manhandling": "Choking Manhandling - 4 Steps.json",
    "Standing / Hair Pull": "Standing Fuck Hair Pull - 4 Steps.json",
    "Titfuck / Paizuri": "Titfuck Paizuri - 4 Steps.json",
    "Body Showcase (Camera Sweep)": "Body Showcase Sweep - 4 Steps.json",
    "Full Nelson": "Full Nelson - 4 Steps.json",
    "Breast Insertion / Titfuck": "Breast Insertion Titfuck - 4 Steps.json",
    "Rough Doggy (Slider LoRA)": "Rough Doggy Slider - 4 Steps.json",
}

# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _save_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def _load_scene_meta() -> dict:
    return _load_json(os.path.join(PLUGIN_DIR, "scene_meta.json")) or {}

def _load_type_defaults() -> dict:
    return _load_json(os.path.join(PLUGIN_DIR, "type_defaults.json")) or {}

def _load_preset(scene_name: str) -> Optional[dict]:
    """Load and validate a scene preset JSON. Returns None on any error."""
    filename = SCENE_PRESETS.get(scene_name)
    if not filename:
        return None
    path = os.path.join(PRESETS_DIR, filename)
    data = _load_json(path)
    if not data:
        return None
    # Validate required fields
    loras = data.get("activated_loras", [])
    weights = data.get("loras_multipliers", "")
    if not isinstance(loras, list):
        print(f"[QuickGen] WARNING: preset '{filename}' has invalid activated_loras (not a list)")
        data["activated_loras"] = []
    if isinstance(weights, str):
        weight_count = len(weights.split()) if weights.strip() else 0
        lora_count = len(data.get("activated_loras", []))
        if weight_count != lora_count and lora_count > 0:
            print(f"[QuickGen] WARNING: preset '{filename}' weight/LoRA mismatch ({weight_count} weights, {lora_count} LoRAs). Padding/trimming.")
            w = weights.split() if weights.strip() else []
            while len(w) < lora_count:
                w.append("0.7")
            data["loras_multipliers"] = " ".join(w[:lora_count])
    # Validate LoRA files exist on disk
    lora_dir = os.path.normpath(os.path.join(PLUGIN_DIR, "..", "..", "loras", "wan"))
    missing = []
    for lora in data.get("activated_loras", []):
        if not os.path.exists(os.path.join(lora_dir, lora)):
            missing.append(lora)
    if missing:
        print(f"[QuickGen] WARNING: preset '{filename}' has {len(missing)} missing LoRA(s): {', '.join(missing)}")
    return data

def _load_user_type_settings() -> dict:
    data = _load_json(TYPE_SETTINGS_PATH)
    if data:
        return data
    return {
        "skin_tone": "fair",
        "hair_color": "blonde",
        "makeup_style": "pornstar_glam",
        "aesthetic": "pornstar",
    }

def _save_user_type_settings(settings: dict):
    _save_json(TYPE_SETTINGS_PATH, settings)

# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def _load_analytics() -> dict:
    data = _load_json(ANALYTICS_PATH)
    if data:
        return data
    return {"scene_stats": {}, "global_stats": {"total_generations": 0, "total_starred": 0}}

def _save_analytics(data: dict):
    _save_json(ANALYTICS_PATH, data)

def _record_generation(analytics: dict, scene: str, seed: int, starred: bool, gen_time: float):
    stats = analytics.setdefault("scene_stats", {})
    scene_stat = stats.setdefault(scene, {"total_generations": 0, "starred_count": 0, "best_seeds": []})
    scene_stat["total_generations"] += 1
    if starred:
        scene_stat["starred_count"] += 1
        seeds = scene_stat.get("best_seeds", [])
        if seed not in seeds:
            seeds.append(seed)
            scene_stat["best_seeds"] = seeds[-20:]
    scene_stat["avg_generation_time"] = gen_time
    g = analytics.setdefault("global_stats", {"total_generations": 0, "total_starred": 0})
    g["total_generations"] += 1
    if starred:
        g["total_starred"] += 1
    _save_analytics(analytics)

# ---------------------------------------------------------------------------
# Character system
# ---------------------------------------------------------------------------

def _list_characters() -> List[str]:
    os.makedirs(CHARACTERS_DIR, exist_ok=True)
    chars = []
    for f in sorted(os.listdir(CHARACTERS_DIR)):
        if f.endswith(".json"):
            chars.append(f.replace(".json", ""))
    return chars

def _load_character(name: str) -> Optional[dict]:
    return _load_json(os.path.join(CHARACTERS_DIR, f"{name}.json"))

def _save_character(name: str, data: dict):
    _save_json(os.path.join(CHARACTERS_DIR, f"{name}.json"), data)

def _delete_character(name: str):
    path = os.path.join(CHARACTERS_DIR, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)

# ---------------------------------------------------------------------------
# Generation metadata
# ---------------------------------------------------------------------------

def _save_generation_meta(video_path: str, meta: dict):
    if not video_path:
        return
    meta_path = video_path.rsplit(".", 1)[0] + "_meta.json"
    _save_json(meta_path, meta)

# ---------------------------------------------------------------------------
# GPU monitoring
# ---------------------------------------------------------------------------

def _get_vram_info() -> Tuple[float, float]:
    if HAS_TORCH and torch.cuda.is_available():
        try:
            alloc = torch.cuda.memory_allocated() / (1024**3)
            total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            return round(alloc, 1), round(total, 1)
        except Exception:
            pass
    return 0.0, 0.0

def _get_gpu_temp() -> int:
    if HAS_PYNVML:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            return pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        except Exception:
            pass
    return -1

def _get_disk_usage_mb() -> float:
    if not os.path.exists(OUTPUT_DIR):
        return 0.0
    total = 0
    for root, _dirs, files in os.walk(OUTPUT_DIR):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return round(total / (1024 * 1024), 1)

def _format_status_bar() -> str:
    vram_used, vram_total = _get_vram_info()
    temp = _get_gpu_temp()
    disk = _get_disk_usage_mb()
    parts = []
    if vram_total > 0:
        pct = int(vram_used / vram_total * 100)
        color = "#4ade80" if pct < 75 else ("#facc15" if pct < 90 else "#ef4444")
        parts.append(f'<span style="color:{color}">VRAM: {vram_used}/{vram_total}GB ({pct}%)</span>')
    if temp > 0:
        color = "#4ade80" if temp < 80 else ("#facc15" if temp < 87 else "#ef4444")
        parts.append(f'<span style="color:{color}">GPU: {temp}\u00b0C</span>')
    if disk > 0:
        parts.append(f"Outputs: {disk}MB")
    return " \u2502 ".join(parts) if parts else "GPU info unavailable"

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_prompt(
    scene_name: str,
    scene_meta: dict,
    type_defaults: dict,
    user_type: dict,
    modifiers: List[str],
    camera: str,
    gaze: str,
    hair_state: str,
    environment: str,
    lighting: str,
    color_temp: str,
    shine: str,
    male_vis: str,
    intensity: str,
    continuation_depth: int = 0,
) -> Tuple[str, str]:
    """Build the full positive and negative prompt from all layers.

    Defensive: all dict accesses use .get() with fallbacks.
    If scene_meta or type_defaults are None/empty, returns minimal prompt.
    """
    if not scene_meta:
        scene_meta = {}
    if not type_defaults:
        type_defaults = {}
    if not user_type:
        user_type = {}
    if not modifiers:
        modifiers = []
    meta = scene_meta.get(scene_name, {})
    parts = []

    # Layer 1: Base body
    parts.append(type_defaults.get("body_prompt", ""))

    # Layer 2: Appearance
    skin = type_defaults.get("skin_tone", {}).get(user_type.get("skin_tone", "fair"), "")
    hair = type_defaults.get("hair_color", {}).get(user_type.get("hair_color", "blonde"), "")
    makeup = type_defaults.get("makeup_style", {}).get(user_type.get("makeup_style", "pornstar_glam"), "")
    aesthetic = type_defaults.get("aesthetic_presets", {}).get(user_type.get("aesthetic", "pornstar"), "")
    for frag in [skin, hair, makeup, aesthetic]:
        if frag:
            parts.append(frag)

    # Layer 3: Scene prompt
    scene_prompt = meta.get("prompt", "")
    if scene_prompt:
        parts.append(scene_prompt)

    # Layer 4: Implant motion
    impl = meta.get("implant_motion", "")
    if impl:
        parts.append(impl)

    # Layer 5: Camera
    cam_prompt = type_defaults.get("camera_prompts", {}).get(camera, "")
    if cam_prompt:
        parts.append(cam_prompt)

    # Layer 6: Modifiers
    chip_defs = type_defaults.get("modifier_chips", {})
    for mod_key in modifiers:
        chip = chip_defs.get(mod_key, {})
        if chip.get("prompt"):
            parts.append(chip["prompt"])

    # Layer 7: Gaze
    gaze_prompt = type_defaults.get("gaze_prompts", {}).get(gaze, "")
    if gaze_prompt:
        parts.append(gaze_prompt)

    # Layer 7b: Hair
    hair_prompt = type_defaults.get("hair_state_prompts", {}).get(hair_state, "")
    if hair_prompt:
        parts.append(hair_prompt)

    # Layer 7c: Environment
    env_prompt = type_defaults.get("environment_prompts", {}).get(environment, "")
    if env_prompt:
        parts.append(env_prompt)

    # Layer 7d: Lighting
    light_prompt = type_defaults.get("lighting_prompts", {}).get(lighting, "")
    if light_prompt:
        parts.append(light_prompt)

    # Layer 8: Quality
    parts.append(type_defaults.get("quality_prompt", ""))

    # Layer 9: Shine
    shine_prompt = type_defaults.get("shine_prompts", {}).get(shine, "")
    if shine_prompt:
        parts.append(shine_prompt)

    # Layer 10: Color temp
    ct_prompt = type_defaults.get("color_temp_prompts", {}).get(color_temp, "")
    if ct_prompt:
        parts.append(ct_prompt)

    # Layer 11: Physical contact (for action scenes)
    cat = meta.get("scene_category", "")
    if cat in ("oral", "sex", "rough", "breast"):
        parts.append(type_defaults.get("physical_contact_prompt", ""))

    # Layer 12: Male visibility
    mv_prompt = type_defaults.get("male_visibility_prompts", {}).get(male_vis, "")
    if mv_prompt and meta.get("male_default", "none") != "none":
        parts.append(mv_prompt)

    # Layer 13: Mess escalation for continuations
    if continuation_depth > 0:
        esc = type_defaults.get("mess_escalation", [])
        idx = min(continuation_depth, len(esc) - 1)
        if idx >= 0 and idx < len(esc):
            parts.append(esc[idx])

    positive = ", ".join(p for p in parts if p.strip())

    # --- Negative prompt ---
    neg_parts = [type_defaults.get("base_negative", "")]
    neg_parts.append(type_defaults.get("body_negative", ""))
    scene_neg = meta.get("negative_extra", "")
    if scene_neg:
        neg_parts.append(scene_neg)
    impl_neg = meta.get("implant_motion_negative", "")
    if impl_neg:
        neg_parts.append(impl_neg)

    negative = ", ".join(n for n in neg_parts if n.strip())

    return positive, negative


# ---------------------------------------------------------------------------
# Estimate generation time (rough heuristic for RTX 3060)
# ---------------------------------------------------------------------------

def _estimate_time(steps: int, frames: int, width: int, height: int) -> str:
    """Rough estimate for RTX 3060 12GB with GGUF Q3_K model.
    Calibrated from real measurement: 4 steps, 81 frames, 480x848 = 341s (5m41s).
    First run adds ~60s for model/LoRA loading (not included here).
    """
    pixels = width * height
    # 341s / 4 steps = 85.25s per step at 81 frames, 480x848
    base_per_step = 85.0
    frame_scale = frames / 81.0
    pixel_scale = pixels / (480 * 848)
    seconds = steps * base_per_step * frame_scale * pixel_scale
    # Add ~30s overhead for LoRA loading on first gen, VAE decode
    seconds += 30
    if seconds < 60:
        return f"~{int(seconds)}s"
    return f"~{int(seconds // 60)}m {int(seconds % 60)}s"


# ---------------------------------------------------------------------------
# LoRA weight scaling by intensity
# ---------------------------------------------------------------------------

def _scale_lora_weights(weights_str: str, multiplier: float, cap: float = 1.5) -> str:
    weights = weights_str.split()
    scaled = []
    for w in weights:
        try:
            val = float(w) * multiplier
            val = min(val, cap)
            scaled.append(f"{val:.2f}")
        except ValueError:
            scaled.append(w)
    return " ".join(scaled)


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_summary(
    scene: str, aspect: str, quality: str, steps: int, frames: int,
    width: int, height: int, num_loras: int, fidelity: float,
    intensity: str, seed: Optional[int], modifiers: List[str],
) -> str:
    est = _estimate_time(steps, frames, width, height)
    vram_used, vram_total = _get_vram_info()
    lines = [
        f"**Scene:** {scene}",
        f"**Resolution:** {width}x{height} ({aspect})",
        f"**Quality:** {quality} ({steps} steps, {frames} frames)",
        f"**Fidelity:** {fidelity:.2f} | **Intensity:** {intensity}",
        f"**LoRAs:** {num_loras} loaded",
        f"**Seed:** {seed if seed else 'random'}",
    ]
    if modifiers:
        lines.append(f"**Modifiers:** {', '.join(modifiers)}")
    lines.append(f"**Est. time:** {est}")
    if vram_total > 0:
        lines.append(f"**VRAM:** {vram_used}/{vram_total}GB")
    return "\n".join(lines)


def _model_check_html() -> str:
    """Check if the GGUF model file exists and return appropriate HTML banner."""
    gguf_path = os.path.join(PLUGIN_DIR, "..", "..", "ckpts", "wan2.2-i2v-rapid-aio-v10-nsfw-Q3_K.gguf")
    if os.path.exists(gguf_path):
        return (
            '<div style="padding:8px 12px;background:#1a3a1a;border:1px solid #2d5a2d;border-radius:6px;margin:4px 0;font-size:0.85em">'
            '<b style="color:#4ade80">Model ready.</b> '
            f'Select <b>"{EXPECTED_MODEL_NAME}"</b> from the Video Generator tab\'s model dropdown, then return here to generate.'
            '</div>'
        )
    return (
        '<div style="padding:8px 12px;background:#3a1a1a;border:1px solid #5a2d2d;border-radius:6px;margin:4px 0;font-size:0.85em">'
        '<b style="color:#ef4444">GGUF model not found!</b> '
        'Download <code>wan2.2-i2v-rapid-aio-v10-nsfw-Q3_K.gguf</code> to the <code>ckpts/</code> folder.'
        '</div>'
    )


def _check_model_type(state: dict) -> str:
    """Check if the currently loaded model is the expected WAN 2.2 I2V model. Returns error string or empty."""
    model_type = state.get("model_type", "")
    if not model_type:
        return f"No model selected. Go to Video Generator tab and select '{EXPECTED_MODEL_NAME}' from the model dropdown."
    # Accept any wan i2v model (the finetune or the stock one)
    if "i2v" in model_type.lower() and ("wan" in model_type.lower() or "2_2" in model_type or "nsfw" in model_type.lower()):
        return ""
    # Check for exact finetune match
    if model_type == EXPECTED_MODEL_TYPE:
        return ""
    return (
        f"Wrong model loaded: '{model_type}'. "
        f"Quick Gen needs a WAN 2.2 I2V model. "
        f"Go to Video Generator tab and select '{EXPECTED_MODEL_NAME}' from the dropdown."
    )


# ===========================================================================
# PLUGIN CLASS
# ===========================================================================

class QuickGenPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = PlugIn_Name
        self.version = "2.0.0"
        self.description = "All-in-one NSFW I2V: upload image, pick scene, generate. 95 features across Simple/Standard/Full modes."
        self.uninstallable = True
        self._scene_meta = _load_scene_meta()
        self._type_defaults = _load_type_defaults()
        self._user_type = _load_user_type_settings()
        self._analytics = _load_analytics()
        self._session_videos: List[dict] = []
        self._last_settings: dict = {}
        self._last_seed: Optional[int] = None
        self._continuation_depth: int = 0

    # -------------------------------------------------------------------
    # Plugin API
    # -------------------------------------------------------------------
    def setup_ui(self):
        self.request_global("get_current_model_settings")
        self.request_global("server_config")
        self.request_global("args")
        self.request_component("refresh_form_trigger")
        self.request_component("state")
        self.request_component("main_tabs")

        self.add_tab(
            tab_id=PlugIn_Id,
            label=PlugIn_Name,
            component_constructor=self.create_ui,
            position=0,
        )

        self.add_custom_js(KEYBOARD_SHORTCUTS_JS)

    def on_tab_select(self, state: dict):
        return []

    def on_tab_deselect(self, state: dict):
        pass

    # -------------------------------------------------------------------
    # UI Construction
    # -------------------------------------------------------------------
    def create_ui(self):
        state = self.state
        scene_meta = self._scene_meta
        type_defaults = self._type_defaults

        scene_names = list(SCENE_PRESETS.keys())
        modifier_keys = list(type_defaults.get("modifier_chips", {}).keys())
        modifier_labels = [k.replace("_", " ").title() for k in modifier_keys]
        camera_choices = list(type_defaults.get("camera_prompts", {}).keys())
        gaze_choices = list(type_defaults.get("gaze_prompts", {}).keys())
        hair_choices = list(type_defaults.get("hair_state_prompts", {}).keys())
        env_choices = list(type_defaults.get("environment_prompts", {}).keys())
        light_choices = list(type_defaults.get("lighting_prompts", {}).keys())
        color_choices = list(type_defaults.get("color_temp_prompts", {}).keys())
        shine_choices = list(type_defaults.get("shine_prompts", {}).keys())
        male_choices = list(type_defaults.get("male_visibility_prompts", {}).keys())
        aspect_choices = list(type_defaults.get("aspect_ratios", {}).keys())
        quality_choices = list(type_defaults.get("quality_presets", {}).keys())
        skin_choices = list(type_defaults.get("skin_tone", {}).keys())
        hair_color_choices = list(type_defaults.get("hair_color", {}).keys())
        makeup_choices = list(type_defaults.get("makeup_style", {}).keys())
        aesthetic_choices = list(type_defaults.get("aesthetic_presets", {}).keys())
        character_names = _list_characters()

        # --- Internal state ---
        ui_mode = gr.State("standard")  # simple / standard / full
        session_list = gr.State([])
        current_seed = gr.State(None)
        lock_seed = gr.State(False)
        continuation_depth = gr.State(0)
        last_settings_diff = gr.State("")
        last_gen_meta = gr.State({})

        with gr.Column():
            # ============================================================
            # HEADER
            # ============================================================
            with gr.Row(equal_height=True):
                with gr.Column(scale=3):
                    gr.HTML("""
                    <div style="padding:4px 0">
                        <h2 style="margin:0;font-size:1.5em">Quick Gen <span style="font-size:0.5em;opacity:0.5">v2.0</span></h2>
                        <p style="margin:2px 0 0;opacity:0.6;font-size:0.9em">Upload \u2192 Pick scene \u2192 Generate</p>
                    </div>""")
                with gr.Column(scale=1, min_width=200):
                    mode_radio = gr.Radio(
                        choices=["simple", "standard", "full"],
                        value="standard",
                        label="Mode",
                        info="Controls how many options are visible",
                        interactive=True,
                    )

            # Model check banner
            model_warning = gr.HTML(value=_model_check_html(), visible=True)

            # Status bar
            status_html = gr.HTML(value=f'<div style="font-size:0.8em;opacity:0.7;padding:4px 8px;background:var(--block-background-fill);border-radius:6px">{_format_status_bar()}</div>')

            # ============================================================
            # MAIN LAYOUT
            # ============================================================
            with gr.Row():
                # ---- LEFT COLUMN: Image ----
                with gr.Column(scale=2):
                    image_input = gr.Image(
                        label="Reference Image",
                        type="filepath",
                        sources=["upload", "clipboard"],
                        height=350,
                    )
                    image_hint = gr.Markdown(value="", visible=True)

                    # Auto-crop (standard+)
                    with gr.Row(visible=True) as crop_row:
                        crop_mode = gr.Radio(
                            choices=["Full image", "Face + upper body", "Torso focus"],
                            value="Full image",
                            label="Image framing",
                            info="How to frame the reference for this scene",
                        )

                    # Recent images strip (standard+)
                    recent_images = gr.Gallery(
                        label="Recent",
                        columns=6,
                        height=80,
                        object_fit="cover",
                        visible=True,
                        allow_preview=False,
                    )

                    # Character panel (standard+)
                    with gr.Accordion("Character Profiles", open=False, visible=True) as char_accordion:
                        with gr.Row():
                            char_dropdown = gr.Dropdown(
                                choices=["(None)"] + character_names,
                                value="(None)",
                                label="Load Character",
                                scale=2,
                            )
                            char_save_btn = gr.Button("Save as Character", size="sm", scale=1)
                        char_name_input = gr.Textbox(label="Character name", visible=False, placeholder="Enter name...")
                        char_save_confirm = gr.Button("Confirm Save", visible=False, size="sm")

                # ---- RIGHT COLUMN: Controls ----
                with gr.Column(scale=3):
                    # Scene dropdown
                    scene_dropdown = gr.Dropdown(
                        choices=scene_names,
                        value=scene_names[0],
                        label="Scene Type",
                        info="Each scene auto-loads the right LoRAs, prompt, and settings",
                    )

                    # Type panel (standard+)
                    with gr.Accordion("Appearance / Type (persistent)", open=False, visible=True) as type_accordion:
                        with gr.Row():
                            skin_dd = gr.Dropdown(choices=skin_choices, value=self._user_type.get("skin_tone", "fair"), label="Skin Tone", scale=1)
                            hair_color_dd = gr.Dropdown(choices=hair_color_choices, value=self._user_type.get("hair_color", "blonde"), label="Hair Color", scale=1)
                        with gr.Row():
                            makeup_dd = gr.Dropdown(choices=makeup_choices, value=self._user_type.get("makeup_style", "pornstar_glam"), label="Makeup", scale=1)
                            aesthetic_dd = gr.Dropdown(choices=aesthetic_choices, value=self._user_type.get("aesthetic", "pornstar"), label="Aesthetic", scale=1)

                    # Fidelity slider (standard+)
                    fidelity_slider = gr.Slider(
                        minimum=0.15, maximum=0.85, value=0.5, step=0.05,
                        label="Image Fidelity \u2194 Motion Freedom",
                        info="Left = looks like reference (less motion). Right = more motion (may drift from reference).",
                        visible=True,
                    )

                    with gr.Row():
                        intensity_radio = gr.Radio(
                            choices=["gentle", "rough", "extreme"],
                            value="rough",
                            label="Intensity",
                            info="Scales LoRA weights: gentle=0.7x, rough=1.0x, extreme=1.3x",
                        )
                        quality_radio = gr.Radio(
                            choices=quality_choices,
                            value="draft",
                            label="Quality",
                            info="Draft=4 steps (~6min), Standard=8 (~12min), High=12 (~18min) on RTX 3060",
                        )

                    with gr.Row():
                        duration_slider = gr.Slider(
                            minimum=33, maximum=161, value=81, step=8,
                            label="Duration (frames)",
                            info="33=~1.3s, 57=~2.3s, 81=~3.2s, 105=~4.2s, 129=~5.2s, 161=~6.4s @ 25fps",
                            visible=True,
                        )
                        aspect_radio = gr.Radio(
                            choices=aspect_choices,
                            value="portrait",
                            label="Aspect Ratio",
                            visible=True,
                        )

                    # Camera (standard+)
                    camera_radio = gr.Radio(
                        choices=camera_choices,
                        value="pov_above",
                        label="Camera Angle",
                        visible=True,
                    )

                    # Modifiers (standard+)
                    modifier_check = gr.CheckboxGroup(
                        choices=modifier_keys,
                        value=[],
                        label="Quick Modifiers (multi-select)",
                        info="Each adds a visual detail to the prompt",
                        visible=True,
                    )

            # ============================================================
            # FULL MODE CONTROLS
            # ============================================================
            with gr.Accordion("Advanced Scene Controls", open=False, visible=True) as adv_scene_acc:
                with gr.Row():
                    gaze_dd = gr.Dropdown(choices=gaze_choices, value="camera", label="Gaze Direction", scale=1)
                    hair_dd = gr.Dropdown(choices=hair_choices, value="loose", label="Hair State", scale=1)
                    male_dd = gr.Dropdown(choices=male_choices, value="pov_hands", label="Male Visibility", scale=1)
                with gr.Row():
                    env_dd = gr.Dropdown(choices=env_choices, value="none", label="Environment", scale=1)
                    light_dd = gr.Dropdown(choices=light_choices, value="ring_light", label="Lighting", scale=1)
                    color_dd = gr.Dropdown(choices=color_choices, value="warm", label="Color Temp", scale=1)
                with gr.Row():
                    shine_dd = gr.Dropdown(choices=shine_choices, value="glossy", label="Skin Shine", scale=1)
                    dof_slider = gr.Slider(minimum=0, maximum=1, value=0.7, step=0.1, label="Background Blur / DoF", scale=1)
                    body_emphasis = gr.Slider(minimum=0.3, maximum=1.4, value=0.9, step=0.05, label="Implant Size Emphasis", info="Maps to Huge_Breasts LoRA weight", scale=1)
                with gr.Row():
                    face_lock = gr.Checkbox(value=True, label="Face Consistency Lock")
                    face_strength = gr.Slider(minimum=0.2, maximum=1.0, value=0.7, step=0.05, label="Face Lock Strength")
                    audio_toggle = gr.Checkbox(value=False, label="Generate Audio (MMAudio)")
                    film_grain_toggle = gr.Checkbox(value=False, label="Film Grain")

            with gr.Accordion("Prompt Override (editable)", open=False, visible=True) as prompt_acc:
                prompt_override = gr.Textbox(label="Positive Prompt (auto-filled, edit to override)", lines=4, value="")
                neg_override = gr.Textbox(label="Negative Prompt (auto-filled, edit to override)", lines=3, value="")
                prompt_enhance_toggle = gr.Checkbox(value=True, label="AI Prompt Enhancement", info="Uses AI to expand prompt into second-by-second descriptions")
                rebuild_prompt_btn = gr.Button("Rebuild from settings", size="sm")

            # ============================================================
            # GENERATE SECTION
            # ============================================================
            summary_md = gr.Markdown(value="", visible=True)

            with gr.Row():
                generate_btn = gr.Button("Generate Video", variant="primary", scale=3, size="lg")
                cancel_btn = gr.Button("Cancel", variant="stop", scale=1, visible=False)

            progress_html = gr.HTML(value="", visible=False)

            # ============================================================
            # RESULT SECTION
            # ============================================================
            with gr.Row(visible=False) as result_row:
                with gr.Column(scale=1):
                    ref_preview = gr.Image(label="Reference", height=300, interactive=False)
                with gr.Column(scale=2):
                    video_output = gr.Video(label="Generated Video", autoplay=True, loop=True, height=300)
                    with gr.Row():
                        seed_display = gr.Number(label="Seed", interactive=False, precision=0)
                        lock_seed_cb = gr.Checkbox(label="Lock Seed", value=False)

            # Keeper actions
            with gr.Row(visible=False) as keeper_row:
                star_btn = gr.Button("\u2b50 Star", size="sm")
                redo_btn = gr.Button("\U0001f3b2 Redo (new seed)", size="sm")
                redo_hq_btn = gr.Button("\u2728 Redo (higher quality)", size="sm")
                continue_btn = gr.Button("\u27a1 Continue (+2-4s)", size="sm")
                diff_scene_btn = gr.Button("\U0001f504 Same woman, diff scene", size="sm")
                variation_btn = gr.Button("\U0001f500 Seed variations (\u00b11,\u00b12)", size="sm")

            # Changes diff
            diff_md = gr.Markdown(value="", visible=False)

            # Session history
            with gr.Accordion("Session History", open=True, visible=False) as session_acc:
                session_gallery = gr.Gallery(
                    label="This session's videos",
                    columns=8,
                    height=100,
                    object_fit="cover",
                    allow_preview=True,
                )

            # ============================================================
            # EVENT HANDLERS
            # ============================================================

            # --- Scene change: update defaults ---
            def on_scene_change(scene_name):
                meta = scene_meta.get(scene_name, {})
                hint = meta.get("image_hint", "")
                defaults = {
                    "fidelity": meta.get("default_fidelity", 0.5),
                    "duration": meta.get("default_duration_frames", 81),
                    "aspect": meta.get("default_aspect", "portrait"),
                    "camera": meta.get("default_camera", "pov_above"),
                    "gaze": meta.get("default_gaze", "camera"),
                    "hair": meta.get("default_hair", "loose"),
                    "male": meta.get("male_default", "pov_hands"),
                    "tempo": meta.get("default_tempo", "building"),
                }
                return (
                    f"*{hint}*" if hint else "",
                    defaults["fidelity"],
                    defaults["duration"],
                    defaults["aspect"],
                    defaults["camera"],
                    defaults["gaze"],
                    defaults["hair"],
                    defaults["male"],
                )

            scene_dropdown.change(
                fn=on_scene_change,
                inputs=[scene_dropdown],
                outputs=[image_hint, fidelity_slider, duration_slider, aspect_radio, camera_radio, gaze_dd, hair_dd, male_dd],
            )

            # --- Type settings persistence ---
            def save_type(skin, hair_c, makeup, aes):
                s = {"skin_tone": skin, "hair_color": hair_c, "makeup_style": makeup, "aesthetic": aes}
                _save_user_type_settings(s)
                self._user_type = s
                return gr.update()

            for comp in [skin_dd, hair_color_dd, makeup_dd, aesthetic_dd]:
                comp.change(fn=save_type, inputs=[skin_dd, hair_color_dd, makeup_dd, aesthetic_dd], outputs=[status_html])

            # --- Build prompt preview ---
            def rebuild_prompt(
                scene, skin, hair_c, makeup, aes, mods, camera, gaze, hair,
                env, light, color, shine, male, intensity, cont_depth
            ):
                user_t = {"skin_tone": skin, "hair_color": hair_c, "makeup_style": makeup, "aesthetic": aes}
                pos, neg = build_prompt(
                    scene, scene_meta, type_defaults, user_t,
                    mods, camera, gaze, hair, env, light, color, shine, male, intensity, cont_depth,
                )
                return pos, neg

            rebuild_prompt_btn.click(
                fn=rebuild_prompt,
                inputs=[scene_dropdown, skin_dd, hair_color_dd, makeup_dd, aesthetic_dd,
                        modifier_check, camera_radio, gaze_dd, hair_dd,
                        env_dd, light_dd, color_dd, shine_dd, male_dd, intensity_radio, continuation_depth],
                outputs=[prompt_override, neg_override],
            )

            # --- Build summary ---
            def build_summary_fn(scene, aspect, quality, fidelity, intensity, frames, seed_val, mods, lock_s):
                ar = type_defaults.get("aspect_ratios", {}).get(aspect, {"width": 480, "height": 848})
                qp = type_defaults.get("quality_presets", {}).get(quality, {"num_inference_steps": 4})
                steps = qp["num_inference_steps"]
                preset = _load_preset(scene)
                n_loras = len(preset.get("activated_loras", [])) if preset else 0
                s = seed_val if lock_s and seed_val else None
                return _build_summary(scene, aspect, quality, steps, frames, ar["width"], ar["height"], n_loras, fidelity, intensity, s, mods)

            for trigger in [scene_dropdown, aspect_radio, quality_radio, fidelity_slider, intensity_radio, duration_slider, modifier_check]:
                trigger.change(
                    fn=build_summary_fn,
                    inputs=[scene_dropdown, aspect_radio, quality_radio, fidelity_slider, intensity_radio, duration_slider, current_seed, modifier_check, lock_seed],
                    outputs=[summary_md],
                )

            # --- Status bar refresh ---
            def refresh_status():
                return f'<div style="font-size:0.8em;opacity:0.7;padding:4px 8px;background:var(--block-background-fill);border-radius:6px">{_format_status_bar()}</div>'

            # ============================================================
            # GENERATE
            # ============================================================
            def apply_and_generate(
                state_dict, scene, fidelity, intensity, quality, duration_frames, aspect,
                camera, mods, skin, hair_c, makeup, aes, gaze, hair, env, light, color,
                shine, male, body_emp, face_lk, face_str, prompt_text, neg_text,
                enhance_on, audio_on, grain_on, dof_val, seed_val, lock_s, cont_depth, image_path,
            ):
                no_change = (time.time(), gr.Tabs(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update())

                try:
                    return _apply_and_generate_inner(
                        state_dict, scene, fidelity, intensity, quality, duration_frames, aspect,
                        camera, mods, skin, hair_c, makeup, aes, gaze, hair, env, light, color,
                        shine, male, body_emp, face_lk, face_str, prompt_text, neg_text,
                        enhance_on, audio_on, grain_on, dof_val, seed_val, lock_s, cont_depth, image_path,
                    )
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    gr.Warning(f"Generation failed: {str(e)[:200]}")
                    return no_change

            def _apply_and_generate_inner(
                state_dict, scene, fidelity, intensity, quality, duration_frames, aspect,
                camera, mods, skin, hair_c, makeup, aes, gaze, hair, env, light, color,
                shine, male, body_emp, face_lk, face_str, prompt_text, neg_text,
                enhance_on, audio_on, grain_on, dof_val, seed_val, lock_s, cont_depth, image_path,
            ):
                no_change = (time.time(), gr.Tabs(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update())

                if not image_path:
                    gr.Warning("Upload a reference image first.")
                    return no_change

                # Validate model type
                model_err = _check_model_type(state_dict)
                if model_err:
                    gr.Warning(model_err)
                    return no_change

                settings = self.get_current_model_settings(state_dict)
                if settings is None:
                    gr.Warning(f"No model settings found. Go to Video Generator tab and select '{EXPECTED_MODEL_NAME}'.")
                    return no_change

                # Load scene preset
                preset = _load_preset(scene)
                if not preset:
                    gr.Warning(f"Scene preset not found: {scene}")
                    return (time.time(), gr.Tabs(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update())

                # Apply LoRAs
                activated = list(preset.get("activated_loras", []))
                base_weights_str = preset.get("loras_multipliers", "")
                base_weights = base_weights_str.split()

                # --- lora_skip filtering ---
                skip_list = scene_meta.get(scene, {}).get("lora_skip", [])
                if skip_list:
                    filtered_loras = []
                    filtered_weights = []
                    for i, lora_name in enumerate(activated):
                        if not any(skip in lora_name for skip in skip_list):
                            filtered_loras.append(lora_name)
                            if i < len(base_weights):
                                filtered_weights.append(base_weights[i])
                    activated = filtered_loras
                    base_weights = filtered_weights

                settings["activated_loras"] = activated

                # Scale weights by intensity
                mult = type_defaults.get("intensity_multipliers", {}).get(intensity, 1.0)
                scaled = _scale_lora_weights(" ".join(base_weights), mult).split()

                # --- body_emphasis override (Huge_Breasts weight) ---
                for i, lora_name in enumerate(activated):
                    if "Huge_Breasts" in lora_name and i < len(scaled):
                        scaled[i] = f"{min(max(float(body_emp), 0.2), 1.5):.2f}"
                        break

                # --- face_strength override (Consistent_Face weight) ---
                if face_lk:
                    for i, lora_name in enumerate(activated):
                        if "Consistent_Face" in lora_name and i < len(scaled):
                            scaled[i] = f"{min(max(float(face_str), 0.1), 1.2):.2f}"
                            break

                settings["loras_multipliers"] = " ".join(scaled)

                # Quality settings
                qp = type_defaults.get("quality_presets", {}).get(quality, {})
                settings["num_inference_steps"] = qp.get("num_inference_steps", 4)
                if "guidance_phases" in qp:
                    settings["guidance_phases"] = qp["guidance_phases"]
                settings["guidance_scale"] = preset.get("guidance_scale", 1)

                # Resolution
                ar = type_defaults.get("aspect_ratios", {}).get(aspect, {"width": 480, "height": 848})
                settings["width"] = ar["width"]
                settings["height"] = ar["height"]

                # Duration
                settings["num_frames"] = int(duration_frames)

                # Fidelity (denoising strength)
                settings["denoising_strength"] = fidelity

                # Seed
                if lock_s and seed_val and seed_val > 0:
                    settings["seed"] = int(seed_val)
                else:
                    settings["seed"] = random.randint(1, 999999999)

                # Image
                settings["image_start"] = image_path

                # Prompt
                user_t = {"skin_tone": skin, "hair_color": hair_c, "makeup_style": makeup, "aesthetic": aes}
                if prompt_text.strip():
                    pos = prompt_text
                else:
                    pos, _ = build_prompt(
                        scene, scene_meta, type_defaults, user_t,
                        mods, camera, gaze, hair, env, light, color, shine, male, intensity, cont_depth,
                    )
                if neg_text.strip():
                    neg = neg_text
                else:
                    _, neg = build_prompt(
                        scene, scene_meta, type_defaults, user_t,
                        mods, camera, gaze, hair, env, light, color, shine, male, intensity, cont_depth,
                    )

                # --- DoF injection ---
                if dof_val and float(dof_val) > 0.3:
                    dof_strength = float(dof_val)
                    if dof_strength > 0.7:
                        pos += ", extremely shallow depth of field, f/1.2, strong creamy bokeh, background completely blurred"
                    elif dof_strength > 0.4:
                        pos += ", shallow depth of field, f/1.8, soft bokeh background"
                    else:
                        pos += ", slight depth of field, f/2.8, background slightly soft"

                # --- Prompt enhancement prefix ---
                if enhance_on:
                    pos = "(Enhance this prompt: describe detailed second-by-second motion choreography, physical interactions, camera movements, and realistic body physics for this scene) " + pos

                settings["prompt"] = pos
                settings["negative_prompt"] = neg

                # --- MMAudio ---
                if audio_on:
                    settings["MMAudio_setting"] = 1
                    audio_prompt = scene_meta.get(scene, {}).get("auto_audio_prompt", "")
                    if audio_prompt:
                        settings["audio_prompt"] = audio_prompt
                else:
                    settings["MMAudio_setting"] = 0

                # Film grain
                if grain_on:
                    settings["film_grain_intensity"] = 0.15
                    settings["film_grain_saturation"] = 0.3
                else:
                    settings["film_grain_intensity"] = 0
                    settings["film_grain_saturation"] = 0

                # Save last seed
                self._last_seed = settings["seed"]
                self._last_settings = {
                    "scene": scene, "fidelity": fidelity, "intensity": intensity,
                    "quality": quality, "duration": duration_frames, "aspect": aspect,
                    "camera": camera, "modifiers": mods, "seed": settings["seed"],
                }

                # Record analytics
                _record_generation(self._analytics, scene, settings["seed"], False, 0)

                # Debug: log applied settings
                print(f"[QuickGen] === Generation Settings ===")
                print(f"[QuickGen]   Scene: {scene}")
                print(f"[QuickGen]   LoRAs ({len(activated)}): {', '.join(l[:30] for l in activated)}")
                print(f"[QuickGen]   Weights: {settings['loras_multipliers']}")
                print(f"[QuickGen]   Steps: {qp.get('num_inference_steps', 4)} | Res: {ar['width']}x{ar['height']} | Frames: {duration_frames}")
                print(f"[QuickGen]   Fidelity: {fidelity} | Seed: {settings['seed']} | Audio: {audio_on} | Grain: {grain_on}")
                print(f"[QuickGen]   Prompt ({len(pos)} chars): {pos[:100]}...")
                print(f"[QuickGen]   Neg ({len(neg)} chars): {neg[:80]}...")
                print(f"[QuickGen] ==============================")

                gr.Info(f"Generating: {scene} | Seed: {settings['seed']} | {ar['width']}x{ar['height']} | {qp.get('num_inference_steps', 4)} steps")

                # Switch to Video Generator to run generation
                return (
                    time.time(),
                    gr.Tabs(selected="video_gen"),
                    settings["seed"],
                    gr.update(visible=True),
                    gr.update(visible=True),
                    gr.update(visible=True),
                    gr.update(visible=True),
                    image_path,
                )

            # JS to auto-click the native Generate button after tab switch
            AUTO_CLICK_GENERATE_JS = """
            () => {
                let attempts = 0;
                const tryClick = () => {
                    attempts++;
                    // Scope to the first tabpanel (Video Generator)
                    const panels = document.querySelectorAll('[role="tabpanel"]');
                    const videoGenPanel = panels.length > 0 ? panels[0] : document;
                    const buttons = videoGenPanel.querySelectorAll('button');
                    for (const btn of buttons) {
                        const txt = btn.textContent.trim();
                        if (txt === 'Generate' && btn.offsetParent !== null) {
                            btn.click();
                            console.log('[QuickGen] Auto-clicked Generate (attempt ' + attempts + ')');
                            return;
                        }
                    }
                    if (attempts < 4) {
                        console.log('[QuickGen] Generate button not found, retry ' + attempts + '/4...');
                        setTimeout(tryClick, 500);
                    } else {
                        console.error('[QuickGen] Generate button not found after 4 attempts');
                    }
                };
                setTimeout(tryClick, 800);
            }
            """

            generate_btn.click(
                fn=apply_and_generate,
                inputs=[
                    state, scene_dropdown, fidelity_slider, intensity_radio, quality_radio,
                    duration_slider, aspect_radio, camera_radio, modifier_check,
                    skin_dd, hair_color_dd, makeup_dd, aesthetic_dd,
                    gaze_dd, hair_dd, env_dd, light_dd, color_dd, shine_dd, male_dd,
                    body_emphasis, face_lock, face_strength,
                    prompt_override, neg_override, prompt_enhance_toggle,
                    audio_toggle, film_grain_toggle, dof_slider,
                    current_seed, lock_seed_cb, continuation_depth, image_input,
                ],
                outputs=[
                    self.refresh_form_trigger, self.main_tabs,
                    current_seed, result_row, keeper_row, session_acc, diff_md, ref_preview,
                ],
            ).then(fn=None, inputs=[], outputs=[], js=AUTO_CLICK_GENERATE_JS)

            # --- Star / Favorite ---
            def star_current(seed_val):
                os.makedirs(FAVORITES_DIR, exist_ok=True)
                gr.Info(f"Starred! Seed {int(seed_val)} saved to favorites.")
                self._analytics = _load_analytics()
                scene = self._last_settings.get("scene", "unknown")
                _record_generation(self._analytics, scene, int(seed_val), True, 0)
                return gr.update()

            star_btn.click(fn=star_current, inputs=[current_seed], outputs=[status_html])

            # --- Redo (new seed) ---
            def redo_new_seed():
                return False, None

            redo_btn.click(fn=redo_new_seed, outputs=[lock_seed_cb, current_seed]).then(
                fn=apply_and_generate,
                inputs=[
                    state, scene_dropdown, fidelity_slider, intensity_radio, quality_radio,
                    duration_slider, aspect_radio, camera_radio, modifier_check,
                    skin_dd, hair_color_dd, makeup_dd, aesthetic_dd,
                    gaze_dd, hair_dd, env_dd, light_dd, color_dd, shine_dd, male_dd,
                    body_emphasis, face_lock, face_strength,
                    prompt_override, neg_override, prompt_enhance_toggle,
                    audio_toggle, film_grain_toggle, dof_slider,
                    current_seed, lock_seed_cb, continuation_depth, image_input,
                ],
                outputs=[
                    self.refresh_form_trigger, self.main_tabs,
                    current_seed, result_row, keeper_row, session_acc, diff_md, ref_preview,
                ],
            ).then(fn=None, inputs=[], outputs=[], js=AUTO_CLICK_GENERATE_JS)

            # --- Redo (higher quality) ---
            def bump_quality(current_q):
                order = ["draft", "standard", "high"]
                idx = order.index(current_q) if current_q in order else 0
                return order[min(idx + 1, len(order) - 1)], True

            redo_hq_btn.click(fn=bump_quality, inputs=[quality_radio], outputs=[quality_radio, lock_seed_cb]).then(
                fn=apply_and_generate,
                inputs=[
                    state, scene_dropdown, fidelity_slider, intensity_radio, quality_radio,
                    duration_slider, aspect_radio, camera_radio, modifier_check,
                    skin_dd, hair_color_dd, makeup_dd, aesthetic_dd,
                    gaze_dd, hair_dd, env_dd, light_dd, color_dd, shine_dd, male_dd,
                    body_emphasis, face_lock, face_strength,
                    prompt_override, neg_override, prompt_enhance_toggle,
                    audio_toggle, film_grain_toggle, dof_slider,
                    current_seed, lock_seed_cb, continuation_depth, image_input,
                ],
                outputs=[
                    self.refresh_form_trigger, self.main_tabs,
                    current_seed, result_row, keeper_row, session_acc, diff_md, ref_preview,
                ],
            ).then(fn=None, inputs=[], outputs=[], js=AUTO_CLICK_GENERATE_JS)

            # --- Continue video ---
            def prep_continue(depth):
                return depth + 1

            continue_btn.click(fn=prep_continue, inputs=[continuation_depth], outputs=[continuation_depth]).then(
                fn=apply_and_generate,
                inputs=[
                    state, scene_dropdown, fidelity_slider, intensity_radio, quality_radio,
                    duration_slider, aspect_radio, camera_radio, modifier_check,
                    skin_dd, hair_color_dd, makeup_dd, aesthetic_dd,
                    gaze_dd, hair_dd, env_dd, light_dd, color_dd, shine_dd, male_dd,
                    body_emphasis, face_lock, face_strength,
                    prompt_override, neg_override, prompt_enhance_toggle,
                    audio_toggle, film_grain_toggle, dof_slider,
                    current_seed, lock_seed_cb, continuation_depth, image_input,
                ],
                outputs=[
                    self.refresh_form_trigger, self.main_tabs,
                    current_seed, result_row, keeper_row, session_acc, diff_md, ref_preview,
                ],
            ).then(fn=None, inputs=[], outputs=[], js=AUTO_CLICK_GENERATE_JS)

            # --- Same woman, different scene ---
            def reset_for_new_scene(depth):
                return 0

            diff_scene_btn.click(fn=reset_for_new_scene, inputs=[continuation_depth], outputs=[continuation_depth])

            # --- Character save ---
            def show_char_save():
                return gr.update(visible=True), gr.update(visible=True)

            def do_char_save(name, skin, hair_c, makeup, aes, fidelity):
                if not name.strip():
                    gr.Warning("Enter a character name")
                    return gr.update(), gr.update()
                data = {
                    "name": name.strip(),
                    "type_settings": {
                        "skin_tone": skin, "hair_color": hair_c,
                        "makeup_style": makeup, "aesthetic": aes,
                    },
                    "preferred_fidelity": fidelity,
                    "proven_seeds": [],
                    "created": datetime.datetime.now().isoformat(),
                }
                _save_character(name.strip(), data)
                gr.Info(f"Character '{name.strip()}' saved!")
                new_chars = _list_characters()
                return gr.Dropdown(choices=["(None)"] + new_chars), gr.update(visible=False), gr.update(visible=False)

            char_save_btn.click(fn=show_char_save, outputs=[char_name_input, char_save_confirm])
            char_save_confirm.click(
                fn=do_char_save,
                inputs=[char_name_input, skin_dd, hair_color_dd, makeup_dd, aesthetic_dd, fidelity_slider],
                outputs=[char_dropdown, char_name_input, char_save_confirm],
            )

            # --- Character load ---
            def load_char(char_name):
                if char_name == "(None)":
                    return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
                data = _load_character(char_name)
                if not data:
                    gr.Warning(f"Character '{char_name}' not found")
                    return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
                ts = data.get("type_settings", {})
                return (
                    ts.get("skin_tone", "fair"),
                    ts.get("hair_color", "blonde"),
                    ts.get("makeup_style", "pornstar_glam"),
                    ts.get("aesthetic", "pornstar"),
                    data.get("preferred_fidelity", 0.5),
                )

            char_dropdown.change(
                fn=load_char,
                inputs=[char_dropdown],
                outputs=[skin_dd, hair_color_dd, makeup_dd, aesthetic_dd, fidelity_slider],
            )

            # --- Mode visibility ---
            def update_visibility(mode):
                is_std = mode in ("standard", "full")
                is_full = mode == "full"
                return (
                    gr.update(visible=is_std),   # crop_row
                    gr.update(visible=is_std),   # recent_images
                    gr.update(visible=is_std),   # char_accordion
                    gr.update(visible=is_std),   # type_accordion
                    gr.update(visible=is_std),   # fidelity_slider
                    gr.update(visible=is_std),   # duration_slider
                    gr.update(visible=is_std),   # aspect_radio
                    gr.update(visible=is_std),   # camera_radio
                    gr.update(visible=is_std),   # modifier_check
                    gr.update(visible=is_full),  # adv_scene_acc
                    gr.update(visible=is_full),  # prompt_acc
                    gr.update(visible=is_std),   # summary_md
                )

            mode_radio.change(
                fn=update_visibility,
                inputs=[mode_radio],
                outputs=[
                    crop_row, recent_images, char_accordion, type_accordion,
                    fidelity_slider, duration_slider, aspect_radio, camera_radio,
                    modifier_check, adv_scene_acc, prompt_acc, summary_md,
                ],
            )

        # Store references
        self.on_tab_outputs = []


# ---------------------------------------------------------------------------
# Keyboard shortcuts JS
# ---------------------------------------------------------------------------
KEYBOARD_SHORTCUTS_JS = """
(function() {
    document.addEventListener('keydown', function(e) {
        // Only act if not typing in an input/textarea
        var tag = (e.target || e.srcElement).tagName.toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

        // Ctrl+Enter = Generate
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            var genBtn = document.querySelector('#QuickGen button.primary');
            if (genBtn) { genBtn.click(); e.preventDefault(); }
        }
    });
})();
"""
