# Last Updated: 2026-08-09
import os
import time
import struct
import zlib
import glob
import re
from tkinter import messagebox

def wait_for_esp_ack(esp32, tk_root, timeout=1.0):
    start_t = time.time()
    while time.time() - start_t < timeout:
        tk_root.update()
        if esp32 and esp32.in_waiting > 0:
            char = esp32.read(1)
            if char == b'\x01': 
                return True
        time.sleep(0.01)
    return False

def send_file_to_psram(esp32, file_type, file_data, target_filename, tk_root):
    """ Universally streams a file to the ESP32's PSRAM cache using a single high-speed blast """
    file_size = len(file_data)
    checksum = zlib.crc32(file_data) & 0xFFFFFFFF
    
    # FIX: Expanded filename buffer to 64 bytes to match ESP32 upgrade
    name_bytes = target_filename.encode('utf-8')[:63].ljust(64, b'\x00')
    
    # Send Handshake with 3-Byte 'WLE' Preamble
    handshake = bytearray([0x57, 0x4C, 0x45, 0x02, file_type]) + struct.pack('<I I', file_size, checksum) + name_bytes
    
    if hasattr(esp32, 'reset_input_buffer'):
        esp32.reset_input_buffer()
        
    esp32.write(handshake)
    
    # Wait for ESP32 to allocate PSRAM
    if not wait_for_esp_ack(esp32, tk_root, timeout=3.0):
        return False

    # Blast the raw data. ESP32 is trapped in a blocking read loop to catch it all.
    esp32.write(file_data)
    
    # Wait for ESP32 to verify CRC and save from PSRAM to Flash
    return wait_for_esp_ack(esp32, tk_root, timeout=10.0)


