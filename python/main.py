# Last Updated: 2026-08-06 02:25 AM EDT
import sys
import os
import subprocess

# =========================================================
# PYINSTALLER SUB-PROCESS ROUTER
# Intercepts the boot sequence before Ursina or Tkinter load.
# Packages scripts cleanly into one .exe but runs them in isolated windows!
# =========================================================
if "--run-tool" in sys.argv:
    tool_name = sys.argv[sys.argv.index("--run-tool") + 1]
    mod_name = tool_name.replace(".py", "")
    
    del sys.argv[sys.argv.index("--run-tool") : sys.argv.index("--run-tool") + 2]
    
    import runpy
    runpy.run_module(mod_name, run_name="__main__")
    sys.exit(0)

if False:
    import media_sync, optimize_media, config_editor

# =========================================================
# NORMAL IDE BOOT SEQUENCE
# =========================================================
import time
import glob
import re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ursina import Ursina, application, held_keys, camera, Audio, Text, color, Button, invoke
from panda3d.core import Filename  

app = Ursina(title="WLE5 3D Simulator", borderless=False, size=(1024, 768))

from animation_engine import AnimationPlayer
from sender import parse_live_input
from wle_compiler import run_smart_sync
from robot_sim import VirtualWalle
from comm_link import CommManager
from digital_twin import DigitalTwinEngine 
import wle_config

from wle_config import TOOLS_DIR, CONFIG_DIR, ANIMS_DIR

def get_launch_cmd(script_name, *args):
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
        root_dir = os.path.abspath(os.path.join(app_dir, ".."))
        return [sys.executable, "--run-tool", script_name, "--root", root_dir] + list(args)
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(app_dir, ".."))
        return [sys.executable, script_name, "--root", root_dir] + list(args)

# =========================================================
# SHARED DATA & CONFIGURATION
# =========================================================
CFG_VERSION, JOINT_CONFIG = wle_config.load_master_config()
ID_TO_NAME = {v["id"]: k for k, v in JOINT_CONFIG.items()}
JOINTS_LIST = list(JOINT_CONFIG.keys())

HOTKEYS = {
    "yaw": "A/D", "neck_base_pitch": "W/S", "neck_top_pitch": "Q/E",
    "head_pitch": "Up/Dn", "left_eye": "T/G", "right_eye": "Y/H",
    "v_eyelid": "1/2", "left_arm_rot": "F/V", "right_arm_rot": "J/M"
}
SIMULATED_JOINTS = ["yaw", "neck_base_pitch", "neck_top_pitch", "head_pitch", "left_eye", "right_eye", "v_eyelid", "v_aperture", "v_glow_color", "left_arm_rot", "right_arm_rot"]

robot = VirtualWalle(JOINT_CONFIG)
comm = CommManager(JOINT_CONFIG, ID_TO_NAME)
master_engine = DigitalTwinEngine(JOINT_CONFIG)

def safe_force_sync():
    master_engine.force_tx_all()
    for trigger in ["v_audio_play", "v_play_anim"]:
        if trigger in master_engine.joints:
            master_engine.joints[trigger]['tx_required'] = False

# =========================================================
# TKINTER UI SETUP (MAIN WINDOW)
# =========================================================
tk_root = tk.Tk()
tk_root.title("WLE5 Animation Studio - Control Panel")
tk_root.geometry("1000x960") 

is_shutting_down = False

def on_tk_close():
    global is_shutting_down
    is_shutting_down = True
    comm.close()
    tk_root.destroy()
    application.quit()

tk_root.protocol("WM_DELETE_WINDOW", on_tk_close)

main_frame = tk.Frame(tk_root, bg="#D3D3D3")
main_frame.pack(expand=True, fill=tk.BOTH)
btn_font = ("Verdana", 9, "bold")

toolbar = tk.Frame(main_frame, bd=1, relief=tk.FLAT, bg="#333333", pady=10, padx=10)
toolbar.pack(side=tk.TOP, fill=tk.X)

left_ctrl = tk.Frame(toolbar, bg="#333333")
left_ctrl.pack(side=tk.LEFT)

def show_editor():
    editor_window.deiconify()
    editor_window.lift()
    editor_window.attributes('-topmost', True)
    editor_window.after(50, lambda: editor_window.attributes('-topmost', False))

def show_wifi_setup():
    wifi_win = tk.Toplevel(tk_root)
    wifi_win.title("ESP32 Wi-Fi Setup")
    wifi_win.geometry("300x230")
    wifi_win.configure(bg="#1e1e1e")
    wifi_win.attributes('-topmost', True)
    
    tk.Label(wifi_win, text="Wi-Fi SSID:", fg="white", bg="#1e1e1e", font=("Verdana", 10, "bold")).pack(pady=(20, 5))
    ssid_entry = tk.Entry(wifi_win, font=("Verdana", 10), width=25)
    ssid_entry.pack()
    
    tk.Label(wifi_win, text="Password:", fg="white", bg="#1e1e1e", font=("Verdana", 10, "bold")).pack(pady=(10, 5))
    pass_entry = tk.Entry(wifi_win, font=("Verdana", 10), width=25, show="*")
    pass_entry.pack()
    
    def submit():
        s = ssid_entry.get().strip()
        p = pass_entry.get().strip()
        if s:
            comm.send_wifi_config(s, p, push_log)
            wifi_win.destroy()
            messagebox.showinfo("Wi-Fi Synced", "Credentials sent!\n\nThe ESP32 will now reboot.", parent=tk_root)
            
    tk.Button(wifi_win, text="Send to Robot", font=("Verdana", 10, "bold"), bg="#4CAF50", fg="white", command=submit).pack(pady=20)

