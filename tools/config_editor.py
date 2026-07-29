import tkinter as tk
from tkinter import messagebox, ttk
import wle_config

class ConfigEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WLE5 Hardware Configuration Editor")
        self.geometry("1150x600")

        # Load the configuration data securely via the central hub
        self.version, self.joints = wle_config.load_master_config()

        # --- TOOLBAR ---
        toolbar = tk.Frame(self, bg="#e0e0e0", bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        
        tk.Button(toolbar, text="+ Add Physical Joint", font=("Verdana", 9, "bold"), 
                  bg="#2196F3", fg="white", command=self.add_joint).pack(side=tk.LEFT, padx=10, pady=8)
                  
        tk.Button(toolbar, text="Save & Export Configurations", font=("Verdana", 9, "bold"), 
                  bg="#4CAF50", fg="white", command=self.save_and_export).pack(side=tk.RIGHT, padx=10, pady=8)

        # --- SCROLLABLE CANVAS ---
        self.canvas = tk.Canvas(self)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview, width=25) 
        self.scroll_frame = tk.Frame(self.canvas)

        # Update scroll region dynamically but safely
        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Mouse wheel support for the main canvas
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self.entries = {}
        self.build_grid()

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def build_grid(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        # Build Headers
        headers = ["Joint Name", "ID", "Region", "Ctrl Type", "HW Addr", "R_Min", "R_Max", "R_Init", "Cmd_Min", "Cmd_Max", "Cmd_Init", "Def_Spd", "Max_Spd", "Max_Acc"]
        for col, text in enumerate(headers):
            w = 15 if text == "Joint Name" else (14 if text == "Ctrl Type" else 8)
            tk.Label(self.scroll_frame, text=text, font=("Verdana", 9, "bold"), bg="#d3d3d3", width=w).grid(row=0, column=col, padx=1, pady=5, sticky="ew")

        self.entries = {}
        row = 1
        
        sorted_joints = sorted(self.joints.items(), key=lambda x: x[1].get("id", 999))
        
        for orig_name, cfg in sorted_joints:
            self.create_row(row, orig_name, cfg)
            row += 1

    def create_row(self, row, orig_name, cfg):
        row_entries = {}
        
        name_entry = tk.Entry(self.scroll_frame, font=("Verdana", 9, "bold"), width=18)
        name_entry.insert(0, orig_name)
        
        try:
            is_virtual = int(cfg.get("control_type", 1)) == 2
        except (ValueError, TypeError):
            is_virtual = False

        if is_virtual:
            name_entry.config(state="readonly", fg="gray") 
            
        name_entry.grid(row=row, column=0, padx=2, pady=3)
        row_entries["name"] = name_entry
        row_entries["orig_name"] = orig_name 

        fields = ["id", "region", "control_type", "hardware_address", "r_min", "r_max", "r_init", "cmd_min", "cmd_max", "cmd_init", "def_spd", "max_spd", "max_acc"]
        
        for col, field in enumerate(fields, start=1):
            if field == "control_type":
                ctrl_combo = ttk.Combobox(self.scroll_frame, values=["0: ESP32 PWM", "1: PCA9685", "2: Virtual"], width=13, state="readonly", font=("Consolas", 9))
                type_map = {0: "0: ESP32 PWM", 1: "1: PCA9685", 2: "2: Virtual"}
                
                try:
                    current_val = int(cfg.get(field, 1))
                except (ValueError, TypeError):
                    current_val = 1
                    
                ctrl_combo.set(type_map.get(current_val, "1: PCA9685"))
                
                # --- THE FIX: Block the scroll wheel from modifying this specific widget ---
                def block_combo_scroll(event):
                    self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                    return "break"
                
                ctrl_combo.bind('<MouseWheel>', block_combo_scroll)
                # -------------------------------------------------------------------------

                ctrl_combo.grid(row=row, column=col, padx=2, pady=3)
                row_entries[field] = ctrl_combo
            else:
                ent = tk.Entry(self.scroll_frame, font=("Consolas", 10), width=9)
                ent.insert(0, str(cfg.get(field, 0)))
                ent.grid(row=row, column=col, padx=2, pady=3)
                row_entries[field] = ent

        self.entries[orig_name] = row_entries

    def add_joint(self):
        new_name = f"new_joint_{len(self.joints)}"
        
        while new_name in self.joints:
            new_name = f"{new_name}_1"
            
        used_ids = [j.get("id", 0) for name, j in self.joints.items() if j.get("control_type", 1) != 2]
        next_id = max(used_ids + [-1]) + 1
            
        self.joints[new_name] = {
            "id": next_id,
            "region": 0, "control_type": 1, "hardware_address": -1,
            "r_min": -90.0, "r_max": 90.0, "r_init": 0.0,
            "cmd_min": 500, "cmd_max": 2500, "cmd_init": 1500,
            "def_spd": 100, "max_spd": 255, "max_acc": 255
        }
        
        self.build_grid()
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0) 

    def save_and_export(self):
        new_joints = {}
        try:
            for orig_name, row_data in self.entries.items():
                name_val = row_data["name"].get().strip()
                if not name_val: continue

                ctrl_str = row_data["control_type"].get()
                ctrl_int = int(ctrl_str.split(":")[0])

                cfg = {
                    "id": int(row_data["id"].get()),
                    "region": int(row_data["region"].get()),
                    "control_type": ctrl_int,
                    "hardware_address": int(row_data["hardware_address"].get()),
                    "r_min": float(row_data["r_min"].get()),
                    "r_max": float(row_data["r_max"].get()),
                    "r_init": float(row_data["r_init"].get()),
                    "cmd_min": int(row_data["cmd_min"].get()),
                    "cmd_max": int(row_data["cmd_max"].get()),
                    "cmd_init": int(row_data["cmd_init"].get()),
                    "def_spd": int(row_data["def_spd"].get()),
                    "max_spd": int(row_data["max_spd"].get()),
                    "max_acc": int(row_data["max_acc"].get())
                }
                new_joints[name_val] = cfg

            self.joints = new_joints
            # --- THE FIX: Increment the version number before saving! ---
            self.version += 1 
            # ------------------------------------------------------------
            wle_config.save_master_config(self.version, self.joints)
            wle_config.export_cpp_header(self.joints)
            wle_config.export_config_bin(self.version, self.joints)
            
            messagebox.showinfo("Success", "Configuration Saved and Exported Successfully!\n\nYou can now use Smart Sync to push limits to the ESP32.")
            
            self.build_grid() 
            
        except ValueError as e:
            messagebox.showerror("Validation Error", f"Please ensure all numerical fields contain valid numbers.\n\nDetails: {e}")

if __name__ == "__main__":
    app = ConfigEditor()
    app.mainloop()