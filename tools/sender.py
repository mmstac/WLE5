import sys
import serial
import time
import struct
import re
import wle_config

def parse_live_input(cmd_str, joint_config):
    """
    Shared parser used by both main_ide.py and the standalone sender.
    Returns (ActionType, Data)
    """
    cmd = cmd_str.strip()
    if not cmd: return "NONE", ""
    
    parts = cmd.split()
    first = parts[0].upper()

    if first == "TEST" and len(parts) > 1:
        return "TEST", " ".join(parts[1:])
    elif first == "PLAY" and len(parts) > 1:
        if parts[1].isdigit():
            return "PLAY", int(parts[1])
        else:
            return "ERROR", "PLAY requires a numeric ID (e.g., PLAY 1)"
    elif first in ["HELP", "?"]:
        return "HELP", ""
    elif first == "TOC":
        return "TOC", ""
    else:
        # Default assumption: It's a joint command (e.g., yaw=45,255)
        return "JOINTS", cmd


# =========================================================
# STANDALONE CLI MODE
# Runs only if you execute this script directly!
# =========================================================
if __name__ == '__main__':
    print("==================================================")
    print("      WLE5 Standalone Telemetry Sender            ")
    print("==================================================")
    
    # 1. Load Dynamic Limits
    version, JOINT_CONFIG = wle_config.load_master_config()
    print(f"Loaded Configuration v{version} ({len(JOINT_CONFIG)} joints known).")
    
    # 2. Connect to Hardware
    port = input("Enter COM Port [COM9]: ").strip().upper()
    if not port: port = "COM9"
    
    try:
        esp32 = serial.Serial(port, 115200, timeout=0)
        print(f"--> SUCCESS: Connected to {port}\n")
    except Exception as e:
        print(f"--> ERROR: Failed to connect to {port}.\nDetails: {e}")
        sys.exit(1)

    print("Type 'HELP' for a list of commands.")
    print("-" * 50)

    # 3. Interactive Loop
    while True:
        try:
            cmd = input("WLE5> ")
        except (KeyboardInterrupt, EOFError):
            break
            
        if cmd.lower() in ['exit', 'quit']:
            break
            
        action, data = parse_live_input(cmd, JOINT_CONFIG)

        if action == "HELP":
            print("\n--- WLE5 COMMAND MENU ---")
            print("  <joint>=<tgt>,<spd> : Jog a joint (e.g., yaw=45,255 head_pitch=-10)")
            print("                        (You can chain multiple: yaw=0 left_eye=20,100)")
            print("  PLAY <id>           : Trigger an animation stored on the ESP32 (e.g., PLAY 1)")
            print("  TOC                 : View Table of Contents (Lists all joints & limits)")
            print("  EXIT / QUIT         : Close the connection")
            print("-------------------------\n")

        elif action == "TOC":
            print("\n--- TABLE OF CONTENTS (Configured Joints) ---")
            print(f"  {'ID':<4} | {'NAME':<18} | {'MIN':<7} | {'MAX':<7}")
            print("  " + "-"*45)
            for name, cfg in sorted(JOINT_CONFIG.items(), key=lambda x: x[1]['id']):
                # Only show active/valid IDs
                if cfg['id'] >= 0:
                    print(f"  {cfg['id']:<4} | {name:<18} | {cfg['r_min']:<7.1f} | {cfg['r_max']:<7.1f}")
            print("---------------------------------------------\n")

        elif action == "JOINTS":
            targets = []
            # Extract pattern: name=target,speed (speed is optional)
            matches = re.findall(r'(\w+)=(-?\d+\.?\d*)(?:,(\d+))?', data)
            
            if not matches:
                print("  -> No valid joint commands found. Type 'HELP' for syntax.")
                continue

            for j_name, tgt_str, spd_str in matches:
                if j_name in JOINT_CONFIG:
                    cfg = JOINT_CONFIG[j_name]
                    tgt = float(tgt_str)
                    spd = int(spd_str) if spd_str else cfg.get("def_spd", 255)

                    # Mathematical Clamping & Normalization
                    clamped = max(cfg["r_min"], min(cfg["r_max"], tgt))
                    r_range = abs(cfg["r_max"] - cfg["r_min"]) or 1
                    norm = (clamped - cfg["r_min"]) / r_range
                    byte_val = int(norm * 255)

                    targets.append({"id": cfg["id"], "set": byte_val, "spd": spd})
                else:
                    print(f"  [Warning] Unknown joint: '{j_name}'. Type 'TOC' to see valid names.")

            # Pack and send the 0xAA stream over USB
            if targets:
                packet = bytearray([0xAA, len(targets)])
                for t in targets[:16]: # Max 16 per packet
                    packet.extend(struct.pack('BBB', t["id"], t["set"], t["spd"]))
                
                esp32.write(packet)
                print(f"  -> Streamed {len(targets)} joint updates to ESP32.")

        elif action == "PLAY":
            # Dynamically fetch the ID for v_play_anim (116) so it never mismatches!
            play_id = JOINT_CONFIG.get("v_play_anim", {}).get("id", 116)
            packet = bytearray([0xAA, 1])
            packet.extend(struct.pack('BBB', play_id, data, 255))
            esp32.write(packet)
            print(f"  -> Sent playback trigger for Animation ID: {data}")

        elif action == "ERROR":
            print(f"  -> Syntax Error: {data}")

    if esp32 and esp32.is_open:
        esp32.close()
    print("Connection closed. Goodbye!")