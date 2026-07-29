import json
import struct
import os

# --- ABSOLUTE PATH RESOLUTION ---
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TOOLS_DIR)
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
ANIMS_DIR = os.path.join(ROOT_DIR, "anims")

# Auto-create directories if they don't exist
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(ANIMS_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(CONFIG_DIR, "robot_master.json")
CPP_HEADER_FILE = os.path.join(ROOT_DIR, "robot_config.h")
CONFIG_BIN_FILE = os.path.join(CONFIG_DIR, "config.bin")
# --------------------------------

# Complete fallback list ensuring ALL virtual rendering joints exist for the C++ header
DEFAULT_JOINTS = {
    "yaw": {"id": 0, "region": 0, "control_type": 1, "hardware_address": 0, "r_min": -45.0, "r_max": 45.0, "r_init": 0.0, "cmd_min": 500, "cmd_max": 2500, "cmd_init": 1500, "def_spd": 100, "max_spd": 255, "max_acc": 255},
    "neck_base_pitch": {"id": 1, "region": 0, "control_type": 1, "hardware_address": 1, "r_min": -85.0, "r_max": -25.0, "r_init": -25.0, "cmd_min": 500, "cmd_max": 2500, "cmd_init": 1500, "def_spd": 80, "max_spd": 255, "max_acc": 255},
    "neck_top_pitch": {"id": 2, "region": 0, "control_type": 1, "hardware_address": 2, "r_min": -60.0, "r_max": 110.0, "r_init": 0.0, "cmd_min": 500, "cmd_max": 2500, "cmd_init": 1500, "def_spd": 80, "max_spd": 255, "max_acc": 255},
    "head_pitch": {"id": 3, "region": 0, "control_type": 1, "hardware_address": 3, "r_min": -15.0, "r_max": 100.0, "r_init": 0.0, "cmd_min": 500, "cmd_max": 2500, "cmd_init": 1500, "def_spd": 100, "max_spd": 255, "max_acc": 255},
    "left_eye": {"id": 4, "region": 1, "control_type": 1, "hardware_address": 4, "r_min": -45.0, "r_max": 45.0, "r_init": 0.0, "cmd_min": 500, "cmd_max": 2500, "cmd_init": 1500, "def_spd": 120, "max_spd": 255, "max_acc": 255},
    "right_eye": {"id": 5, "region": 1, "control_type": 1, "hardware_address": 5, "r_min": -45.0, "r_max": 45.0, "r_init": 0.0, "cmd_min": 500, "cmd_max": 2500, "cmd_init": 1500, "def_spd": 120, "max_spd": 255, "max_acc": 255},
    
    # Virtual Render Joints
    "v_eyelid": {"id": 100, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 0.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 0, "def_spd": 60, "max_spd": 255, "max_acc": 255},
    "v_r_eyelid": {"id": 101, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 0.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 0, "def_spd": 60, "max_spd": 255, "max_acc": 255},
    "v_glow_color": {"id": 102, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 127.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 127, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_glow_pulse": {"id": 103, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 0.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 0, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_aperture": {"id": 104, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 0.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 0, "def_spd": 60, "max_spd": 255, "max_acc": 255},
    "v_gaze_x": {"id": 105, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 127.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 127, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_gaze_y": {"id": 106, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 127.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 127, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_r_gaze_x": {"id": 107, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 127.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 127, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_r_gaze_y": {"id": 108, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 127.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 127, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_img_select": {"id": 109, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 0.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 0, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_img_opacity": {"id": 110, "region": 1, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 0.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 0, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    
    # System Commands 
    "v_audio_play": {"id": 115, "region": 5, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 0.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 0, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_play_anim": {"id": 116, "region": 5, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 0.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 0, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_asymmetry": {"id": 117, "region": 5, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 1.0, "r_init": 0.0, "cmd_min": 0, "cmd_max": 1, "cmd_init": 0, "def_spd": 255, "max_spd": 255, "max_acc": 255},
    "v_idle_state": {"id": 118, "region": 5, "control_type": 2, "hardware_address": -1, "r_min": 0.0, "r_max": 255.0, "r_init": 1.0, "cmd_min": 0, "cmd_max": 255, "cmd_init": 1, "def_spd": 255, "max_spd": 255, "max_acc": 255},
}

def load_master_config():
    joints = dict(DEFAULT_JOINTS) 
    version = 1
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                
            if isinstance(data, dict):
                version = data.get("version", 1)
                loaded_joints = data.get("joints", {})
            else:
                loaded_joints = data
                
            if isinstance(loaded_joints, dict):
                for k, v in loaded_joints.items():
                    joints[k] = v
            elif isinstance(loaded_joints, list):
                for item in loaded_joints:
                    if isinstance(item, dict):
                        if "name" in item:
                            name = item.pop("name")
                            joints[name] = item
                        else:
                            for k, v in item.items():
                                joints[k] = v
        except Exception as e:
            print(f"Notice: Loading defaults due to JSON structure change: {e}")
            
    return version, joints

def load_joint_map():
    _, joints = load_master_config()
    return joints

def save_master_config(version, joints):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"version": version, "joints": joints}, f, indent=4)

def export_cpp_header(joints):
    # Only injects VIRTUAL/SYSTEM joints into the C++ compiler.
    with open(CPP_HEADER_FILE, "w") as f:
        f.write("// AUTO-GENERATED BY WLE5 IDE (VIRTUAL JOINTS ONLY)\n")
        f.write("#ifndef ROBOT_CONFIG_H\n#define ROBOT_CONFIG_H\n\n")
        for name, cfg in joints.items():
            if name.startswith("v_"):
                f.write(f"#define {name.upper()} {cfg['id']}\n")
        f.write("\n#endif\n")

def export_config_bin(version, joints):
    bin_data = bytearray(b'WLEC')
    bin_data.extend(struct.pack('<I', version))
    
    active_joints = [name for name, cfg in joints.items() if cfg.get("id", -1) >= 0]
    bin_data.append(len(active_joints))
    
    for name in active_joints:
        j = joints[name]
        name_bytes = name.encode('utf-8')[:31].ljust(32, b'\x00')
        
        # CHANGED: The 11th format character is now 'h' (16-bit int) to handle values like 1500
        packed = struct.pack('<B 32s B B b f f f h h h B B B',
            j["id"], name_bytes,
            j.get("region", 0), j.get("control_type", 0), j.get("hardware_address", -1),
            float(j.get("r_min", 0.0)), float(j.get("r_max", 100.0)), float(j.get("r_init", 0.0)),
            int(j.get("cmd_min", 0)), int(j.get("cmd_max", 0)), 
            int(j.get("cmd_init", 0)), # Now packs safely as a 2-byte integer
            int(j.get("def_spd", 100)), int(j.get("max_spd", 255)), int(j.get("max_acc", 255))
        )
        bin_data.extend(packed)
        
    with open(CONFIG_BIN_FILE, "wb") as f:
        f.write(bin_data)