tools_mb = tk.Menubutton(left_ctrl, text="🛠️ TOOLBOX ▼", font=("Verdana", 10, "bold"), bg="#00838F", fg="white", relief=tk.FLAT, padx=10, pady=2)
tools_menu = tk.Menu(tools_mb, tearoff=0, font=("Verdana", 10), bg="#777777", fg="white", activebackground="navy")

tools_menu.add_command(label="📝 Script Editor", command=show_editor)
tools_menu.add_command(label="⚙️ Joint Config", command=lambda: run_utility_script("config_editor.py", "Config Editor", require_link=False, show_prompt=False, show_console=False))
tools_menu.add_command(label="🔄 Sync Manager", command=lambda: show_sync())
tools_menu.add_separator()
tools_menu.add_command(label="📡 Wi-Fi Setup", command=show_wifi_setup)

tools_mb.config(menu=tools_menu)
tools_mb.pack(side=tk.LEFT, padx=5)

right_ctrl = tk.Frame(toolbar, bg="#333333")
right_ctrl.pack(side=tk.RIGHT)

tk.Label(right_ctrl, text="LINK", font=("Consolas", 11, "bold"), bg="#333333", fg="#81D4FA").pack(side=tk.LEFT, padx=5)

HISTORY_FILE = os.path.join(CONFIG_DIR, "link_history.txt") if CONFIG_DIR else "link_history.txt"
recent_links = ["COM9"]

if os.path.exists(HISTORY_FILE):
    try:
        with open(HISTORY_FILE, "r") as f:
            loaded = [line.strip() for line in f.read().splitlines() if line.strip()]
            if loaded: recent_links = loaded
    except Exception: pass

def save_link_history(link):
    if link in recent_links: recent_links.remove(link)
    recent_links.insert(0, link)
    com_entry['values'] = recent_links[:5]
    try:
        with open(HISTORY_FILE, "w") as f: f.write("\n".join(recent_links[:5]))
    except Exception: pass

com_entry = ttk.Combobox(right_ctrl, font=("Verdana", 10, "bold"), width=14, values=recent_links)
com_entry.set(recent_links[0])
com_entry.pack(side=tk.LEFT, padx=3)

def attempt_connection():
    target = com_entry.get().strip()
    if "." not in target: target = target.upper() 
        
    if not comm.is_connected():
        if comm.toggle_connection(target, push_log, conn_btn):
            save_link_history(target)
            safe_force_sync()
    else:
        comm.toggle_connection(target, push_log, conn_btn)
        sim_btn.config(text=">>SIM<<", bg="lightgrey", fg="black")

conn_btn = tk.Button(right_ctrl, text="Connect", font=btn_font, bg="#4CAF50", fg="white", width=10, command=attempt_connection)
conn_btn.pack(side=tk.LEFT, padx=3)

def ui_toggle_telemetry():
    if comm.toggle_telemetry(push_log):
        safe_force_sync()
        sim_btn.config(text="<LIVE>", bg="yellow", fg="black")
    else:
        sim_btn.config(text=">>SIM<<", bg="lightgrey", fg="black")

sim_btn = tk.Button(right_ctrl, text=">>SIM<<", font=btn_font, bg="lightgrey", fg="black", width=8, command=ui_toggle_telemetry)
sim_btn.pack(side=tk.LEFT, padx=(15, 3))

PENDING_RECONNECT_TARGET = None
PENDING_WAS_LIVE = False

def run_utility_script(script_name, window_title, require_link=True, show_prompt=True, show_console=True):
    target_link = com_entry.get().strip() if require_link else ""
    
    if require_link and not target_link:
        messagebox.showerror("Error", "Please specify a COM port or IP address.")
        return
        
    if show_prompt:
        if not messagebox.askyesno(window_title, f"This will launch {script_name} in a new window.\n\nProceed?"):
            return
        
    was_connected = comm.is_connected()
    was_live = comm.telemetry_enabled
    
    if require_link and was_connected:
        comm.toggle_connection(target_link, push_log, conn_btn)
        sim_btn.config(text=">>SIM<<", bg="lightgrey", fg="black")
        push_log(f"Auto-disconnected IDE for {script_name}.")
        
    try:
        push_log(f"Launching {script_name}...")
        import threading
        
        def run_and_reconnect():
            args = [target_link] if target_link else []
            cmd = get_launch_cmd(script_name, *args)
            
            tools_path = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            cflags = subprocess.CREATE_NEW_CONSOLE if show_console else 0x08000000
            
            if show_console:
                proc = subprocess.Popen(cmd, cwd=tools_path, creationflags=cflags)
            else:
                proc = subprocess.Popen(
                    cmd, cwd=tools_path, creationflags=cflags, 
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            
            proc.wait() 
            
            if require_link and was_connected:
                time.sleep(1.5) 
                global PENDING_RECONNECT_TARGET, PENDING_WAS_LIVE
                PENDING_WAS_LIVE = was_live
                PENDING_RECONNECT_TARGET = target_link
                
        threading.Thread(target=run_and_reconnect, daemon=True).start()
    except Exception as e:
        messagebox.showerror("Execution Error", f"Failed to launch {script_name}.\n{str(e)}")

# =========================================================
# NEW SYNC & MEDIA POPUP WINDOW
# =========================================================
def create_scrolled_listbox(parent, height, expand=False):
    frame = tk.Frame(parent, bg="#1e1e1e")
    if expand: frame.pack(fill=tk.BOTH, expand=True, pady=5)
    else: frame.pack(fill=tk.X, pady=5)
    
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    listbox = tk.Listbox(frame, bg="#333", fg="white", height=height, highlightthickness=0, borderwidth=0, yscrollcommand=scrollbar.set)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=listbox.yview)
    return listbox

