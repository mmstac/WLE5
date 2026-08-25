# Last Updated: 2026-08-09
import os
import sys
import serial
import time
import struct
import zlib
import socket
import select
import tkinter as tk
from tkinter import ttk, messagebox

# --- CONFIGURATION ---
BAUD_RATE = 115200
ACK_BYTE = b'\x01'

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL_AUDIO_DIR = os.path.join(BASE_DIR, "media", "optimized_audio")
LOCAL_IMG_DIR = os.path.join(BASE_DIR, "media", "optimized_img")

# --- WI-FI TCP WRAPPER ---
class TCPLink:
    def __init__(self, ip, port=4210, timeout=0.1):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(3.0) 
        self.sock.connect((ip, port))
        self.sock.settimeout(timeout) 
        self.timeout = timeout

    @property
    def is_open(self): return True

    def write(self, data):
        try: self.sock.sendall(data)
        except Exception: pass

    @property
    def in_waiting(self):
        r, _, _ = select.select([self.sock], [], [], 0.0)
        return 1024 if r else 0

    def read(self, size=1):
        data = bytearray()
        start = time.time()
        try:
            while len(data) < size and (time.time() - start) < self.timeout:
                chunk = self.sock.recv(size - len(data))
                if not chunk: break
                data.extend(chunk)
        except Exception: pass
        return bytes(data)

    def reset_input_buffer(self):
        try:
            r, _, _ = select.select([self.sock], [], [], 0.0)
            if r: self.sock.recv(4096)
        except Exception: pass

    def close(self):
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception: pass
        self.sock.close()

def wait_for_ack(ser, timeout=2.0, root=None):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if root: root.update()
        if ser.in_waiting > 0:
            if ser.read(1) == ACK_BYTE:
                return True
        time.sleep(0.01)
    return False

def send_file_to_psram(ser, file_type, file_data, target_path, mprint, root, progress_var):
    file_size = len(file_data)
    checksum = zlib.crc32(file_data) & 0xFFFFFFFF
    
    # FIX: Expanded filename buffer to 64 bytes to match ESP32 upgrade
    name_bytes = target_path.encode('utf-8')[:63].ljust(64, b'\x00')
    
    # 3-Byte 'WLE' Preamble + 0x02 Handshake
    handshake = bytearray([0x57, 0x4C, 0x45, 0x02, file_type]) + struct.pack('<I I', file_size, checksum) + name_bytes
    
    if hasattr(ser, 'reset_input_buffer'):
        ser.reset_input_buffer()
        
    ser.write(handshake)
    
    if not wait_for_ack(ser, timeout=3.0, root=root):
        mprint("  -> FAILED: Robot denied PSRAM allocation.")
        return False
        
    mprint("  -> Syncing to buffer...")
    ser.write(file_data)
    
    # High capacity wait period for Flash Drive to finish committing
    if wait_for_ack(ser, timeout=15.0, root=root):
        progress_var.set(100)
        root.update()
        return True
    
    return False


