"""
Quick Gen v2.0 — Full Smoke Test + Stress Test Suite
Run: python tests/smoke_test.py
"""
import os, json, ast, sys, hashlib, glob, importlib.util, urllib.request, types

# Resolve project root relative to this script (tests/ -> project root)
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# Mock the WanGP internal modules so plugin can import outside server context
sys.path.insert(0, PROJECT_ROOT)
shared_mod = types.ModuleType('shared')
utils_mod = types.ModuleType('shared.utils')
plugins_mod = types.ModuleType('shared.utils.plugins')

class MockPlugin:
    def __init__(self, *a, **kw): pass
    def get_current_model_settings(self, state): return {}
    def set_current_model_settings(self, state, settings): pass

plugins_mod.WAN2GPPlugin = MockPlugin
shared_mod.utils = utils_mod
utils_mod.plugins = plugins_mod
sys.modules['shared'] = shared_mod
sys.modules['shared.utils'] = utils_mod
sys.modules['shared.utils.plugins'] = plugins_mod

LORA_DIR = os.path.join(PROJECT_ROOT, 'loras', 'wan')
PRESETS_DIR = os.path.join(PROJECT_ROOT, 'profiles', 'wan_2_2')
PLUGIN_DIR = os.path.join(PROJECT_ROOT, 'plugins', 'wan2gp-nsfw-quickgen')

errors = []
warnings = []

def test_pass(msg):
    print(f'  [PASS] {msg}')

def test_fail(msg):
    errors.append(msg)
    print(f'  [FAIL] {msg}')

def test_warn(msg):
    warnings.append(msg)
    print(f'  [WARN] {msg}')

print('=' * 70)
print('SMOKE TEST SUITE — Quick Gen v2.0')
print('=' * 70)

# =====================================================================
# TEST 1: Plugin syntax + full import
# =====================================================================
print('\n[TEST 1] Plugin syntax and module import')
try:
    with open(f'{PLUGIN_DIR}/plugin.py', 'r', encoding='utf-8') as f:
        source = f.read()
    ast.parse(source)
    test_pass(f'Syntax OK ({len(source)} bytes, {source.count(chr(10))} lines)')
except SyntaxError as e:
    test_fail(f'Syntax error: {e}')

spec = importlib.util.spec_from_file_location('qg', f'{PLUGIN_DIR}/plugin.py')
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    test_pass('Module imports OK')
except Exception as e:
    test_fail(f'Import error: {e}')
    sys.exit(1)

# =====================================================================
# TEST 2: scene_meta.json integrity
# =====================================================================
print('\n[TEST 2] scene_meta.json integrity')
try:
    with open(f'{PLUGIN_DIR}/scene_meta.json', 'r', encoding='utf-8') as f:
        sm = json.load(f)
    test_pass(f'Valid JSON ({len(sm)} scenes)')
except Exception as e:
    test_fail(f'scene_meta.json parse error: {e}')
    sm = {}

required_meta_keys = ['prompt', 'negative_extra', 'default_duration_frames', 'default_aspect',
                       'default_fidelity', 'default_camera', 'image_hint', 'scene_category',
                       'implant_motion', 'male_default', 'default_gaze', 'default_hair']
for scene_name, meta in sm.items():
    missing_keys = [k for k in required_meta_keys if k not in meta]
    if missing_keys:
        test_fail(f'scene_meta "{scene_name}" missing keys: {missing_keys}')
    else:
        test_pass(f'"{scene_name}" has all {len(required_meta_keys)} required keys')

# =====================================================================
# TEST 3: type_defaults.json integrity
# =====================================================================
print('\n[TEST 3] type_defaults.json integrity')
try:
    with open(f'{PLUGIN_DIR}/type_defaults.json', 'r', encoding='utf-8') as f:
        td = json.load(f)
    required_td_keys = ['body_prompt', 'body_negative', 'base_negative', 'quality_prompt',
                         'skin_tone', 'hair_color', 'makeup_style', 'camera_prompts',
                         'modifier_chips', 'gaze_prompts', 'intensity_multipliers',
                         'quality_presets', 'aspect_ratios']
    missing = [k for k in required_td_keys if k not in td]
    if missing:
        test_fail(f'type_defaults.json missing keys: {missing}')
    else:
        test_pass(f'All {len(required_td_keys)} required keys present')

    chips = td.get('modifier_chips', {})
    empty_chips = [k for k, v in chips.items() if not v.get('prompt', '').strip()]
    if empty_chips:
        test_warn(f'{len(empty_chips)} chips with empty prompts: {empty_chips[:5]}')
    else:
        test_pass(f'All {len(chips)} modifier chips have prompt text')

    qp = td.get('quality_presets', {})
    for qname, qdata in qp.items():
        if 'num_inference_steps' not in qdata:
            test_fail(f'quality preset "{qname}" missing num_inference_steps')
        else:
            test_pass(f'quality preset "{qname}": {qdata["num_inference_steps"]} steps')