sync_window = tk.Toplevel(tk_root)
sync_window.title("WLE5 Sync & Media Manager")
sync_window.geometry("700x825")
sync_window.withdraw() 
sync_window.protocol("WM_DELETE_WINDOW", sync_window.withdraw)

sync_frame_main = tk.Frame(sync_window, bg="#1e1e1e", padx=20, pady=20)
sync_frame_main.pack(fill=tk.BOTH, expand=True)

cfg_col = tk.Frame(sync_frame_main, bg="#1e1e1e")
cfg_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
media_col = tk.Frame(sync_frame_main, bg="#1e1e1e")
media_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10)

tk.Label(cfg_col, text="CONFIG SYNC", font=("Consolas", 14, "bold"), bg="#1e1e1e", fg="#4CAF50").pack(pady=(0, 10))
tk.Button(cfg_col, text="Sync Configs & Scripts", font=btn_font, bg="#8B0000", fg="white", command=lambda: run_smart_sync(comm.active_link, tk_root, push_log, animations, anim_player, JOINT_CONFIG, CONFIG_DIR, ANIMS_DIR, rescan_scripts)).pack(fill=tk.X, pady=5)

tk.Label(cfg_col, text="IDLE STATES", font=("Verdana", 10, "bold"), bg="#1e1e1e", fg="white").pack(anchor="w", pady=(10,0))
idle_listbox = create_scrolled_listbox(cfg_col, height=4, expand=False)

tk.Label(cfg_col, text="ANIMATIONS", font=("Verdana", 10, "bold"), bg="#1e1e1e", fg="white").pack(anchor="w", pady=(10,0))
anim_listbox = create_scrolled_listbox(cfg_col, height=8, expand=True)

tk.Label(media_col, text="MEDIA SYNC", font=("Consolas", 14, "bold"), bg="#1e1e1e", fg="#2196F3").pack(pady=(0, 10))

media_btn_frame = tk.Frame(media_col, bg="#1e1e1e")
media_btn_frame.pack(fill=tk.X, pady=5)

tk.Button(media_btn_frame, text="Sync Media to Robot", font=btn_font, bg="#d84315", fg="white", command=lambda: run_utility_script("media_sync.py", "Sync Media", require_link=True, show_prompt=True, show_console=False)).pack(side=tk.TOP, expand=True, fill=tk.X, pady=(0, 4))
tk.Button(media_btn_frame, text="Add Media", font=btn_font, bg="#4527A0", fg="white", command=lambda: run_utility_script("optimize_media.py", "Add Media", require_link=False, show_prompt=False, show_console=False)).pack(side=tk.TOP, expand=True, fill=tk.X, pady=(0, 4))

tk.Button(media_btn_frame, text="↻ Refresh Lists", font=("Verdana", 8, "bold"), bg="#555555", fg="white", command=lambda: refresh_sync_lists()).pack(side=tk.TOP, expand=True, fill=tk.X)

tk.Label(media_col, text="AUDIO FILES", font=("Verdana", 10, "bold"), bg="#1e1e1e", fg="white").pack(anchor="w", pady=(10,0))
audio_listbox = create_scrolled_listbox(media_col, height=8, expand=True)

tk.Label(media_col, text="IMAGE FILES", font=("Verdana", 10, "bold"), bg="#1e1e1e", fg="white").pack(anchor="w", pady=(10,0))
img_listbox = create_scrolled_listbox(media_col, height=8, expand=True)

def refresh_sync_lists():
    anim_listbox.delete(0, tk.END)
    idle_listbox.delete(0, tk.END)
    audio_listbox.delete(0, tk.END)
    img_listbox.delete(0, tk.END)

    for idx, a in enumerate(animations):
        anim_listbox.insert(tk.END, f"{idx+1}. {a['name']}")

    combined = ""
    for f in glob.glob(os.path.join(ANIMS_DIR, "*.wle")) + glob.glob(os.path.join(ANIMS_DIR, "*.txt")):
        with open(f, 'r') as file: combined += file.read() + "\n"
    state_blocks = re.finditer(r'\[State:\s*(.+?)\]', combined, re.IGNORECASE)
    for idx, match in enumerate(state_blocks):
        idle_listbox.insert(tk.END, f"{idx+1}. {match.group(1).strip()}")

    proj_root = os.path.dirname(CONFIG_DIR) if CONFIG_DIR else "."
    
    audio_dir = os.path.join(proj_root, "media", "optimized_audio")
    img_dir = os.path.join(proj_root, "media", "optimized_img")

    if os.path.exists(audio_dir):
        for idx, f in enumerate(sorted(os.listdir(audio_dir))):
            if f.endswith(('.wav', '.mp3', '.bin')): audio_listbox.insert(tk.END, f"{idx+1}. {f}")
    if os.path.exists(img_dir):
        for idx, f in enumerate(sorted(os.listdir(img_dir))):
            if f.endswith(('.jpg', '.png', '.bin', '.bmp')): img_listbox.insert(tk.END, f"{idx+1}. {f}")

