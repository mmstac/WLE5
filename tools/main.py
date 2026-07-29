import time
import subprocess
import sys
import zlib
import os
from ursina import *
from ursina.shaders import lit_with_shadows_shader
app = Ursina(title="WLE5 3D Simulator", borderless=False)
window.exit_button.visible = False
Entity.default_shader = lit_with_shadows_shader

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import glob
import re
import math
import struct
import serial

from animation_engine import AnimationPlayer
from sender import parse_live_input
import wle_config

# Import strict directory paths
from wle_config import TOOLS_DIR, CONFIG_DIR, ANIMS_DIR

# =========================================================
# SHARED DATA & CONFIGURATION
# =========================================================
CFG_VERSION, JOINT_CONFIG = wle_config.load_master_config()
ID_TO_NAME = {v["id"]: k for k, v in JOINT_CONFIG.items()}
JOINTS_LIST = list(JOINT_CONFIG.keys())

esp32 = None
usb_telemetry_enabled = False
last_sent_pose = {}

HOTKEYS = {
    "yaw": "A/D", "neck_base_pitch": "W/S", "neck_top_pitch": "Q/E",
    "head_pitch": "Up/Dn", "left_eye": "T/G", "right_eye": "Y/H",
    "v_eyelid": "1/2"
}

SIMULATED_JOINTS = ["yaw", "neck_base_pitch", "neck_top_pitch", "head_pitch", "left_eye", "right_eye", "v_eyelid", "v_aperture", "v_glow_color"]

# =========================================================
# TKINTER UI SETUP
# =========================================================
tk_root = tk.Tk()
tk_root.title("WLE5 Animation Studio")
tk_root.geometry("1150x850") 

def on_tk_close():
    if esp32 and esp32.is_open:
        esp32.close()
    tk_root.destroy()
    application.quit()

tk_root.protocol("WM_DELETE_WINDOW", on_tk_close)

main_frame = tk.Frame(tk_root)
main_frame.pack(expand=True, fill=tk.BOTH)

# ---------------------------------------------------------
# TOOLBAR (MAIN)
# ---------------------------------------------------------
toolbar = tk.Frame(main_frame, bd=1, relief=tk.RAISED, bg="#e0e0e0")
toolbar.pack(side=tk.TOP, fill=tk.X)

def load_script_file():
    filepath = filedialog.askopenfilename(initialdir=ANIMS_DIR, defaultextension=".wle", filetypes=[("WLE Scripts", "*.wle"), ("Text Files", "*.txt"), ("All Files", "*.*")])
    if filepath:
        with open(filepath, 'r') as f:
            content = f.read()
        text_area.delete(1.0, tk.END)
        text_area.insert(tk.END, content)
        rescan_scripts()

def save_script_file():
    filepath = filedialog.asksaveasfilename(initialdir=ANIMS_DIR, defaultextension=".wle", filetypes=[("WLE Scripts", "*.wle"), ("Text Files", "*.txt"), ("All Files", "*.*")])
    if filepath:
        with open(filepath, 'w') as f:
            f.write(text_area.get(1.0, tk.END))
        messagebox.showinfo("Saved", f"Script saved successfully to:\n{filepath}")
        rescan_scripts()

btn_font = ("Verdana", 10, "bold")
tk.Button(toolbar, text="Load Script", font=btn_font, bg="#1A237E", fg="white", command=load_script_file).pack(side=tk.LEFT, padx=5, pady=4)
tk.Button(toolbar, text="Save Script", font=btn_font, bg="#1A237E", fg="white", command=save_script_file).pack(side=tk.LEFT, padx=5, pady=4)

def open_config_window():
    subprocess.Popen([sys.executable, os.path.join(TOOLS_DIR, "config_editor.py")])

# --- COM PORT & UNIFIED SYNC LOGIC ---
def toggle_connection():
    global esp32, usb_telemetry_enabled
    if esp32 and esp32.is_open:
        esp32.close()
        esp32 = None
        usb_telemetry_enabled = False
        conn_btn.config(text="Connect", bg="#4CAF50")
        push_log("USB Disconnected.")
    else:
        port = com_entry.get().strip().upper()
        try:
            esp32 = serial.Serial(port, 115200, timeout=0)
            conn_btn.config(text="Disconnect", bg="#f44336")
            push_log(f"USB Connected to {port}.")
        except serial.SerialException as e:
            messagebox.showerror("Port Error", f"Could not open {port}.\n\nEnsure the device is plugged in and the Arduino Serial Monitor is CLOSED.\n\nDetails: {e}")

def wait_for_esp_ack(timeout=1.0):
    start_t = time.time()
    while time.time() - start_t < timeout:
        tk_root.update()
        if esp32 and esp32.in_waiting > 0:
            if esp32.read(1) == b'\x01': 
                return True
        time.sleep(0.01)
    return False