except Exception as e:
    test_fail(f'type_defaults.json error: {e}')
    td = {}

# =====================================================================
# TEST 4: SCENE_PRESETS dict matches actual files + scene_meta
# =====================================================================
print('\n[TEST 4] SCENE_PRESETS maps to real files')
for scene_name, filename in mod.SCENE_PRESETS.items():
    path = os.path.join(PRESETS_DIR, filename)
    if os.path.exists(path):
        test_pass(f'"{scene_name}" -> {filename}')
    else:
        test_fail(f'"{scene_name}" -> {filename} DOES NOT EXIST')

print('\n[TEST 4b] Every SCENE_PRESET has scene_meta entry')
for scene_name in mod.SCENE_PRESETS:
    if scene_name in sm:
        test_pass(f'"{scene_name}" in scene_meta')
    else:
        test_fail(f'"{scene_name}" MISSING from scene_meta')

# =====================================================================
# TEST 5: LoRA file integrity (no stubs, real sizes)
# =====================================================================
print('\n[TEST 5] LoRA file integrity')
actual_loras = {}
for f in sorted(os.listdir(LORA_DIR)):
    if f.endswith('.safetensors'):
        path = os.path.join(LORA_DIR, f)
        size = os.path.getsize(path)
        actual_loras[f] = size
        if size < 10_000_000:  # <10MB is definitely wrong for a WAN 2.2 LoRA
            test_fail(f'{f}: {size/1024/1024:.1f} MB (too small — likely stub or failed download)')
        else:
            test_pass(f'{f}: {size/1024/1024:.1f} MB')

# =====================================================================
# TEST 6: Every preset's LoRAs exist + weights valid
# =====================================================================
print('\n[TEST 6] Preset LoRA references + weight validation')
our_presets = [f for f in os.listdir(PRESETS_DIR) if f.endswith('.json')]
for pf in sorted(our_presets):
    path = os.path.join(PRESETS_DIR, pf)
    with open(path, 'r') as f:
        data = json.load(f)
    loras = data.get('activated_loras', [])
    weights_str = data.get('loras_multipliers', '')
    weights = weights_str.split() if weights_str.strip() else []

    if any(l.startswith('http') for l in loras):
        continue

    missing = [l for l in loras if l not in actual_loras]
    stubs = [l for l in loras if l in actual_loras and actual_loras[l] < 1000]
    wmismatch = len(weights) != len(loras)
    dupes = [l for l in set(loras) if loras.count(l) > 1]

    bad_weights = []
    for i, w in enumerate(weights):
        try:
            v = float(w)
            if v < 0 or v > 2.0:
                bad_weights.append(f'{w}@idx{i}')
        except ValueError:
            bad_weights.append(f'{w}@idx{i}(NaN)')

    issues = []
    if missing: issues.append(f'{len(missing)} missing LoRAs')
    if stubs: issues.append(f'{len(stubs)} stub files')
    if wmismatch: issues.append(f'weight count mismatch ({len(loras)}L vs {len(weights)}W)')
    if dupes: issues.append(f'duplicate LoRAs: {dupes}')
    if bad_weights: issues.append(f'bad weights: {bad_weights}')

    if issues:
        test_fail(f'{pf}: {"; ".join(issues)}')
        for m in missing: print(f'         MISSING: {m}')
    else:
        has_pusa = '+Pusa' if any('Pusa' in l for l in loras) else ''
        test_pass(f'{pf}: {len(loras)}L/{len(weights)}W {has_pusa}')