def show_sync():
    refresh_sync_lists()
    sync_window.deiconify()
    sync_window.lift()
    sync_window.attributes('-topmost', True)
    sync_window.after(50, lambda: sync_window.attributes('-topmost', False))

# =========================================================
# ACCORDION UI SETUP (JOINTS)
# =========================================================
joints_frame = tk.Frame(main_frame, pady=10, bg="#D3D3D3")
joints_frame.pack(side=tk.TOP, fill=tk.X, padx=10)

sync_frame = tk.Frame(joints_frame, bg="#D3D3D3")
sync_frame.grid(row=0, column=3, columnspan=2, padx=5, pady=5)

def pull_from_sim():
    for j_name, entries in tk_inputs.items():
        if entries["tgt"].get().strip() != "" and j_name in master_engine.joints:
            entries["tgt"].delete(0, tk.END)
            entries["tgt"].insert(0, f"{master_engine.joints[j_name]['current_position']:.1f}")

def push_to_sim():
    for j_name, entries in tk_inputs.items():
        t_val, s_val = entries["tgt"].get().strip(), entries["spd"].get().strip()
        if t_val: 
            try:
                tgt = float(t_val)
                spd = int(s_val) if s_val else JOINT_CONFIG[j_name].get("def_spd", 255)
                master_engine.set_target(j_name, tgt, spd)
                
                if j_name.lower() in ["v_audio_play", "v_play_anim"]:
                    master_engine.joints[j_name]['tx_required'] = True
                    master_engine.joints[j_name]['tx_speed'] = spd
                
                if j_name.lower() == "v_audio_play":
                    play_sim_audio(int(tgt))
                    
            except ValueError: pass

def jog_joint(j_name, delta):
    try:
        current_tgt = master_engine.joints[j_name]['user_target']
        spd = JOINT_CONFIG[j_name].get("def_spd", 255)
        master_engine.set_target(j_name, current_tgt + delta, spd)
    except Exception: pass

tk.Button(sync_frame, text="SIM>", width=6, font=("Verdana", 9, "bold"), bg="#ddd", takefocus=0, command=pull_from_sim).pack(side=tk.LEFT, padx=2)
tk.Button(sync_frame, text="< PUSH", width=6, font=("Verdana", 9, "bold"), bg="#ddd", takefocus=0, command=push_to_sim).pack(side=tk.LEFT, padx=2)

tk.Label(joints_frame, text="SIM", font=("Verdana", 9, "bold"), bg="#D3D3D3").grid(row=0, column=2)
tk.Label(joints_frame, text="SCRIPT", font=("Verdana", 9, "bold"), bg="#D3D3D3").grid(row=0, column=5, columnspan=2)

for col, (text, width) in enumerate(zip(["Reg", "Joint", "POS", "Keys", "Min", "Set", "Max", "Spd", "Def Spd"], [4, 16, 6, 4, 6, 4, 6, 4, 8])):
    tk.Label(joints_frame, text=text, font=("Verdana", 10, "bold"), width=width, bg="#D3D3D3").grid(row=1, column=col, pady=2)

tk_inputs, tk_pos_labels = {}, {}
joints_by_region, region_widgets, region_state = {}, {}, {}
ordered_tgt_entries = []
ordered_spd_entries = []

for j in JOINTS_LIST:
    if j in JOINT_CONFIG: joints_by_region.setdefault(JOINT_CONFIG[j].get("region", 0), []).append(j)

def toggle_region(r_idx, btn):
    region_state[r_idx] = not region_state[r_idx]
    btn.config(text=f"{r_idx} ►" if not region_state[r_idx] else f"{r_idx} ▼")
    for w in region_widgets[r_idx]: w.grid_remove() if not region_state[r_idx] else w.grid()