def smart_sync():
    if not esp32 or not esp32.is_open:
        messagebox.showwarning("Not Connected", "Please connect to the ESP32 COM port first.")
        return

    sync_results = []
    
    # === 1. SYNC HARDWARE CONFIG ===
    cfg_bin_path = os.path.join(CONFIG_DIR, "config.bin")
    try:
        with open(cfg_bin_path, "rb") as f:
            cfg_data = f.read()
            local_cfg_version = struct.unpack('<I', cfg_data[4:8])[0]
    except FileNotFoundError:
        messagebox.showerror("Error", "config.bin missing. Please run Hardware Config to generate it.")
        return

    push_log(f"Checking Config Version (Local: {local_cfg_version})...")
    esp32.reset_input_buffer()
    esp32.write(bytearray([0xBB, 0x01])) # Query Config Version
    
    start_t = time.time()
    esp_cfg_version = None
    while time.time() - start_t < 1.0:
        tk_root.update()
        if esp32.in_waiting >= 4:
            esp_cfg_version = struct.unpack('<I', esp32.read(4))[0]
            break
        time.sleep(0.01)
        
    do_cfg_sync = False
    if esp_cfg_version is None:
        do_cfg_sync = messagebox.askyesno("Timeout", "ESP32 did not respond to Config Version query.\n\nForce config upload anyway?")
    elif esp_cfg_version == local_cfg_version:
        sync_results.append("Hardware Config: Skipped (Up to date)")
    else:
        push_log(f"ESP32 Config Version ({esp_cfg_version}) is outdated. Uploading...")
        do_cfg_sync = True

    if do_cfg_sync:
        file_size = len(cfg_data)
        esp32.write(bytearray([0xBB, 0x02]) + struct.pack('<I', file_size))
        if not wait_for_esp_ack():
            sync_results.append("Hardware Config: FAILED (No initial ACK)")
        else:
            success = True
            for i in range(0, file_size, 64):
                chunk = cfg_data[i:i+64]
                esp32.write(bytearray([0xBB, 0x03, len(chunk)]) + chunk)
                if not wait_for_esp_ack():
                    success = False
                    break
                tk_root.update()
            
            if success:
                esp32.write(bytearray([0xBB, 0x04]))
                if wait_for_esp_ack():
                    sync_results.append(f"Hardware Config: Updated to v{local_cfg_version}")
                else:
                    sync_results.append("Hardware Config: Transfer sent, but missing final ACK")
            else:
                sync_results.append("Hardware Config: FAILED (Timeout mid-transfer)")

    # === 2. COMPILE & SYNC ANIMATIONS ===
    script_files = glob.glob(os.path.join(ANIMS_DIR, "*.wle")) + glob.glob(os.path.join(ANIMS_DIR, "*.txt"))
    combined_text = ""
    for fname in script_files:
        with open(fname, 'r') as file:
            combined_text += file.read() + "\n"
            
    anim_hash = zlib.crc32(combined_text.encode('utf-8')) & 0xFFFFFFFF
    
    push_log(f"Checking Anim Hash (Local: {anim_hash})...")
    esp32.reset_input_buffer()
    esp32.write(bytearray([0xCC, 0x01])) # Query Anim Hash
    
    start_t = time.time()
    esp_anim_hash = None
    while time.time() - start_t < 1.0:
        tk_root.update()
        if esp32.in_waiting >= 4:
            esp_anim_hash = struct.unpack('<I', esp32.read(4))[0]
            break
        time.sleep(0.01)

    do_anim_sync = False
    if esp_anim_hash is None:
        do_anim_sync = messagebox.askyesno("Timeout", "ESP32 did not respond to Anim Hash query.\n\nForce animation compile and upload anyway?")
    elif esp_anim_hash == anim_hash:
        sync_results.append("Animations: Skipped (Up to date)")
    else:
        push_log("ESP32 Animations are outdated. Compiling and Uploading...")
        do_anim_sync = True

    if do_anim_sync:
        rescan_scripts()
        bin_data = bytearray(b'WLEA')
        bin_data.extend(struct.pack('<I', anim_hash))
        bin_data.append(len(animations))
        
        for anim in animations:
            name_bytes = anim["name"].encode('utf-8')[:31].ljust(32, b'\x00')
            anim_player.load_script(anim["name"], anim["script"])
            kf_count = len(anim_player.keyframes)
            bin_data.extend(name_bytes)
            bin_data.extend(struct.pack('<H', kf_count))
            
            for kf in anim_player.keyframes:
                time_val = int(kf["time"] * 10) & 0xFF
                cmd_count = len(kf["targets"])
                bin_data.extend(struct.pack('<B B', time_val, cmd_count))
                
                for j_name, cmd in kf["targets"].items():
                    cfg = JOINT_CONFIG[j_name]
                    clamped = max(cfg["r_min"], min(cfg["r_max"], cmd["target"]))
                    norm = (clamped - cfg["r_min"]) / (abs(cfg["r_max"] - cfg["r_min"]) or 1)
                    byte_val = int(norm * 255)
                    bin_data.extend(struct.pack('<B B B', cmd["id"], byte_val, cmd["speed"]))
        
        anim_bin_path = os.path.join(CONFIG_DIR, "anims.bin")
        with open(anim_bin_path, "wb") as f:
            f.write(bin_data)
            
        file_size = len(bin_data)
        esp32.write(bytearray([0xCC, 0x02]) + struct.pack('<I', file_size))
        
        if not wait_for_esp_ack():
            sync_results.append("Animations: FAILED (No initial ACK)")
        else:
            success = True
            for i in range(0, file_size, 64):
                chunk = bin_data[i:i+64]
                esp32.write(bytearray([0xCC, 0x03, len(chunk)]) + chunk)
                if not wait_for_esp_ack():
                    success = False
                    break
                tk_root.update()
            
            if success:
                esp32.write(bytearray([0xCC, 0x04]))
                if wait_for_esp_ack():
                    sync_results.append(f"Animations: Compiled & Updated successfully")
                else:
                    sync_results.append("Animations: Transfer sent, but missing final ACK")
            else:
                sync_results.append("Animations: FAILED (Timeout mid-transfer)")

    messagebox.showinfo("Smart Sync Complete", "\n".join(sync_results))
    push_log("Sync Process Completed.")

