# Last Updated: 2026-08-10
import serial
import socket
import struct
import select
import time
from tkinter import messagebox

class TCPLink:
    """ Fakes a serial.Serial object by wrapping a standard TCP Socket. """
    def __init__(self, ip, port=4210, timeout=0.1):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) 
        self.sock.settimeout(3.0) 
        self.sock.connect((ip, port))
        self.sock.settimeout(timeout) 
        self.timeout = timeout

    @property
    def is_open(self):
        return True

    def write(self, data):
        try:
            self.sock.sendall(data)
            return True # --- FIX: Report success
        except Exception:
            return False # --- FIX: Instantly report broken pipe!

    @property
    def in_waiting(self):
        try:
            r, _, _ = select.select([self.sock], [], [], 0.0)
            return 1024 if r else 0
        except Exception:
            return 0 

    def read(self, size=1):
        data = bytearray()
        start = time.time()
        try:
            while len(data) < size and (time.time() - start) < self.timeout:
                chunk = self.sock.recv(size - len(data))
                if not chunk: break
                data.extend(chunk)
        except (socket.timeout, BlockingIOError):
            pass
        except Exception:
            pass
        return bytes(data)

    def reset_input_buffer(self):
        try:
            r, _, _ = select.select([self.sock], [], [], 0.0)
            if r:
                self.sock.recv(4096)
        except Exception:
            pass

    def reset_output_buffer(self):
        pass

    def close(self):
        # --- FIX: Removed shutdown() and SO_LINGER to prevent Windows UI freezes!
        try:
            self.sock.close()
        except Exception:
            pass


class CommManager:
    def __init__(self, joint_config, id_to_name):
        self.JOINT_CONFIG = joint_config
        self.ID_TO_NAME = id_to_name
        
        self.mode = "NONE" 
        self.active_link = None
        self.telemetry_enabled = False
        self.buffer = bytearray()
        self.last_rx_time = 0 

    def is_connected(self):
        return self.mode != "NONE"

    def toggle_connection(self, target_str, push_log_callback, conn_btn):
        if self.is_connected():
            self.close()
            self.telemetry_enabled = False
            conn_btn.config(text="Connect", bg="#4CAF50")
            push_log_callback("Link Disconnected.")
            return False
        else:
            target = target_str.strip()
            if "." in target: 
                try:
                    self.active_link = TCPLink(target, port=4210)
                    self.mode = "TCP"
                    self.buffer.clear()
                    self.telemetry_enabled = False 
                    self.last_rx_time = time.time() 
                    
                    conn_btn.config(text="Disconnect", bg="#f44336")
                    push_log_callback(f"TCP Wi-Fi Link established to {target}:4210")
                    return True
                except Exception as e:
                    messagebox.showerror("TCP Error", f"Could not connect to {target}.\nEnsure the robot is on and connected to Wi-Fi.\nDetails: {e}")
                    return False
            else: 
                try:
                    self.active_link = serial.Serial(target, 115200, timeout=0.1)
                    self.mode = "SERIAL"
                    self.buffer.clear()
                    self.telemetry_enabled = False 
                    self.last_rx_time = time.time()
                    
                    conn_btn.config(text="Disconnect", bg="#f44336")
                    push_log_callback(f"USB Connected to {target}.")
                    return True
                except Exception as e:
                    messagebox.showerror("Port Error", f"Could not open {target}.\nEnsure Arduino Serial Monitor is CLOSED.\nDetails: {e}")
                    return False

    def toggle_telemetry(self, push_log_callback):
        if self.is_connected():
            self.telemetry_enabled = not self.telemetry_enabled
            
            if self.telemetry_enabled:
                # --- FIX: Reset watchdog ONLY when activating LIVE so it survives the first click
                self.last_rx_time = time.time() 
                
            status = "ACTIVE" if self.telemetry_enabled else "PAUSED"
            push_log_callback(f"Live Telemetry Stream {status}")
            return self.telemetry_enabled
        else:
            push_log_callback("Cannot stream Telemetry: Connect Link first.")
            return False

    def _write_data(self, packet):
        if self.active_link:
            try:
                # If write fails (ESP32 is dead), kill the connection instantly!
                result = self.active_link.write(packet)
                if result is False: 
                    self.close()
                else:
                    # FIX: Feed the WDT on successful OS-level transmission!
                    self.last_rx_time = time.time()
            except Exception:
                self.close()
            
    def send_packets(self, packets):
        if not self.is_connected() or not self.telemetry_enabled or not packets: 
            return

        commands = []
        for p in packets:
            j_id = p["id"]
            j_name = self.ID_TO_NAME.get(j_id)
            if not j_name: continue
            
            cfg = self.JOINT_CONFIG[j_name]
            clamped = max(cfg["r_min"], min(cfg["r_max"], p["target"]))
            norm = (clamped - cfg["r_min"]) / (abs(cfg["r_max"] - cfg["r_min"]) or 1)
            byte_val = int(norm * 255)
            
            commands.append(struct.pack('BBB', j_id, byte_val, p["speed"]))
            
        if commands:
            for i in range(0, len(commands), 16):
                chunk = commands[i:i+16]
                packet = bytearray([0xAA, len(chunk)])
                for cmd_bytes in chunk: 
                    packet.extend(cmd_bytes)
                self._write_data(packet)

    def send_play_command(self, anim_id, push_log_callback):
        if self.is_connected():
            packet = bytearray([0xAA, 1])
            packet.extend(struct.pack('BBB', 116, anim_id, 255))
            self._write_data(packet)
            push_log_callback(f"Sent PLAY command (ID:{anim_id}) to robot.")
        else:
            push_log_callback("Cannot send PLAY command. Link Disabled.")
            
    def send_wifi_config(self, ssid, password, push_log_callback):
        if self.is_connected():
            ssid_bytes = ssid.encode('utf-8')
            pass_bytes = password.encode('utf-8')
            
            packet = bytearray([0x57, 0x4C, 0x45, 0xFF, 0x01, len(ssid_bytes), len(pass_bytes)])
            packet.extend(ssid_bytes)
            packet.extend(pass_bytes)
            
            self._write_data(packet)
            push_log_callback("Sent Wi-Fi Credentials. ESP32 Rebooting...")
        else:
            push_log_callback("Error: Must be connected to sync Wi-Fi.")

    def read_telemetry(self):
        if not self.is_connected(): return None 
        
        # --- FIX: Reverted to 30s. Only monitors INCOMING heartbeats.
        if time.time() - self.last_rx_time > 30.0:
            self.close()
            return None
            
        stats = None
        try:
            if self.active_link.in_waiting > 0:
                data = self.active_link.read(512)
                if data:
                    self.last_rx_time = time.time() 
                    self.buffer.extend(data)
                
                while len(self.buffer) >= 17:
                    if self.buffer[0:4] == b'WLE\xAA':
                        payload = self.buffer[4:17]
                        phys, gfx, sram, psram, rssi = struct.unpack('<HHIIb', payload)
                        stats = {
                            "phys_hz": phys,
                            "gfx_fps": gfx,
                            "sram": sram,
                            "psram": psram,
                            "rssi": rssi
                        }
                        self.buffer = self.buffer[17:]
                    else:
                        self.buffer.pop(0)
        except Exception:
            pass
            
        return stats

    def close(self):
        if self.active_link:
            try:
                self.active_link.close()
            except Exception:
                pass
        self.mode = "NONE"
        self.active_link = None
        self.telemetry_enabled = False
# --- END OF FILE ---