def sync_media(port_str):
    root = tk.Tk()
    root.title(f"WLE5 Media Sync -> {port_str}")
    root.geometry("600x450")
    root.configure(bg="#1e1e1e")
    root.attributes('-topmost', True)
    
    log_text = tk.Text(root, bg="#1e1e1e", fg="#4CAF50", font=("Consolas", 10), borderwidth=0)
    log_text.pack(expand=True, fill=tk.BOTH, padx=15, pady=(15, 5))
    
    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(root, variable=progress_var, maximum=100)
    progress_bar.pack(fill=tk.X, padx=15, pady=(0, 15))
    
    def mprint(msg):
        log_text.insert(tk.END, str(msg) + "\n")
        log_text.see(tk.END)
        root.update()

    mprint("==================================================")
    mprint("          WLE5 Media Sync Utility                 ")
    mprint("==================================================")
    
    ser = None
    
    try:
        if "." in port_str:
            mprint(f"Connecting to Wi-Fi TCP {port_str}:4210...")
            ser = TCPLink(port_str, port=4210)
        else:
            mprint(f"Connecting to USB {port_str}...")
            ser = serial.Serial(port_str, BAUD_RATE, timeout=1)
            time.sleep(2) 
            
        mprint("-> Connected!")
        time.sleep(0.5)
        
        if hasattr(ser, 'reset_input_buffer'):
            ser.reset_input_buffer()

        mprint("Requesting manifest from robot...")
        # SECURE ROUTE: 'WLE' Preamble + 0xEE Manifest Request
        ser.write(b'\x57\x4C\x45\xEE\x01')
        
        esp_files = {}
        
        start_time = time.time()
        buf = ""
        while time.time() - start_time < 5.0:
            root.update()
            if ser.in_waiting > 0:
                chunk = ser.read(1024).decode('utf-8', errors='ignore')
                buf += chunk
                if "END_OF_MANIFEST" in buf:
                    break
            time.sleep(0.01)

        lines = buf.split('\n')
        for line in lines:
            line = line.strip()
            if line and ":" in line and not line.startswith("END_OF"):
                parts = line.split(":")
                esp_files[parts[0]] = int(parts[1])

        mprint(f"Robot currently holds {len(esp_files)} media files.")

        local_files = {}
        
        if os.path.exists(LOCAL_AUDIO_DIR):
            for f in os.listdir(LOCAL_AUDIO_DIR):
                if f.endswith('.mp3') or f.endswith('.wav'):
                    target_path = f"/audio/{f}"
                    local_path = os.path.join(LOCAL_AUDIO_DIR, f)
                    local_files[target_path] = (local_path, os.path.getsize(local_path))
                    
        if os.path.exists(LOCAL_IMG_DIR):
            for f in os.listdir(LOCAL_IMG_DIR):
                if f.endswith('.bin'):
                    target_path = f"/img/{f}"
                    local_path = os.path.join(LOCAL_IMG_DIR, f)
                    local_files[target_path] = (local_path, os.path.getsize(local_path))

        to_delete = [p for p in esp_files.keys() if p not in local_files]
        to_upload = []
        
        for target_path, (local_path, local_size) in local_files.items():
            if target_path not in esp_files:
                to_upload.append(target_path)
            elif esp_files[target_path] != local_size:
                mprint(f"Size mismatch for {target_path} (Robot: {esp_files[target_path]}b, Local: {local_size}b). Flagged for update.")
                to_upload.append(target_path)

        mprint(f"Delta Calculation Complete: {len(to_delete)} files to delete, {len(to_upload)} files to upload.")

        # 5. EXECUTE DELETIONS
        for path in to_delete:
            mprint(f"Deleting {path}...")
            path_bytes = path.encode('utf-8')
            ser.write(b'\x57\x4C\x45\xEE\x05' + bytes([len(path_bytes)]) + path_bytes)
            if not wait_for_ack(ser, root=root):
                mprint(f"Failed to delete {path}")

        # 6. EXECUTE UPLOADS (Unified PSRAM Protocol)
        for target_path in to_upload:
            local_path, local_size = local_files[target_path]
            mprint(f"Uploading {target_path} ({local_size} bytes)...")
            
            with open(local_path, "rb") as f:
                file_data = f.read()

            file_type = 4 if target_path.startswith("/audio") else 3
            progress_var.set(10)
            root.update()

            if send_file_to_psram(ser, file_type, file_data, target_path, mprint, root, progress_var):
                mprint("  -> SUCCESS!")
            else:
                mprint("  -> CRC ERROR or TIMEOUT!")

        # 7. TRIGGER RELOAD
        mprint("\nSync complete. Instructing robot to reload memory...")
        ser.write(b'\x57\x4C\x45\xEE\x06')
        if wait_for_ack(ser, timeout=4.0, root=root):
            mprint("Robot reloaded successfully. Ready to animate.")
        else:
            mprint("Warning: Robot did not acknowledge reload command. A hardware reboot may be required.")

        mprint("\n--- ALL DONE ---")
        mprint("You may now close this window.")
        
        root.attributes('-topmost', False)
        root.mainloop()

    except Exception as e:
        mprint(f"\nCritical Error: {e}")
    finally:
        if ser:
            ser.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="WLE5 Media Sync")
    parser.add_argument("target", nargs="?", default="", help="COM Port or IP Address")
    parser.add_argument("--root", help="Absolute path to the project root directory")
    args = parser.parse_args()

    if args.root:
        base_dir = args.root
    else:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        
    LOCAL_AUDIO_DIR = os.path.join(base_dir, "media", "optimized_audio")
    LOCAL_IMG_DIR = os.path.join(base_dir, "media", "optimized_img")
    
    target = args.target if args.target else ""
    if not target:
        try:
            if sys.stdin and sys.stdin.isatty():
                target = input("Enter COM Port or IP Address: ").strip()
        except Exception:
            pass
    
    globals()['LOCAL_AUDIO_DIR'] = LOCAL_AUDIO_DIR
    globals()['LOCAL_IMG_DIR'] = LOCAL_IMG_DIR
    
    sync_media(target)
    
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to exit...")
    except Exception:
        pass
# --- END OF FILE ---