# =====================================================================
# TEST 7: build_prompt stress test (all scenes × cameras × intensities)
# =====================================================================
print('\n[TEST 7] build_prompt stress test')
test_mods = ['oily', 'throat_bulge', 'mascara_running', 'eye_contact', 'jiggle']
test_cams = ['pov_above', 'side', 'pov_below', 'static_wide', 'slow_pan']
test_gazes = ['camera', 'looking_up', 'eyes_closed', 'eyes_rolling', 'away']
test_ints = ['gentle', 'rough', 'extreme']
user_t = {'skin_tone': 'fair', 'hair_color': 'blonde', 'makeup_style': 'pornstar_glam', 'aesthetic': 'pornstar'}

prompt_issues = 0
total = 0
for scene in mod.SCENE_PRESETS:
    for cam in test_cams:
        for gaze in test_gazes[:2]:
            for intensity in test_ints:
                total += 1
                try:
                    pos, neg = mod.build_prompt(scene, sm, td, user_t, test_mods, cam, gaze, 'gripped', 'none', 'ring_light', 'warm', 'glossy', 'pov_hands', intensity, 0)
                    if len(pos) < 100:
                        test_warn(f'Short prompt: {scene}/{cam}/{gaze} = {len(pos)} chars')
                        prompt_issues += 1
                except Exception as e:
                    test_fail(f'build_prompt crash: {scene}/{cam}/{gaze}/{intensity}: {e}')
                    prompt_issues += 1

if prompt_issues == 0:
    test_pass(f'All {total} prompt combinations generated OK')
else:
    test_warn(f'{total} combinations tested, {prompt_issues} issues')

# Also test continuation depths 0-5
for depth in range(6):
    try:
        pos, neg = mod.build_prompt('Deepthroat / Facefuck', sm, td, user_t, test_mods, 'pov_above', 'camera', 'gripped', 'none', 'ring_light', 'warm', 'glossy', 'pov_hands', 'rough', depth)
        test_pass(f'Continuation depth {depth}: {len(pos)} chars')
    except Exception as e:
        test_fail(f'Continuation depth {depth} crashed: {e}')

# =====================================================================
# TEST 8: Weight scaling
# =====================================================================
print('\n[TEST 8] Weight scaling edge cases')
weight_tests = [
    ('0.8 0.7 0.9', 1.0, '0.80 0.70 0.90'),
    ('0.8 0.7 0.9', 0.0, '0.00 0.00 0.00'),
    ('0.8 0.7 0.9', 99.0, '1.50 1.50 1.50'),
    ('', 1.0, ''),
    ('1.0', 1.3, '1.30'),
]
for input_w, mult, expected in weight_tests:
    result = mod._scale_lora_weights(input_w, mult)
    if result == expected:
        test_pass(f'scale("{input_w}", {mult}) = "{result}"')
    else:
        test_fail(f'scale("{input_w}", {mult}) = "{result}" (expected "{expected}")')

# =====================================================================
# TEST 9: Time estimates
# =====================================================================
print('\n[TEST 9] Time estimate sanity')
time_tests = [
    (4, 81, 480, 848, 5, 15),
    (8, 81, 480, 848, 10, 30),
    (12, 129, 480, 848, 20, 60),
    (4, 33, 480, 848, 2, 8),
]
for steps, frames, w, h, min_m, max_m in time_tests:
    result = mod._estimate_time(steps, frames, w, h)
    if 'm' in result:
        mins = int(result.split('~')[1].split('m')[0])
    else:
        mins = 0
    if min_m <= mins <= max_m:
        test_pass(f'{steps}step/{frames}f/{w}x{h}: {result}')
    else:
        test_warn(f'{steps}step/{frames}f/{w}x{h}: {result} (expected {min_m}-{max_m}m)')

# =====================================================================
# TEST 10: Model validation
# =====================================================================
print('\n[TEST 10] Model type validation')
model_tests = [
    ({}, True), ({'model_type': ''}, True), ({'model_type': 'ltx2_22b'}, True),
    ({'model_type': 'nsfw_i2v_rapid'}, False), ({'model_type': 'wan_i2v_14b'}, False),
    ({'model_type': 'nsfw_mega_v12'}, False),
]
for state, should_error in model_tests:
    result = mod._check_model_type(state)
    if bool(result) == should_error:
        test_pass(f'state={state} -> error={bool(result)}')
    else:
        test_fail(f'state={state} -> error={bool(result)} (expected {should_error})')