row_idx = 2
for r_idx in sorted(joints_by_region.keys()):
    region_state[r_idx], region_widgets[r_idx] = True, []
    btn = tk.Button(joints_frame, text=f"{r_idx} ▼", font=("Verdana", 8, "bold"), bg="#555", fg="white", bd=1, takefocus=0)
    btn.grid(row=row_idx, column=0, sticky="n", pady=2)
    btn.config(command=lambda r=r_idx, b=btn: toggle_region(r, b))
    
    for j in joints_by_region[r_idx]:
        cfg, is_sim = JOINT_CONFIG[j], j in SIMULATED_JOINTS
        row_widgets = []
        
        name_bg = "#D3D3D3" if is_sim else "#666666"
        name_fg = "black" if is_sim else "white"
        row_bg = "#D3D3D3"
        row_fg = "black"
        
        lbl = tk.Label(joints_frame, text=j, font=("Verdana", 10, "bold"), width=16, anchor="w", bg=name_bg, fg=name_fg)
        lbl.grid(row=row_idx, column=1, padx=2, pady=1)
        row_widgets.append(lbl)
        
        tk_pos_labels[j] = tk.Label(joints_frame, text="0.0", font=("Verdana", 10), width=6, fg="blue", bg=row_bg)
        tk_pos_labels[j].grid(row=row_idx, column=2)
        row_widgets.append(tk_pos_labels[j])
        
        kf = tk.Frame(joints_frame, bg=row_bg)
        kf.grid(row=row_idx, column=3, padx=0)
        row_widgets.append(kf)
        if "/" in HOTKEYS.get(j, ""):
            k1, k2 = HOTKEYS[j].split("/")[:2]
            tk.Button(kf, text=k1, font=("Verdana", 7), width=1, padx=2, takefocus=0, command=lambda jn=j: jog_joint(jn, -5)).pack(side=tk.LEFT, padx=1)
            tk.Button(kf, text=k2, font=("Verdana", 7), width=1, padx=2, takefocus=0, command=lambda jn=j: jog_joint(jn, 5)).pack(side=tk.LEFT, padx=1)
        elif HOTKEYS.get(j, ""): tk.Label(kf, text=HOTKEYS[j], font=("Verdana", 8, "italic"), fg="gray", bg=row_bg).pack()
            
        shade_bg = "#C0C0C0"
        for c, t, w, bg_col in [(4, cfg["r_min"], 6, shade_bg), (6, cfg["r_max"], 6, shade_bg), (8, cfg["def_spd"], 8, row_bg)]:
            l = tk.Label(joints_frame, text=str(t), font=("Verdana", 10), width=w, bg=bg_col, fg=row_fg)
            l.grid(row=row_idx, column=c)
            row_widgets.append(l)
        
        tgt, spd = tk.Entry(joints_frame, font=("Verdana", 11, "bold"), width=5), tk.Entry(joints_frame, font=("Verdana", 11, "bold"), width=4)
        tgt.grid(row=row_idx, column=5, padx=2)
        spd.grid(row=row_idx, column=7, padx=2)
        row_widgets.extend([tgt, spd])
        
        tk_inputs[j] = {"tgt": tgt, "spd": spd}
        ordered_tgt_entries.append(tgt)
        ordered_spd_entries.append(spd)
        region_widgets[r_idx].extend(row_widgets)
        row_idx += 1

def focus_next_entry(entries_list, current_idx, direction):
    next_idx = current_idx + direction
    if 0 <= next_idx < len(entries_list):
        entries_list[next_idx].focus_set()
        entries_list[next_idx].select_range(0, tk.END) 
    return "break"

def on_enter_tab(event):
    event.widget.tk_focusNext().focus()
    return "break"

for i, t_entry in enumerate(ordered_tgt_entries):
    t_entry.bind('<Up>', lambda e, idx=i: focus_next_entry(ordered_tgt_entries, idx, -1))
    t_entry.bind('<Down>', lambda e, idx=i: focus_next_entry(ordered_tgt_entries, idx, 1))
    t_entry.bind('<Return>', on_enter_tab)

for i, s_entry in enumerate(ordered_spd_entries):
    s_entry.bind('<Up>', lambda e, idx=i: focus_next_entry(ordered_spd_entries, idx, -1))
    s_entry.bind('<Down>', lambda e, idx=i: focus_next_entry(ordered_spd_entries, idx, 1))
    s_entry.bind('<Return>', on_enter_tab)

tk.Frame(main_frame, height=15, bg="#D3D3D3").pack(side=tk.TOP, fill=tk.X)

# =========================================================
# FLOATING SCRIPT EDITOR WINDOW
# =========================================================
editor_window = tk.Toplevel(tk_root)
editor_window.title("WLE5 Script Editor")
editor_window.geometry("960x700") 
editor_window.withdraw() 
editor_window.protocol("WM_DELETE_WINDOW", lambda: editor_window.withdraw())

editor_frame = tk.Frame(editor_window, pady=10)
editor_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)
editor_toolbar_top = tk.Frame(editor_frame)
editor_toolbar_top.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))

def load_script_file():
    filepath = filedialog.askopenfilename(initialdir=ANIMS_DIR, defaultextension=".wle", filetypes=[("WLE Scripts", "*.wle"), ("Text Files", "*.txt"), ("All Files", "*.*")])
    if filepath:
        with open(filepath, 'r') as f:
            text_area.delete(1.0, tk.END)
            text_area.insert(tk.END, f.read())
        rescan_scripts()
    editor_window.lift()
    editor_window.attributes('-topmost', True)
    editor_window.after(50, lambda: editor_window.attributes('-topmost', False))

def save_script_file():
    filepath = filedialog.asksaveasfilename(initialdir=ANIMS_DIR, initialfile="new_animation.wle", defaultextension=".wle", filetypes=[("WLE Scripts", "*.wle"), ("Text Files", "*.txt"), ("All Files", "*.*")])
    if filepath:
        with open(filepath, 'w') as f: f.write(text_area.get(1.0, tk.END))
        messagebox.showinfo("Saved", f"Script saved successfully to:\n{filepath}")
        rescan_scripts()
    editor_window.lift()
    editor_window.attributes('-topmost', True)
    editor_window.after(50, lambda: editor_window.attributes('-topmost', False))