tk.Button(toolbar, text="⚙ Hardware Config", font=btn_font, bg="#424242", fg="white", command=open_config_window).pack(side=tk.RIGHT, padx=15, pady=4)
tk.Button(toolbar, text="Smart Sync to ESP32", font=btn_font, bg="#8B0000", fg="white", command=smart_sync).pack(side=tk.RIGHT, padx=5, pady=4)

# COM Port UI Elements
conn_btn = tk.Button(toolbar, text="Connect", font=("Verdana", 9, "bold"), bg="#4CAF50", fg="white", command=toggle_connection)
conn_btn.pack(side=tk.RIGHT, padx=(2, 15), pady=4)

com_entry = tk.Entry(toolbar, font=("Verdana", 10, "bold"), width=6)
com_entry.insert(0, "COM9")
com_entry.pack(side=tk.RIGHT, padx=2, pady=4)
tk.Label(toolbar, text="PORT:", font=("Verdana", 9, "bold")).pack(side=tk.RIGHT)

joints_frame = tk.Frame(main_frame, pady=10)
joints_frame.pack(side=tk.TOP, fill=tk.X, padx=10)

sync_frame = tk.Frame(joints_frame)
sync_frame.grid(row=0, column=2, columnspan=2, padx=5, pady=5)

def pull_from_sim():
    pose = get_current_pose()
    for j_name, entries in tk_inputs.items():
        if entries["tgt"].get().strip() != "":
            if j_name in pose:
                entries["tgt"].delete(0, tk.END)
                entries["tgt"].insert(0, f"{pose[j_name]:.1f}")

def push_to_sim():
    cmd_parts = []
    for j_name, entries in tk_inputs.items():
        t_val = entries["tgt"].get().strip()
        s_val = entries["spd"].get().strip()
        if t_val:
            cmd_parts.append(f"{j_name}={t_val},{s_val}" if s_val else f"{j_name}={t_val}")
    if cmd_parts:
        script_text = f"[Anim: TkinterPush]\n@0.0s " + "    ".join(cmd_parts)
        anim_player.load_script("TkinterPush", script_text)
        anim_player.play(get_current_pose())

def jog_joint(j_name, delta):
    try:
        curr = float(tk_pos_labels[j_name].cget("text"))
        new_val = curr + delta
        r_min, r_max = JOINT_CONFIG[j_name]["r_min"], JOINT_CONFIG[j_name]["r_max"]
        new_val = max(r_min, min(r_max, new_val))
        
        script_text = f"[Anim: JogCommand]\n@0.0s {j_name}={new_val},255"
        anim_player.load_script("JogCommand", script_text)
        anim_player.play(get_current_pose())
    except Exception:
        pass

tk.Button(sync_frame, text="< PULL", font=("Verdana", 9, "bold"), bg="#ddd", command=pull_from_sim).pack(side=tk.LEFT, padx=2)
tk.Button(sync_frame, text="PUSH >", font=("Verdana", 9, "bold"), bg="#ddd", command=push_to_sim).pack(side=tk.LEFT, padx=2)

tk.Label(joints_frame, text="SIM", font=("Verdana", 9, "bold")).grid(row=0, column=1)
tk.Label(joints_frame, text="SCRIPT", font=("Verdana", 9, "bold")).grid(row=0, column=4, columnspan=2)

headers = ["Joint", "POS", "Keys", "Min", "Set", "Max", "Spd", "Def Spd"]
widths = [16, 6, 4, 6, 4, 6, 4, 8]
for col, (text, width) in enumerate(zip(headers, widths)):
    tk.Label(joints_frame, text=text, font=("Verdana", 10, "bold"), width=width).grid(row=1, column=col, pady=2)

tk_inputs = {}
tk_pos_labels = {}