def run_smart_sync(esp32, tk_root, push_log, animations, anim_player, JOINT_CONFIG, CONFIG_DIR, ANIMS_DIR, rescan_callback):
    if not esp32 or not getattr(esp32, 'is_open', False): 
        messagebox.showwarning("Not Connected", "Please connect to the ESP32 COM port or IP address first.")
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
    
    if hasattr(esp32, 'reset_input_buffer'):
        esp32.reset_input_buffer()
        
    # SECURE ROUTE: 'WLE' Preamble + 0xBB Config Query
    esp32.write(bytearray([0x57, 0x4C, 0x45, 0xBB, 0x01]))
    
    start_t = time.time()
    esp_cfg_version = None
    buf = bytearray()
    while time.time() - start_t < 1.0:
        tk_root.update()
        if esp32.in_waiting > 0:
            chunk = esp32.read(4 - len(buf))
            if chunk:
                buf.extend(chunk)
        if len(buf) >= 4:
            esp_cfg_version = struct.unpack('<I', buf[:4])[0]
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
        if send_file_to_psram(esp32, 0, cfg_data, "config.bin", tk_root):
            sync_results.append(f"Hardware Config: Updated to v{local_cfg_version}")
        else:
            sync_results.append("Hardware Config: FAILED (Transfer or CRC Error)")

    # === 2. COMPILE & SYNC ANIMATIONS ===
    script_files = glob.glob(os.path.join(ANIMS_DIR, "*.wle")) + glob.glob(os.path.join(ANIMS_DIR, "*.txt"))
    combined_text = ""
    for fname in script_files:
        with open(fname, 'r') as file:
            combined_text += file.read() + "\n"
            
    anim_hash = zlib.crc32(combined_text.encode('utf-8')) & 0xFFFFFFFF
    
    push_log(f"Checking Anim Hash (Local: {anim_hash})...")
    if hasattr(esp32, 'reset_input_buffer'):
        esp32.reset_input_buffer()
        
    # SECURE ROUTE: 'WLE' Preamble + 0xCC Anim Query
    esp32.write(bytearray([0x57, 0x4C, 0x45, 0xCC, 0x01]))
    
    start_t = time.time()
    esp_anim_hash = None
    buf = bytearray()
    while time.time() - start_t < 1.0:
        tk_root.update()
        if esp32.in_waiting > 0:
            chunk = esp32.read(4 - len(buf))
            if chunk:
                buf.extend(chunk)
        if len(buf) >= 4:
            esp_anim_hash = struct.unpack('<I', buf[:4])[0]
            break
        time.sleep(0.01)

    do_anim_sync = False
    if esp_anim_hash is None:
        do_anim_sync = messagebox.askyesno("Timeout", "ESP32 did not respond to Anim Hash query.\n\nForce script compile and upload anyway?")
    elif esp_anim_hash == anim_hash:
        sync_results.append("Scripts & Idle States: Skipped (No text changes detected)")
    else:
        push_log("ESP32 Scripts are outdated. Compiling and Uploading...")
        do_anim_sync = True

    if do_anim_sync:
        rescan_callback()
        bin_data = bytearray(b'WLEA')
        bin_data.extend(struct.pack('<I', anim_hash))
        bin_data.append(len(animations))
        
        for anim in animations:
            # Struct alignment internally is still 32 bytes for the C++ parser
            name_bytes = anim["name"].encode('utf-8')[:31].ljust(32, b'\x00')
            anim_player.load_script(anim["name"], anim["script"])
            kf_count = len(anim_player.keyframes)
            bin_data.extend(name_bytes)
            bin_data.extend(struct.pack('<H', kf_count))
            
            for kf in anim_player.keyframes:
                time_val = int(kf["time"] * 10) & 0xFFFF
                cmd_count = len(kf["targets"])
                bin_data.extend(struct.pack('<H B', time_val, cmd_count))
                
                for j_name, cmd in kf["targets"].items():
                    cfg = JOINT_CONFIG[j_name]
                    clamped = max(cfg["r_min"], min(cfg["r_max"], cmd["target"]))
                    norm = (clamped - cfg["r_min"]) / (abs(cfg["r_max"] - cfg["r_min"]) or 1)
                    byte_val = int(norm * 255)
                    bin_data.extend(struct.pack('<B B B', cfg["id"], byte_val, cmd["speed"]))
        
        anim_bin_path = os.path.join(CONFIG_DIR, "anims.bin")
        with open(anim_bin_path, "wb") as f:
            f.write(bin_data)
            
        if send_file_to_psram(esp32, 2, bin_data, "anims.bin", tk_root):
            sync_results.append("Animations (anims.bin): Compiled & Transferred")
        else:
            sync_results.append("Animations: FAILED (Transfer or CRC Error)")

    # === 3. COMPILE & SYNC IDLE STATES ===
    if do_anim_sync:
        idle_timeout = 5.0
        cfg_match = re.search(r'\[Config\]\s*IdleTimeout\s*=\s*([\d\.]+)', combined_text, re.IGNORECASE)
        if cfg_match: idle_timeout = float(cfg_match.group(1))

        state_blocks = re.finditer(r'\[State:\s*(.+?)\]\s*Interval\s*=\s*([\d\.]+)\s*-\s*([\d\.]+)(.*?)(?=\[State:|$)', combined_text, re.DOTALL | re.IGNORECASE)

        states_data = []
        state_counter = 1 

        for match in state_blocks:
            state_label = match.group(1).strip()
            s_min = float(match.group(2))
            s_max = float(match.group(3))
            state_content = match.group(4)
            
            play_matches = re.findall(r'Play:\s*(\w+)(?:\s+w:(\d+))?(?:\s+v:(\d+))?(?:\s+c:(\d+))?', state_content, re.IGNORECASE)
            
            play_commands = []
            for p_match in play_matches:
                anim_name = p_match[0]
                w = int(p_match[1]) if p_match[1] else 100 
                v = int(p_match[2]) if p_match[2] else 10   
                c = int(p_match[3]) if p_match[3] else 5    
                play_commands.append((anim_name, w, v, c))
                
            if play_commands:
                states_data.append({
                    "id": state_counter,
                    "min": s_min,
                    "max": s_max,
                    "plays": play_commands
                })
                state_counter += 1

        if not states_data:
            int_min, int_max = 2.0, 5.0
            state_match = re.search(r'\[State:.*?\]\s*Interval\s*=\s*([\d\.]+)\s*-\s*([\d\.]+)', combined_text, re.IGNORECASE)
            if state_match:
                int_min = float(state_match.group(1))
                int_max = float(state_match.group(2))
                
            play_matches = re.findall(r'Play:\s*(\w+)(?:\s+w:(\d+))?(?:\s+v:(\d+))?(?:\s+c:(\d+))?', combined_text, re.IGNORECASE)
            play_commands = []
            for p_match in play_matches:
                anim_name = p_match[0]
                w = int(p_match[1]) if p_match[1] else 100
                v = int(p_match[2]) if p_match[2] else 10
                c = int(p_match[3]) if p_match[3] else 5
                play_commands.append((anim_name, w, v, c))
                
            if play_commands:
                states_data.append({"id": 1, "min": int_min, "max": int_max, "plays": play_commands})

        state_bin = bytearray(b'WLES')
        state_bin.extend(struct.pack('<f B', idle_timeout, len(states_data)))

        for state in states_data:
            num_actions = len(state["plays"])
            state_bin.extend(struct.pack('<B f f B', state["id"], state["min"], state["max"], num_actions))
            
            for anim_name, w, v, c in state["plays"]:
                # Struct alignment internally is still 32 bytes for the C++ parser
                name_bytes = anim_name.encode('utf-8')[:31].ljust(32, b'\x00')
                state_bin.extend(name_bytes)
                state_bin.extend(struct.pack('<B B H', int(w), int(v), int(c)))

        state_bin_path = os.path.join(CONFIG_DIR, "states.bin")
        with open(state_bin_path, "wb") as f:
            f.write(state_bin)

        if send_file_to_psram(esp32, 1, state_bin, "states.bin", tk_root):
            sync_results.append("Idle States (states.bin): Compiled & Transferred")
        else:
            sync_results.append("Idle States: FAILED (Transfer or CRC Error)")

    messagebox.showinfo("Smart Sync Complete", "\n".join(sync_results))
    push_log("Sync Process Completed.")
# --- END OF FILE ---