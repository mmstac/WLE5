# Last Updated: 2026-08-11
import os
import sys
import struct
import subprocess
import argparse
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image

# --- THE ZOMBIE KILLER ---
if sys.platform == "win32":
    os.system("taskkill /f /im ffmpeg.exe >nul 2>&1")

# --- WINDOWS POPUP SUPPRESSION FLAG ---
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

def get_next_index(directory):
    if not os.path.exists(directory):
        return 1
    
    highest = 0
    for f in os.listdir(directory):
        parts = f.split("_")
        if len(parts) > 1 and parts[0].isdigit():
            idx = int(parts[0])
            if idx > highest:
                highest = idx
    return highest + 1

# ==========================================
# AUDIO PROCESSING (FFMPEG)
# ==========================================
def check_ffmpeg():
    try:
        subprocess.run(
            ["ffmpeg", "-version"], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, 
            creationflags=CREATE_NO_WINDOW
        )
        return True
    except FileNotFoundError:
        return False

# --- NEW: Helper function to determine audio duration ---
def get_audio_duration(file_path):
    try:
        command = [
            "ffprobe", "-v", "error", 
            "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", 
            file_path
        ]
        result = subprocess.run(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.DEVNULL, 
            text=True, 
            creationflags=CREATE_NO_WINDOW
        )
        return float(result.stdout.strip())
    except (ValueError, subprocess.CalledProcessError):
        return 0.0 # Fallback in case of a read error

# --- UPDATED: 3-Tier Audio Processing with dynamic VBR Quality ---
def process_audio(file_paths, project_root, status_callback, vbr_quality="4"):
    if not check_ffmpeg():
        messagebox.showerror("Error", "FFmpeg is not installed or not in your system PATH.")
        status_callback("")
        return

    out_dir = os.path.join(project_root, "media", "optimized_audio")
    os.makedirs(out_dir, exist_ok=True)
    
    start_idx = get_next_index(out_dir)
    success_count = 0
    total_files = len(file_paths)
    
    for i, input_path in enumerate(file_paths, start=start_idx):
        filename = os.path.basename(input_path)
        base_name = os.path.splitext(filename)[0]
        
        # Clamp filename length to 45 characters to avoid ESP32 buffer overflow
        safe_base = base_name[:45]
        output_filename = f"{i:03d}_{safe_base}.mp3"
        output_path = os.path.join(out_dir, output_filename)
        
        status_callback(f"Optimizing Audio: {i - start_idx + 1} of {total_files}\n({filename})")
        
        # Determine duration dynamically to apply the 3-Tier logic
        duration = get_audio_duration(input_path)
        
        if duration < 1.0:  
            # TIER 1: < 1 second -> 24kHz VBR + 0.5s Padding
            command = [
                "ffmpeg", "-y", 
                "-i", input_path, 
                "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=24000:cl=mono", 
                "-filter_complex", "[0:a]aresample=24000,aformat=channel_layouts=mono[a1];[a1][1:a]concat=n=2:v=0:a=1[out]", 
                "-map", "[out]", 
                "-codec:a", "libmp3lame", 
                "-q:a", vbr_quality, 
                output_path
            ]
        elif duration < 11.0: 
            # TIER 2: 1s to 11s -> 24kHz VBR (Maximum ESP32 efficiency)
            command = [
                "ffmpeg", "-y", 
                "-i", input_path, 
                "-ar", "24000", 
                "-ac", "1", 
                "-codec:a", "libmp3lame", 
                "-q:a", vbr_quality, 
                output_path
            ]
        else:               
            # TIER 3: >= 11 seconds -> 44.1kHz VBR (Bypasses MPEG-2 LSF wrap-around bug)
            command = [
                "ffmpeg", "-y", 
                "-i", input_path, 
                "-ar", "44100", 
                "-ac", "1", 
                "-codec:a", "libmp3lame", 
                "-q:a", vbr_quality, 
                output_path
            ]
        
        try:
            subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                check=True,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
                timeout=15
            )
            success_count += 1
            
        except subprocess.TimeoutExpired:
            messagebox.showerror("Timeout Error", f"FFmpeg hung on {filename} and was terminated.")
            if sys.platform == "win32":
                os.system("taskkill /f /im ffmpeg.exe >nul 2>&1")
            break
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else "Unknown FFmpeg error."
            messagebox.showerror("FFmpeg Error", f"Failed to convert {filename}.\n\nFFmpeg Output:\n{error_msg[-500:]}")
            break 
            
    if success_count > 0:
        messagebox.showinfo("Success", f"Added {success_count} MP3 files to:\n{out_dir}\n\nContinuing from Index: {start_idx:03d}")
    status_callback("Ready.")           