for i, joint in enumerate(JOINTS_LIST, start=2):
    if joint not in JOINT_CONFIG: continue
    cfg = JOINT_CONFIG[joint]
    
    is_sim = joint in SIMULATED_JOINTS
    bg_color = "#333333" if not is_sim else None
    fg_color = "white" if not is_sim else "black"
    
    tk.Label(joints_frame, text=joint, font=("Verdana", 10, "bold"), width=16, anchor="w", bg=bg_color, fg=fg_color).grid(row=i, column=0, padx=2, pady=1)
    
    pos_lbl = tk.Label(joints_frame, text="0.0", font=("Verdana", 10), width=6, fg="blue")
    pos_lbl.grid(row=i, column=1)
    tk_pos_labels[joint] = pos_lbl
    
    keys_frame = tk.Frame(joints_frame)
    keys_frame.grid(row=i, column=2, padx=0)
    hk = HOTKEYS.get(joint, "")
    if "/" in hk:
        k1, k2 = hk.split("/")[:2]
        tk.Button(keys_frame, text=k1, font=("Verdana", 7), width=1, padx=2, command=lambda j=joint: jog_joint(j, -5)).pack(side=tk.LEFT, padx=1)
        tk.Button(keys_frame, text=k2, font=("Verdana", 7), width=1, padx=2, command=lambda j=joint: jog_joint(j, 5)).pack(side=tk.LEFT, padx=1)
    elif hk:
        tk.Label(keys_frame, text=hk, font=("Verdana", 8, "italic"), fg="gray").pack()
        
    tk.Label(joints_frame, text=str(cfg["r_min"]), font=("Verdana", 10), width=6, bg="#d3d3d3").grid(row=i, column=3)
    tgt_entry = tk.Entry(joints_frame, font=("Verdana", 11, "bold"), width=5)
    tgt_entry.grid(row=i, column=4, padx=2)
    tk.Label(joints_frame, text=str(cfg["r_max"]), font=("Verdana", 10), width=6, bg="#d3d3d3").grid(row=i, column=5)
    spd_entry = tk.Entry(joints_frame, font=("Verdana", 11, "bold"), width=4)
    spd_entry.grid(row=i, column=6, padx=2)
    tk.Label(joints_frame, text=str(cfg["def_spd"]), font=("Verdana", 10), width=8).grid(row=i, column=7)
    
    tk_inputs[joint] = {"tgt": tgt_entry, "spd": spd_entry}

tk.Frame(main_frame, height=15).pack(side=tk.TOP, fill=tk.X)

editor_frame = tk.Frame(main_frame, pady=10)
editor_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=10, pady=5)

editor_toolbar = tk.Frame(editor_frame)
editor_toolbar.pack(side=tk.TOP, fill=tk.X)

tk.Label(editor_toolbar, text="Time(s):", font=("Verdana", 11, "bold")).pack(side=tk.LEFT)
time_entry = tk.Entry(editor_toolbar, font=("Verdana", 12, "bold"), width=6)
time_entry.insert(0, "0.0")
time_entry.pack(side=tk.LEFT, padx=5)

def insert_line_from_ui():
    time_val = time_entry.get().strip()
    line_parts = [f"@{time_val}s"]
    for j_name, entries in tk_inputs.items():
        t_val, s_val = entries["tgt"].get().strip(), entries["spd"].get().strip()
        if t_val:
            line_parts.append(f"{j_name}={t_val},{s_val}" if s_val else f"{j_name}={t_val}")
    if len(line_parts) > 1:
        text_area.insert(tk.INSERT, "    ".join(line_parts) + "\n")
        for entries in tk_inputs.values():
            entries["tgt"].delete(0, tk.END)
            entries["spd"].delete(0, tk.END)

tk.Button(editor_toolbar, text="Add Line To Script", font=("Verdana", 10, "bold"), bg="#4CAF50", fg="white", command=insert_line_from_ui).pack(side=tk.LEFT, padx=10)

def run_selected_script():
    target_anim = script_combo.get()
    if not target_anim:
        messagebox.showwarning("Warning", "Please select an animation from the dropdown.")
        return
    content = text_area.get(1.0, tk.END)
    anim_player.load_script(target_anim, content)
    anim_player.play(get_current_pose())

def update_script_dropdown():
    content = text_area.get(1.0, tk.END)
    anim_names = re.findall(r'\[Anim:\s*(.+?)\]', content, re.IGNORECASE)
    script_combo['values'] = anim_names
    if anim_names and script_combo.get() not in anim_names:
        script_combo.current(0)
    elif not anim_names:
        script_combo.set('')

tk.Button(editor_toolbar, text="Test in Sim", font=("Verdana", 10, "bold"), bg="#2196F3", fg="white", command=run_selected_script).pack(side=tk.RIGHT, padx=(5,0))
script_combo = ttk.Combobox(editor_toolbar, width=15, font=("Verdana", 10), state="readonly", postcommand=update_script_dropdown)
script_combo.pack(side=tk.RIGHT, padx=5)
tk.Label(editor_toolbar, text="Target Anim:", font=("Verdana", 10, "bold")).pack(side=tk.RIGHT)

text_area = tk.Text(editor_frame, wrap=tk.NONE, font=("Consolas", 14))
text_area.pack(expand=True, fill=tk.BOTH)
text_area.insert(tk.END, "# Write your animation scripts here...")

# --- DYNAMIC TEXT AREA PARSER FIX ---
# --- DYNAMIC TEXT AREA PARSER FIX ---
def on_text_area_click(event=None):
    # Get the line number where the cursor currently is
    cursor_pos = text_area.index(tk.INSERT)
    line_num = cursor_pos.split('.')[0]
    
    # Extract the exact text of that line
    line_text = text_area.get(f"{line_num}.0", f"{line_num}.end").strip()
    
    # Ignore empty lines, comments, or header tags
    if not line_text or line_text.startswith('#') or line_text.startswith('['):
        return

    # 1. We clicked a valid keyframe line. Wipe all boxes clean first!
    for entries in tk_inputs.values():
        entries["tgt"].delete(0, tk.END)
        entries["spd"].delete(0, tk.END)

    # 2. Parse the commands (matches: joint_name=target,speed)
    commands = re.findall(r'([a-zA-Z0-9_]+)=([-\d\.]+)(?:,([\d\.]+))?', line_text)
    
    # 3. Push the parsed values to your dynamic UI sliders
    for match in commands:
        joint_name = match[0]
        value_str = match[1]
        speed_str = match[2] # Will be an empty string if no speed was written
        
        if joint_name in JOINT_CONFIG and joint_name in tk_inputs: 
            try:
                val = float(value_str)
                tk_inputs[joint_name]["tgt"].insert(0, str(val))
                if speed_str:
                    tk_inputs[joint_name]["spd"].insert(0, speed_str)
            except ValueError:
                pass
            