# =====================================================================
# TEST 11: GGUF model + finetune config
# =====================================================================
print('\n[TEST 11] GGUF model + finetune config')
gguf_v12 = os.path.join(PROJECT_ROOT, 'ckpts', 'wan2.2-rapid-mega-aio-nsfw-v12.1-Q3_K.gguf')
gguf_v10 = os.path.join(PROJECT_ROOT, 'ckpts', 'wan2.2-i2v-rapid-aio-v10-nsfw-Q3_K.gguf')
found_gguf = False
for gp, label in [(gguf_v12, 'Mega v12.1'), (gguf_v10, 'v10')]:
    if os.path.exists(gp):
        size_gb = os.path.getsize(gp) / (1024**3)
        if size_gb > 5:
            test_pass(f'GGUF model ({label}): {size_gb:.1f} GB')
            found_gguf = True
        else:
            test_fail(f'GGUF model ({label}) too small: {size_gb:.1f} GB')
if not found_gguf:
    test_fail('No GGUF model found')

ft_path = os.path.join(PROJECT_ROOT, 'finetunes', 'nsfw_i2v_rapid.json')
if os.path.exists(ft_path):
    with open(ft_path, 'r') as f:
        ft = json.load(f)
    m = ft.get('model', {})
    for check_name, check_val in [
        ('architecture=i2v_2_2', m.get('architecture') == 'i2v_2_2'),
        ('has_URLs', bool(m.get('URLs'))),
        ('has_prompt_enhancer', bool(m.get('video_prompt_enhancer_instructions'))),
        ('steps=4', ft.get('num_inference_steps') == 4),
        ('solver=euler', ft.get('sample_solvers') == 'euler'),
    ]:
        if check_val:
            test_pass(check_name)
        else:
            test_fail(f'Finetune: {check_name}')

# =====================================================================
# TEST 12: Server health
# =====================================================================
print('\n[TEST 12] Server health check')
try:
    resp = urllib.request.urlopen('http://localhost:7860/', timeout=5)
    if resp.getcode() == 200:
        test_pass(f'Server responding HTTP {resp.getcode()}')
    else:
        test_warn(f'Server HTTP {resp.getcode()}')
except Exception as e:
    test_warn(f'Server not responding: {e}')

# =====================================================================
# TEST 13: _load_preset for every scene
# =====================================================================
print('\n[TEST 13] _load_preset for every scene')
for scene_name in mod.SCENE_PRESETS:
    preset = mod._load_preset(scene_name)
    if preset and 'activated_loras' in preset:
        lcount = len(preset['activated_loras'])
        test_pass(f'_load_preset("{scene_name}"): {lcount} LoRAs')
    else:
        test_fail(f'_load_preset("{scene_name}") returned None or invalid')

# =====================================================================
# TEST 14: Safetensors header validation (catch corrupt/ZIP files)
# =====================================================================
print('\n[TEST 14] Safetensors binary header validation')
import struct as _struct
for f in sorted(os.listdir(LORA_DIR)):
    if not f.endswith('.safetensors'):
        continue
    path = os.path.join(LORA_DIR, f)
    size = os.path.getsize(path)
    with open(path, 'rb') as fh:
        raw = fh.read(8)
        if len(raw) < 8:
            test_fail(f'{f}: file too small ({size} bytes)')
            continue
        header_size = _struct.unpack('<Q', raw[:8])[0]
        if header_size > 50_000_000 or header_size < 10:
            # Check if it's a ZIP (PK header)
            fh.seek(0)
            magic = fh.read(2)
            if magic == b'PK':
                test_fail(f'{f}: is a ZIP archive, not a safetensors file! Extract it first.')
            else:
                test_fail(f'{f}: invalid safetensors header (header_size={header_size})')
            continue
        test_pass(f'{f}: valid header ({header_size}B, {size/1024/1024:.0f}MB)')

# =====================================================================
# SUMMARY
# =====================================================================
print('\n' + '=' * 70)
print(f'RESULTS: {len(errors)} ERRORS, {len(warnings)} WARNINGS')
print('=' * 70)
if errors:
    print('\nCRITICAL ERRORS:')
    for e in errors:
        print(f'  X {e}')
if warnings:
    print('\nWARNINGS:')
    for w in warnings:
        print(f'  ⚠ {w}')
if not errors and not warnings:
    print('\n  PASS: ALL TESTS PASSED — ZERO ISSUES')
elif not errors:
    print(f'\n  PASS: ALL CRITICAL TESTS PASSED ({len(warnings)} minor warnings)')
else:
    print(f'\n  FAIL: {len(errors)} CRITICAL ISSUES NEED FIXING')

sys.exit(1 if errors else 0)