tk.Button(editor_toolbar_top, text="Load Script", font=btn_font, bg="#1A237E", fg="white", width=12, command=load_script_file).pack(side=tk.LEFT, padx=2)
tk.Button(editor_toolbar_top, text="Save Script As...", font=btn_font, bg="#1A237E", fg="white", width=16, command=save_script_file).pack(side=tk.LEFT, padx=2)

def update_script_dropdown():
    names = re.findall(r'\[Anim:\s*(.+?)\]', text_area.get(1.0, tk.END), re.IGNORECASE)
    script_combo['values'] = names
    if names and script_combo.get() not in names: script_combo.current(0)
    elif not names: script_combo.set('')

tk.Button(editor_toolbar_top, text="Test in Sim", font=("Verdana", 10, "bold"), bg="#2196F3", fg="white", command=lambda: [safe_force_sync(), anim_player.load_script(script_combo.get(), text_area.get(1.0, tk.END)), anim_player.play()] if script_combo.get() else messagebox.showwarning("Warning", "Select an animation.")).pack(side=tk.RIGHT, padx=2)
script_combo = ttk.Combobox(editor_toolbar_top, width=15, font=("Verdana", 10), state="readonly", postcommand=update_script_dropdown)
script_combo.pack(side=tk.RIGHT, padx=5)
tk.Label(editor_toolbar_top, text="Target Anim:", font=("Verdana", 10, "bold")).pack(side=tk.RIGHT)

editor_toolbar_bot = tk.Frame(editor_frame)
editor_toolbar_bot.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

tk.Label(editor_toolbar_bot, text="Time(s):", font=("Verdana", 11, "bold")).pack(side=tk.LEFT)
time_entry = tk.Entry(editor_toolbar_bot, font=("Verdana", 12, "bold"), width=6)
time_entry.insert(0, "0.0")
time_entry.pack(side=tk.LEFT, padx=5)

def insert_line_from_ui():
    parts = [f"@{time_entry.get().strip()}s"]
    for j, e in tk_inputs.items():
        if e["tgt"].get().strip(): parts.append(f"{j}={e['tgt'].get().strip()},{e['spd'].get().strip()}" if e['spd'].get().strip() else f"{j}={e['tgt'].get().strip()}")
    if len(parts) > 1:
        text_area.insert(tk.INSERT, "    ".join(parts) + "\n")
        for e in tk_inputs.values(): e["tgt"].delete(0, tk.END); e["spd"].delete(0, tk.END)

tk.Button(editor_toolbar_bot, text="Add Line To Script", font=("Verdana", 10, "bold"), bg="#4CAF50", fg="white", command=insert_line_from_ui).pack(side=tk.LEFT, padx=10)

text_area = tk.Text(editor_frame, wrap=tk.WORD, font=("Consolas", 14))
text_area.pack(expand=True, fill=tk.BOTH)
text_area.insert(tk.END, "# Write your animation scripts here...")

def on_text_area_click(e=None):
    line = text_area.get(f"{text_area.index(tk.INSERT).split('.')[0]}.0", f"{text_area.index(tk.INSERT).split('.')[0]}.end").strip()
    if not line or line.startswith('#') or line.startswith('['): return
    for ent in tk_inputs.values(): ent["tgt"].delete(0, tk.END); ent["spd"].delete(0, tk.END)
    for j, v, s in re.findall(r'([a-zA-Z0-9_]+)=([-\d\.]+)(?:,([\d\.]+))?', line):
        if j in JOINT_CONFIG and j in tk_inputs:
            try:
                tk_inputs[j]["tgt"].insert(0, str(float(v)))
                if s: tk_inputs[j]["spd"].insert(0, s)
            except ValueError: pass
text_area.bind('<ButtonRelease-1>', on_text_area_click); text_area.bind('<KeyRelease>', on_text_area_click)

# =========================================================
# ANIMATION & COMM SYNC ENGINE
# =========================================================
animations = []
def rescan_scripts():
    animations.clear()
    for f in glob.glob(os.path.join(ANIMS_DIR, "*.wle")) + glob.glob(os.path.join(ANIMS_DIR, "*.txt")):
        with open(f, 'r') as file:
            for m in re.finditer(r'\[Anim:\s*(.+?)\](.*?)(?=\[|$)', file.read(), re.DOTALL | re.IGNORECASE):
                animations.append({"name": m.group(1).strip(), "script": "[Anim: " + m.group(1) + "]" + m.group(2)})

def push_log(msg):
    logs = robot.command_log_display.text.replace("--- COMMAND STREAM ---\n", "").split('\n')
    logs.append(msg)
    if len(logs) > 35: logs.pop(0)
    robot.command_log_display.text = "--- COMMAND STREAM ---\n" + "\n".join(logs)

current_sim_audio = None
pc_audio_enabled = True