# Bind both mouse clicks and keyboard arrow navigation to trigger the parser update
text_area.bind('<ButtonRelease-1>', on_text_area_click)
text_area.bind('<KeyRelease>', on_text_area_click)


# =========================================================
# URSINA OVERLAYS & BEHAVIORS
# =========================================================
EditorCamera()
camera.position = (0, 1.0, -5.5)

sun = DirectionalLight(y=2, z=3, shadows=True, rotation=(45, -45, 0))
AmbientLight(color=color.rgba(120, 120, 120, 255))

servo_display = Text(text="Initializing...", position=(-0.85, 0.45), scale=1.2, color=color.white, background=True)

command_log_display = Text(text="--- COMMAND STREAM ---\nWaiting for script...", position=(0.40, 0.45), scale=1.0, color=color.green, background=True)
log_messages = []

def push_log(msg):
    log_messages.append(msg)
    while len(log_messages) > 20: log_messages.pop(0)
    command_log_display.text = "--- COMMAND STREAM ---\n" + "\n".join(log_messages)

def send_usb_commands(targets):
    if not esp32 or not esp32.is_open or not usb_telemetry_enabled: return
    commands = []
    for t in targets:
        j_id = t["id"]
        j_name = ID_TO_NAME.get(j_id)
        if not j_name: continue
        
        cfg = JOINT_CONFIG[j_name]
        clamped = max(cfg["r_min"], min(cfg["r_max"], t["target"]))
        norm = (clamped - cfg["r_min"]) / (abs(cfg["r_max"] - cfg["r_min"]) or 1)
        byte_val = int(norm * 255)
        commands.append({"id": j_id, "set": byte_val, "spd": t["speed"]})
        
    if commands:
        packet = bytearray([0xAA, len(commands)])
        for cmd in commands[:16]: packet.extend(struct.pack('BBB', cmd["id"], cmd["set"], cmd["spd"]))
        esp32.write(packet)

def on_anim_transmit(targets):
    send_usb_commands(targets)
    for t in targets:
        j_name = ID_TO_NAME.get(t["id"], f"ID_{t['id']}")
        push_log(f"[{round(anim_player.current_time, 2)}s] {j_name}: set={t['target']} spd={t['speed']}")

# ---------------------------------------------------------
# RIGGING HIERARCHY & 3D GEOMETRY
# ---------------------------------------------------------
base_pivot = Entity(position=(0, 0, 0))
base_mesh = Entity(parent=base_pivot, model="cube", scale=(1.50, 0.1, 1.35), color=color.gray)

neck1_pivot = Entity(parent=base_pivot, position=(0, 0.1, 0.325))
neck1_mesh = Entity(parent=neck1_pivot, model="cube", scale=(0.3, 0.58, 0.3), color=color.orange, origin_y=-0.5)
Entity(parent=neck1_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.40, 0.05), rotation_z=90, origin_y=0.5, color=color.black)

neck2_pivot = Entity(parent=neck1_pivot, position=(0, 0.58, 0))
Entity(parent=neck2_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.35, 0.05), rotation_z=90, origin_y=0.5, color=color.black)
neck2_mesh_vertical = Entity(parent=neck2_pivot, model="cube", scale=(0.25, 0.50, 0.25), color=color.orange, origin_y=-0.5)
neck2_mesh_horizontal = Entity(parent=neck2_pivot, model="cube", position=(0, 0.35, 0.175), scale=(0.25, 0.30, 0.35), color=color.orange)
neck2_mesh_vertical_up = Entity(parent=neck2_pivot, model="cube", position=(0, 0.70, 0.35), scale=(0.25, 0.40, 0.25), color=color.orange)

head_pivot = Entity(parent=neck2_pivot, position=(0, 0.90, 0.35))
Entity(parent=head_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.35, 0.05), rotation_z=90, origin_y=0.5, color=color.black)
crossbar_mesh = Entity(parent=head_pivot, model="cube", position=(0, 0, 0), scale=(0.8, 0.05, 0.05), color=color.dark_gray)

eye_left_pivot = Entity(parent=head_pivot, position=(0, 0, 0))
Entity(parent=eye_left_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.15, 0.05), rotation_x=90, origin_y=0.5, color=color.black)

eye_right_pivot = Entity(parent=head_pivot, position=(0, 0, 0))
Entity(parent=eye_right_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.15, 0.05), rotation_x=90, origin_y=0.5, color=color.black)