# ==========================================
# IMAGE PROCESSING (PIL RGB565)
# ==========================================
def process_images(file_paths, project_root, status_callback):
    out_dir = os.path.join(project_root, "media", "optimized_img")
    os.makedirs(out_dir, exist_ok=True)
    
    TARGET_SIZE = 234
    start_idx = get_next_index(out_dir)
    success_count = 0
    total_files = len(file_paths)
    
    for i, input_path in enumerate(file_paths, start=start_idx):
        filename = os.path.basename(input_path)
        base_name = os.path.splitext(filename)[0]
        
        # Clamp filename length to 45 characters to avoid ESP32 buffer overflow
        safe_base = base_name[:45]
        output_filename = f"{i:03d}_{safe_base}.bin"
        output_path = os.path.join(out_dir, output_filename)
        
        status_callback(f"Optimizing Image: {i - start_idx + 1} of {total_files}\n({filename})")
        
        try:
            img = Image.open(input_path).convert("RGB")
            old_w, old_h = img.size
            
            ratio = float(TARGET_SIZE) / max(old_w, old_h)
            new_w, new_h = int(old_w * ratio), int(old_h * ratio)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            canvas = Image.new("RGB", (TARGET_SIZE, TARGET_SIZE), (0, 0, 0))
            canvas.paste(img, ((TARGET_SIZE - new_w) // 2, (TARGET_SIZE - new_h) // 2))

            with open(output_path, "wb") as f:
                for y in range(TARGET_SIZE):
                    for x in range(TARGET_SIZE):
                        r, g, b = canvas.getpixel((x, y))
                        color565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                        f.write(struct.pack('<H', color565))
            success_count += 1
        except Exception as e:
            messagebox.showerror("Image Error", f"Failed to convert {filename}:\n{e}")
            break
            
    if success_count > 0:
        messagebox.showinfo("Success", f"Added {success_count} BIN files to:\n{out_dir}\n\nContinuing from Index: {start_idx:03d}")
    status_callback("Ready.")

# ==========================================
# TKINTER USER INTERFACE
# ==========================================
def main(project_root):
    root = tk.Tk()
    root.title("WLE5 Media Optimizer")
    # Increased geometry height to accommodate the new quality selection frame
    root.geometry("450x380")
    root.configure(bg="#1e1e1e")
    
    tk.Label(root, text="MEDIA OPTIMIZER", font=("Consolas", 18, "bold"), bg="#1e1e1e", fg="#4CAF50").pack(pady=(25, 10))
    tk.Label(root, text=f"Target: {os.path.basename(project_root)}/media/", font=("Verdana", 9), bg="#1e1e1e", fg="#888").pack(pady=(0, 10))
    
    status_label = tk.Label(root, text="Ready.", font=("Verdana", 9, "italic"), bg="#1e1e1e", fg="#FFEB3B")
    status_label.pack(pady=(0, 15))
    
    def update_status(text):
        status_label.config(text=text)
        root.update() 
    
    # --- NEW: VBR Quality Selector UI ---
    quality_var = tk.StringVar(value="4") # Default to Medium Quality
    
    q_frame = tk.Frame(root, bg="#1e1e1e")
    q_frame.pack(pady=(0, 10))
    
    tk.Label(q_frame, text="Audio VBR Quality:", font=("Verdana", 9), bg="#1e1e1e", fg="#ccc").pack(side=tk.LEFT, padx=10)
    tk.Radiobutton(q_frame, text="Low", variable=quality_var, value="7", bg="#1e1e1e", fg="white", selectcolor="#333").pack(side=tk.LEFT)
    tk.Radiobutton(q_frame, text="Med", variable=quality_var, value="4", bg="#1e1e1e", fg="white", selectcolor="#333").pack(side=tk.LEFT)
    tk.Radiobutton(q_frame, text="High", variable=quality_var, value="2", bg="#1e1e1e", fg="white", selectcolor="#333").pack(side=tk.LEFT)

    def select_audio():
        files = filedialog.askopenfilenames(title="Select Audio Files", filetypes=[("Audio Files", "*.wav *.mp3 *.m4a *.ogg *.flac")])
        if files:
            # Pass the selected VBR quality down to the audio processor
            process_audio(sorted(files), project_root, update_status, quality_var.get())
            
    def select_images():
        files = filedialog.askopenfilenames(title="Select Image Files", filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.gif")])
        if files:
            process_images(sorted(files), project_root, update_status)

    tk.Button(root, text="1. Select & Optimize Audio", font=("Verdana", 10, "bold"), bg="#4527A0", fg="white", width=30, pady=10, command=select_audio).pack(pady=5)
    tk.Button(root, text="2. Select & Optimize Images", font=("Verdana", 10, "bold"), bg="#00695C", fg="white", width=30, pady=10, command=select_images).pack(pady=5)

    root.mainloop()

# --- PYINSTALLER / CLI ENTRY POINT ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", default="", help="Ignored (for arg compatibility)")
    parser.add_argument("--root", help="Absolute path to the project root directory")
    args = parser.parse_args()

    base_dir = args.root if args.root else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    main(base_dir)
# --- END OF FILE ---