def play_sim_audio(track_id):
    global current_sim_audio, pc_audio_enabled
    
    if not pc_audio_enabled:
        return
        
    if track_id <= 0:
        if current_sim_audio: current_sim_audio.stop()
        return
        
    proj_root = os.path.abspath(os.path.join(CONFIG_DIR, "..")) if CONFIG_DIR else "."
    audio_dir = os.path.join(proj_root, "media", "optimized_audio")
    valid_exts = ('.wav', '.mp3', '.ogg')
    
    if os.path.exists(audio_dir):
        files = sorted([f for f in os.listdir(audio_dir) if f.endswith(valid_exts)])
    else:
        files = []
        
    if not files:
        fallback_dir = os.path.join(proj_root, "audio")
        if os.path.exists(fallback_dir):
            files = sorted([f for f in os.listdir(fallback_dir) if f.endswith(valid_exts)])
            audio_dir = fallback_dir
            
    if not files:
        push_log("Audio Error: No playable .wav/.mp3 found for PC Simulator.")
        return
        
    idx = int(track_id) - 1
    if 0 <= idx < len(files):
        raw_path = os.path.abspath(os.path.join(audio_dir, files[idx]))
        panda_path = Filename.fromOsSpecific(raw_path).getFullpath()
        
        if current_sim_audio: current_sim_audio.stop()
        try: 
            sound_obj = application.base.loader.loadSfx(panda_path)
            
            if sound_obj:
                # --- THE FIX ---
                # Drop the Ursina Audio() wrapper entirely! 
                # We can just use the native Panda3D sound object directly.
                current_sim_audio = sound_obj
                
                # Delays the PC playback without blocking the 3D physics loop
                invoke(current_sim_audio.play, delay=0.3)
                # ---------------
                
                push_log(f"Sim Audio: Playing track {track_id} (0.8s sync delay)")
            else:
                push_log(f"Audio Error: Panda3D could not decode {files[idx]}")
        except Exception as e: 
            push_log(f"Audio Playback Error: {e}")
    else: 
        push_log(f"Audio Error: Track {track_id} out of bounds.")
        
rescan_scripts()
anim_player = AnimationPlayer(JOINT_CONFIG)
current_anim_index = 0
if animations: anim_player.load_script(animations[0]["name"], animations[0]["script"])

def on_keyframe_triggered(targets):
    for j_name, data in targets.items():
        master_engine.set_target(j_name, data["target"], data["speed"])
        
        # --- THE FIX ---
        # Force discrete triggers to transmit over TCP even if the value hasn't changed since the last run!
        if j_name.lower() in ["v_audio_play", "v_play_anim", "v_img_select", "v_asymmetry"]:
            if j_name in master_engine.joints:
                master_engine.joints[j_name]['tx_required'] = True
                master_engine.joints[j_name]['tx_speed'] = data["speed"]
        # ---------------
                
        if j_name.lower() == "v_audio_play": play_sim_audio(int(data["target"]))
        tgt_val = data['target']
        tgt_str = int(tgt_val) if float(tgt_val).is_integer() else tgt_val
        push_log(f"[{round(anim_player.current_time, 2):.2f}s] {j_name}={tgt_str},{data['speed']}")
anim_player.on_keyframe_triggered = on_keyframe_triggered

def handle_terminal_submit():
    try: cmd = str(robot.terminal_input.text).strip()
    except: cmd = ""
        
    robot.terminal_input.text = ""
    robot.terminal_bg.enabled = False
    robot.terminal_input.enabled = False
    robot.terminal_input.active = False 
    if not cmd: return
    
    if cmd.lower() in ['cam', 'camera']:
        try:
            from ursina import camera
            push_log(f"Cam Pos: ({camera.world_x:.2f}, {camera.world_y:.2f}, {camera.world_z:.2f})")
            push_log(f"Cam Rot: ({camera.world_rotation_x:.2f}, {camera.world_rotation_y:.2f}, {camera.world_rotation_z:.2f})")
        except Exception as e: push_log(f"Cam Error: {e}")
        return
        
    action, data = parse_live_input(cmd, JOINT_CONFIG)
    if action == "TEST":
        rescan_scripts()
        f = next((a for a in animations if a["name"].lower() == data.lower()), None)
        if f: 
            safe_force_sync()
            anim_player.load_script(f["name"], f["script"])
            anim_player.play()
        else: push_log(f"Error: Anim '{data}' not found locally.")
    elif action == "PLAY": comm.send_play_command(data, push_log)
    elif action == "JOINTS":
        matches = re.findall(r'(\w+)=(-?\d+\.?\d*)(?:,(\d+))?', data)
        for j_name, tgt_str, spd_str in matches:
            if j_name in JOINT_CONFIG:
                tgt = float(tgt_str)
                spd = int(spd_str) if spd_str else JOINT_CONFIG[j_name].get("def_spd", 255)
                master_engine.set_target(j_name, tgt, spd)
                if j_name.lower() == "v_audio_play": play_sim_audio(int(tgt))
    elif action == "ERROR": push_log(f"Terminal Error: {data}")
robot.terminal_input.on_submit = handle_terminal_submit

# =========================================================
# URSINA AUDIO MUTE TOGGLE
# =========================================================
audio_toggle_btn = Button(text='PC Audio: ON', position=(0.50, -0.45), scale=(0.22, 0.05), color=color.green.tint(-0.2))