def create_ring_mesh(inner_radius, outer_radius, resolution=36):
    verts, tris = [], []
    for i in range(resolution):
        a1 = math.radians(i * (360/resolution))
        a2 = math.radians((i+1) * (360/resolution))
        verts.extend([
            (math.cos(a1)*inner_radius, math.sin(a1)*inner_radius, 0), (math.cos(a1)*outer_radius, math.sin(a1)*outer_radius, 0),
            (math.cos(a2)*outer_radius, math.sin(a2)*outer_radius, 0), (math.cos(a2)*inner_radius, math.sin(a2)*inner_radius, 0)
        ])
        v = i * 4
        tris.extend([(v, v+1, v+2), (v, v+2, v+3)])
    return Mesh(vertices=verts, triangles=tris)

def build_eye_housing(parent_pivot, is_left=True):
    x_dir = -1 if is_left else 1
    housing = Entity(parent=parent_pivot, position=(0, 0, -0.275))
    
    Entity(parent=housing, model=Cylinder(resolution=32), position=(x_dir * 0.475, 0, 0), scale=(0.55, 1.25, 0.55), rotation_x=90, origin_y=0.5, color=color.gray)
    Entity(parent=housing, model=Cylinder(resolution=32), position=(x_dir * 0.475, 0, -0.626), scale=(0.55, 0.005, 0.55), rotation_x=90, origin_y=0.5, color=color.white)
    Entity(parent=housing, model="cube", position=(x_dir * 0.2375, 0.1375, 0), scale=(0.475, 0.275, 1.25), color=color.gray)
    Entity(parent=housing, model="cube", position=(x_dir * 0.2375, 0.1375, -0.626), scale=(0.475, 0.275, 0.005), color=color.white)

    steps = 40
    for i in range(steps):
        t = i / (steps - 1)
        if is_left:
            edge_x = 0 - (t * 0.20)
            strip_w = edge_x - (-0.475)
            strip_x = -0.475 + (strip_w / 2)
        else:
            edge_x = 0 + (t * 0.20)
            strip_w = 0.475 - edge_x
            strip_x = 0.475 - (strip_w / 2)
            
        strip_h = 0.275 / steps
        strip_y = 0 - (i * strip_h) - (strip_h / 2)
        Entity(parent=housing, model="cube", position=(strip_x, strip_y, 0), scale=(strip_w, strip_h, 1.25), color=color.gray)
        Entity(parent=housing, model="cube", position=(strip_x, strip_y, -0.626), scale=(strip_w, strip_h, 0.005), color=color.white)

    Entity(parent=housing, model=Cylinder(resolution=32), position=(x_dir * 0.30, 0.025, -0.628), scale=(0.33, 0.01, 0.33), rotation_x=90, origin_y=0.5, color=color.dark_gray)
    pupil = Entity(parent=housing, model=Cylinder(resolution=32), position=(x_dir * 0.30, 0.025, -0.629), scale=(0.20, 0.01, 0.20), rotation_x=90, origin_y=0.5, color=color.yellow)
    top_flap = Entity(parent=housing, model="cube", position=(x_dir * 0.30, 0.20, -0.630), scale=(0.33, 0.001, 0.01), origin=(0, 0.5, 0), color=color.light_gray)
    bot_flap = Entity(parent=housing, model="cube", position=(x_dir * 0.30, -0.15, -0.630), scale=(0.33, 0.001, 0.01), origin=(0, -0.5, 0), color=color.light_gray)
    Entity(parent=housing, model=create_ring_mesh(0.160, 0.180, 36), position=(x_dir * 0.30, 0.025, -0.640), color=color.black)

    return {"pupil": pupil, "top_flap": top_flap, "bot_flap": bot_flap}

eye_left_parts = build_eye_housing(eye_left_pivot, is_left=True)
eye_right_parts = build_eye_housing(eye_right_pivot, is_left=False)

is_blinking = False
def blink_eyes():
    global is_blinking
    if is_blinking: return
    is_blinking = True
    for parts in [eye_left_parts, eye_right_parts]:
        parts["top_flap"].animate_scale_y(0.18, duration=0.1) 
        parts["bot_flap"].animate_scale_y(0.18, duration=0.1) 
        invoke(parts["top_flap"].animate_scale_y, 0.001, duration=0.1, delay=0.15)
        invoke(parts["bot_flap"].animate_scale_y, 0.001, duration=0.1, delay=0.15)
    invoke(reset_blink, delay=0.3)
def reset_blink(): global is_blinking; is_blinking = False

def get_current_pose():
    pose = {
        "yaw": head_pivot.rotation_y, "neck_base_pitch": neck1_pivot.rotation_x,
        "neck_top_pitch": neck2_pivot.rotation_x, "head_pitch": head_pivot.rotation_x,
        "left_eye": eye_left_pivot.rotation_z, "right_eye": eye_right_pivot.rotation_z
    }
    for j_name in JOINT_CONFIG:
        if j_name not in pose and j_name in anim_player.current_state:
            pose[j_name] = anim_player.current_state[j_name]
    return pose

# ---------------------------------------------------------
# ANIMATION ENGINE SETUP
# ---------------------------------------------------------
animations = []
def rescan_scripts():
    animations.clear()
    script_files = glob.glob(os.path.join(ANIMS_DIR, "*.wle")) + glob.glob(os.path.join(ANIMS_DIR, "*.txt"))
    for fname in script_files:
        with open(fname, 'r') as file:
            content = file.read()
            anim_blocks = re.finditer(r'\[Anim:\s*(.+?)\](.*?)(?=\[|$)', content, re.DOTALL | re.IGNORECASE)
            for match in anim_blocks:
                animations.append({"name": match.group(1).strip(), "script": "[Anim: " + match.group(1) + "]" + match.group(2)})

rescan_scripts()
anim_player = AnimationPlayer(JOINT_CONFIG)
anim_player.on_network_transmit = on_anim_transmit
current_anim_index = 0
if animations: anim_player.load_script(animations[0]["name"], animations[0]["script"])

# --- Terminal UI ---
terminal_bg = Entity(parent=camera.ui, model='quad', color=color.color(0, 0, 0, .85), scale=(1.2, 0.08), position=(0, -0.46))
terminal_input = InputField(parent=terminal_bg, y=0, scale=(0.95, 0.6), default_value='Type Command...', max_lines=1)
terminal_bg.enabled = False
terminal_input.enabled = False

def handle_terminal_submit():
    cmd = terminal_input.text.strip()
    terminal_input.text = ""
    terminal_bg.enabled = False
    terminal_input.enabled = False
    terminal_input.active = False 
    
    if not cmd: return
    action, data = parse_live_input(cmd, JOINT_CONFIG)
    
    if action == "TEST":
        rescan_scripts()
        found = next((a for a in animations if a["name"].lower() == data.lower()), None)
        if found:
            anim_player.load_script(found["name"], found["script"])
            anim_player.play(get_current_pose())
        else:
            push_log(f"Error: Anim '{data}' not found locally.")
    elif action == "PLAY":
        if esp32 and esp32.is_open:
            packet = bytearray([0xAA, 1])
            packet.extend(struct.pack('BBB', 116, data, 255))
            esp32.write(packet)
            push_log(f"Sent PLAY command (ID:{data}) directly to USB.")
        else:
            push_log(f"Cannot send PLAY command. USB Disabled.")
    elif action == "JOINTS":
        script_text = f"[Anim: LiveCommand]\n@0.0s {cmd}"
        anim_player.load_script("LiveCommand", script_text)
        anim_player.play(get_current_pose())
    elif action == "ERROR":
        push_log(f"Terminal Error: {data}")

terminal_input.on_submit = handle_terminal_submit

def input(key):
    global current_anim_index, usb_telemetry_enabled, last_sent_pose
    
    if key == 'enter':
        if not terminal_bg.enabled:
            terminal_bg.enabled = True
            terminal_input.enabled = True
            terminal_input.active = True
        else:
            handle_terminal_submit()
            
    if terminal_input.active: return 
    
    if key == 'space':
        if not anim_player.is_playing and animations:
            current_anim_index = (current_anim_index + 1) % len(animations)
            name = animations[current_anim_index]["name"]
            script = animations[current_anim_index]["script"]
            anim_player.load_script(name, script)
            anim_player.play(get_current_pose())
            
    if key == 'u':
        if esp32 and esp32.is_open: 
            usb_telemetry_enabled = not usb_telemetry_enabled
            push_log("Live Telemetry Stream ACTIVE" if usb_telemetry_enabled else "Live Telemetry Stream PAUSED")
            if usb_telemetry_enabled:
                pose = get_current_pose()
                targets = []
                for j_name, val in pose.items():
                    if j_name in JOINT_CONFIG:
                        targets.append({"id": JOINT_CONFIG[j_name]["id"], "target": val, "speed": 255})
                send_usb_commands(targets)
                last_sent_pose = pose.copy()
        else: 
            push_log("Cannot stream Telemetry: Connect to COM Port first.")
            
    if key == '1' or key == '2' or key == 'b': blink_eyes()