def toggle_pc_audio():
    global pc_audio_enabled
    pc_audio_enabled = not pc_audio_enabled
    if not pc_audio_enabled and current_sim_audio:
        current_sim_audio.stop()
        
    audio_toggle_btn.text = 'PC Audio: ON' if pc_audio_enabled else 'PC Audio: MUTED'
    
    base_col = color.green if pc_audio_enabled else color.red
    audio_toggle_btn.color = base_col.tint(-0.2)
    audio_toggle_btn.highlight_color = base_col.tint(-0.1)
    audio_toggle_btn.pressed_color = base_col.tint(-0.3)
    
    push_log(f"PC Audio: {'ON' if pc_audio_enabled else 'MUTED'}")

audio_toggle_btn.on_click = toggle_pc_audio

def input(key):
    global current_anim_index, pc_audio_enabled
    if key == 'enter':
        if not robot.terminal_bg.enabled: robot.terminal_bg.enabled, robot.terminal_input.enabled, robot.terminal_input.active = True, True, True
        else: handle_terminal_submit()
    if robot.terminal_input.active: return 
    
    if key == 'm':
        toggle_pc_audio()
    
    if key == 'space' and not anim_player.is_playing and animations:
        current_anim_index = (current_anim_index + 1) % len(animations)
        safe_force_sync()
        anim_player.load_script(animations[current_anim_index]["name"], animations[current_anim_index]["script"])
        anim_player.play()
            
    if key == 'u': ui_toggle_telemetry()
    if key in ['1', '2', 'b']: robot.blink_eyes()

def handle_manual_jogging(keys):
    def jog(j_name, pos_key, neg_key, step=1.0):
        if j_name in master_engine.joints:
            if keys[pos_key] or keys[neg_key]:
                delta = step if keys[pos_key] else -step
                current_tgt = master_engine.joints[j_name]['user_target']
                spd = JOINT_CONFIG[j_name].get("def_spd", 100)
                master_engine.set_target(j_name, current_tgt + delta, spd)

    jog("yaw", "d", "a"); jog("neck_base_pitch", "s", "w"); jog("neck_top_pitch", "e", "q")
    jog("head_pitch", "up arrow", "down arrow"); jog("left_arm_rot", "v", "f"); jog("right_arm_rot", "m", "j")

# =========================================================
# THE MASTER UPDATE LOOP
# =========================================================
esp32_hz_display = Text(text="ESP32: OFFLINE", position=(-0.65, -0.42), scale=1, color=color.gray)

def update():
    global PENDING_RECONNECT_TARGET, PENDING_WAS_LIVE, is_shutting_down
    
    if is_shutting_down: return
    
    if PENDING_RECONNECT_TARGET:
        target = PENDING_RECONNECT_TARGET
        PENDING_RECONNECT_TARGET = None
        if not comm.is_connected():
            if comm.toggle_connection(target, push_log, conn_btn):
                save_link_history(target)
                safe_force_sync()
                if PENDING_WAS_LIVE: ui_toggle_telemetry()

    try:
        if tk_root.winfo_exists(): tk_root.update()
        else: application.quit() 
    except Exception: 
        is_shutting_down = True 

    if is_shutting_down: return 

    anim_player.update(min(time.dt, 0.1))
    if not anim_player.is_playing and not robot.terminal_input.active: handle_manual_jogging(held_keys)

    master_engine.update_physics(min(time.dt, 0.1))
    robot.sync_to_master(master_engine.joints)
    
    if comm.telemetry_enabled:
        packets = master_engine.get_tx_packets()
        comm.send_packets(packets)
    else: master_engine.get_tx_packets() 

    try:
        for j_name, lbl in tk_pos_labels.items():
            if j_name in master_engine.joints:
                lbl.config(text=f"{master_engine.joints[j_name]['current_position']:.1f}")
    except Exception: pass
            
    if comm.is_connected():
        stats = comm.read_telemetry()
        if stats is not None:
            kb_sram = stats['sram'] / 1024
            mb_psram = stats['psram'] / (1024 * 1024)
            
            esp32_hz_display.text = (
                f"ESP32: {stats['phys_hz']}Hz | GFX: {stats['gfx_fps']}FPS | Wifi: {stats['rssi']}dBm\n"
                f"SRAM: {kb_sram:.1f}KB | PSRAM: {mb_psram:.1f}MB"
            )
            esp32_hz_display.color = color.green if stats['phys_hz'] >= 45 else color.orange
    else:
        esp32_hz_display.text = "ESP32: OFFLINE"
        esp32_hz_display.color = color.gray
        
        # --- NEW: Visually reset the UI if the watchdog drops the connection ---
        if conn_btn.cget('text') == "Disconnect":
            conn_btn.config(text="Connect", bg="#4CAF50")
            sim_btn.config(text=">>SIM<<", bg="lightgrey", fg="black")
            push_log("Connection Lost: Watchdog Timeout (30s).")
            
    robot.servo_display.text = (
        f"--- WLE5 SIMULATOR ---\n"
        f"Link: {'CONNECTED' if comm.is_connected() else 'DISCONNECTED'}\n"
        f"Live Stream: {'ACTIVE (u to pause)' if comm.telemetry_enabled else 'PAUSED (u to start)'}\n\n"
        f"Press joint jog keys or\n"
        f"[SPACE] to play through scripts\n"
        f"{'--- TERMINAL MODE ACTIVE ---' if robot.terminal_input.active else ''}"
    )

app.run()
# --- END OF FILE ---