# =========================================================
# THE MASTER UPDATE LOOP
# =========================================================
def update():
    global last_sent_pose
    
    try:
        if tk_root.winfo_exists():
            tk_root.update()
        else:
            application.quit() 
    except Exception:
        pass 

    dt = min(time.dt, 0.1) 
    anim_states = anim_player.update(dt)

    if anim_player.is_playing:
        if "yaw" in anim_states and "yaw" in JOINT_CONFIG: head_pivot.rotation_y = clamp(anim_states["yaw"], JOINT_CONFIG["yaw"]["r_min"], JOINT_CONFIG["yaw"]["r_max"])
        if "neck_base_pitch" in anim_states and "neck_base_pitch" in JOINT_CONFIG: neck1_pivot.rotation_x = clamp(anim_states["neck_base_pitch"], JOINT_CONFIG["neck_base_pitch"]["r_min"], JOINT_CONFIG["neck_base_pitch"]["r_max"])
        if "neck_top_pitch" in anim_states and "neck_top_pitch" in JOINT_CONFIG: neck2_pivot.rotation_x = clamp(anim_states["neck_top_pitch"], JOINT_CONFIG["neck_top_pitch"]["r_min"], JOINT_CONFIG["neck_top_pitch"]["r_max"])
        if "head_pitch" in anim_states and "head_pitch" in JOINT_CONFIG: head_pivot.rotation_x = clamp(anim_states["head_pitch"], JOINT_CONFIG["head_pitch"]["r_min"], JOINT_CONFIG["head_pitch"]["r_max"])
        if "left_eye" in anim_states and "left_eye" in JOINT_CONFIG: eye_left_pivot.rotation_z = clamp(anim_states["left_eye"], JOINT_CONFIG["left_eye"]["r_min"], JOINT_CONFIG["left_eye"]["r_max"])
        if "right_eye" in anim_states and "right_eye" in JOINT_CONFIG: eye_right_pivot.rotation_z = clamp(anim_states["right_eye"], JOINT_CONFIG["right_eye"]["r_min"], JOINT_CONFIG["right_eye"]["r_max"])

        if "v_eyelid" in anim_states and not is_blinking:
            val = anim_states["v_eyelid"] / 100.0
            scale_val = lerp(0.001, 0.18, val)
            for parts in [eye_left_parts, eye_right_parts]:
                parts["top_flap"].scale_y = scale_val
                parts["bot_flap"].scale_y = scale_val
    else:
        if terminal_input.active: return
        y_min = JOINT_CONFIG["yaw"]["r_min"] if "yaw" in JOINT_CONFIG else -45
        y_max = JOINT_CONFIG["yaw"]["r_max"] if "yaw" in JOINT_CONFIG else 45
        if held_keys["a"]: head_pivot.rotation_y -= 1
        if held_keys["d"]: head_pivot.rotation_y += 1
        head_pivot.rotation_y = clamp(head_pivot.rotation_y, y_min, y_max)

        nb_min = JOINT_CONFIG["neck_base_pitch"]["r_min"] if "neck_base_pitch" in JOINT_CONFIG else -85
        nb_max = JOINT_CONFIG["neck_base_pitch"]["r_max"] if "neck_base_pitch" in JOINT_CONFIG else -25
        if held_keys["w"]: neck1_pivot.rotation_x -= 1
        if held_keys["s"]: neck1_pivot.rotation_x += 1
        neck1_pivot.rotation_x = clamp(neck1_pivot.rotation_x, nb_min, nb_max)

        nt_min = JOINT_CONFIG["neck_top_pitch"]["r_min"] if "neck_top_pitch" in JOINT_CONFIG else -60
        nt_max = JOINT_CONFIG["neck_top_pitch"]["r_max"] if "neck_top_pitch" in JOINT_CONFIG else 110
        if held_keys["q"]: neck2_pivot.rotation_x -= 1
        if held_keys["e"]: neck2_pivot.rotation_x += 1
        neck2_pivot.rotation_x = clamp(neck2_pivot.rotation_x, nt_min, nt_max)

        hp_min = JOINT_CONFIG["head_pitch"]["r_min"] if "head_pitch" in JOINT_CONFIG else -15
        hp_max = JOINT_CONFIG["head_pitch"]["r_max"] if "head_pitch" in JOINT_CONFIG else 100
        if held_keys["up arrow"]: head_pivot.rotation_x += 1
        if held_keys["down arrow"]: head_pivot.rotation_x -= 1
        head_pivot.rotation_x = clamp(head_pivot.rotation_x, hp_min, hp_max)

        if usb_telemetry_enabled:
            current_pose = get_current_pose()
            teleop_targets = []
            for j_name, val in current_pose.items():
                if j_name not in last_sent_pose or last_sent_pose[j_name] != val:
                    if j_name in JOINT_CONFIG:
                        teleop_targets.append({"id": JOINT_CONFIG[j_name]["id"], "target": val, "speed": 255})
            if teleop_targets:
                send_usb_commands(teleop_targets)
                last_sent_pose = current_pose.copy()

    pose = get_current_pose()
    if "yaw" in tk_pos_labels: tk_pos_labels["yaw"].config(text=f"{pose.get('yaw', 0.0):.1f}")
    if "neck_base_pitch" in tk_pos_labels: tk_pos_labels["neck_base_pitch"].config(text=f"{pose.get('neck_base_pitch', 0.0):.1f}")
    if "neck_top_pitch" in tk_pos_labels: tk_pos_labels["neck_top_pitch"].config(text=f"{pose.get('neck_top_pitch', 0.0):.1f}")
    if "head_pitch" in tk_pos_labels: tk_pos_labels["head_pitch"].config(text=f"{pose.get('head_pitch', 0.0):.1f}")
    if "left_eye" in tk_pos_labels: tk_pos_labels["left_eye"].config(text=f"{pose.get('left_eye', 0.0):.1f}")
    if "right_eye" in tk_pos_labels: tk_pos_labels["right_eye"].config(text=f"{pose.get('right_eye', 0.0):.1f}")
    
    for j_name in pose:
        if j_name not in ["yaw", "neck_base_pitch", "neck_top_pitch", "head_pitch", "left_eye", "right_eye"]:
            if j_name in tk_pos_labels:
                tk_pos_labels[j_name].config(text=f"{pose[j_name]:.1f}")

    conn_status = "CONNECTED" if (esp32 and esp32.is_open) else "DISCONNECTED"
    stream_status = "ACTIVE (u to pause)" if usb_telemetry_enabled else "PAUSED (u to start)"
    term_status = "\n--- TERMINAL MODE ACTIVE ---\nType command and press ENTER to submit." if terminal_input.active else ""
    servo_display.text = (
        f"--- WLE5 SIMULATOR ---\n"
        f"USB Port: {conn_status}\n"
        f"Live Telemetry: {stream_status}\n\n"
        f"Control the 3D model using the Tkinter\nControl Panel or keyboard (WASD/Arrows).{term_status}"
    )

app.run()