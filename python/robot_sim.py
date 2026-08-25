import math
import time
from ursina import *
from ursina.shaders import lit_with_shadows_shader

class VirtualWalle:
    def __init__(self, joint_config):
        self.JOINT_CONFIG = joint_config
        self.is_blinking = False
        
        # --- URSINA ENVIRONMENT SETUP ---
        Entity.default_shader = lit_with_shadows_shader
        # Moved camera right (+2.0), up (+1.5), and rotated (Pitch 15, Yaw CW -15)
        camera.position = (0.7,0.8,-9.0)
        camera.rotation = (20, 30, 0)
        EditorCamera()

        
        # Disable default Ursina debug stats in the top right
        window.fps_counter.enabled = True
        window.entity_counter.enabled = False
        window.collider_counter.enabled = False
        window.exit_button.visible = False
        
        self.sun = DirectionalLight(y=2, z=3, shadows=True, rotation=(45, -45, 0))
        AmbientLight(color=color.rgba(120, 120, 120, 255))

        # Shifted X position from -0.85 to -0.65 to fit the new window aspect ratio
        self.servo_display = Text(text="Initializing...", position=(-0.65, 0.45), scale=1.2, color=color.white, background=True)
        # Moved log stream slightly right to x=0.25 so it fits perfectly
        self.command_log_display = Text(text="--- COMMAND STREAM ---\nWaiting for script...", position=(0.25, 0.45), scale=0.95, color=color.green, background=True)
        
       
        self.terminal_bg = Entity(parent=camera.ui, model='quad', color=color.color(0, 0, 0, .85), scale=(1.2, 0.08), position=(0, -0.46))
        self.terminal_input = InputField(parent=self.terminal_bg, y=0, scale=(0.95, 0.6), default_value='Type Command...', max_lines=1)
        self.terminal_bg.enabled = False
        self.terminal_input.enabled = False

        self._build_rig()

    def _build_rig(self):
        self.base_pivot = Entity(position=(0, 0, 0))
        dark_yellow = color.color(30, 0.9, 0.6)
        
        self.base_mesh = Entity(parent=self.base_pivot, model="cube", position=(0, -0.6, 0), scale=(1.50, 1.3, 1.35), color=dark_yellow)

        self.neck1_pivot = Entity(parent=self.base_pivot, position=(0, 0.1, 0.325))
        Entity(parent=self.neck1_pivot, model="cube", scale=(0.3, 0.58, 0.3), color=color.orange, origin_y=-0.5)
        Entity(parent=self.neck1_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.40, 0.05), rotation_z=90, origin_y=0.5, color=color.black)

        self.neck2_pivot = Entity(parent=self.neck1_pivot, position=(0, 0.58, 0))
        Entity(parent=self.neck2_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.35, 0.05), rotation_z=90, origin_y=0.5, color=color.black)
        Entity(parent=self.neck2_pivot, model="cube", scale=(0.25, 0.50, 0.25), color=color.orange, origin_y=-0.5)
        Entity(parent=self.neck2_pivot, model="cube", position=(0, 0.35, 0.175), scale=(0.25, 0.30, 0.35), color=color.orange)
        Entity(parent=self.neck2_pivot, model="cube", position=(0, 0.70, 0.35), scale=(0.25, 0.40, 0.25), color=color.orange)

        self.head_pivot = Entity(parent=self.neck2_pivot, position=(0, 0.90, 0.35))
        Entity(parent=self.head_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.35, 0.05), rotation_z=90, origin_y=0.5, color=color.black)
        Entity(parent=self.head_pivot, model="cube", position=(0, 0, 0), scale=(0.8, 0.05, 0.05), color=color.dark_gray)

        self.eye_left_pivot = Entity(parent=self.head_pivot, position=(0, 0, 0))
        Entity(parent=self.eye_left_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.15, 0.05), rotation_x=90, origin_y=0.5, color=color.black)

        self.eye_right_pivot = Entity(parent=self.head_pivot, position=(0, 0, 0))
        Entity(parent=self.eye_right_pivot, model=Cylinder(resolution=16), scale=(0.05, 0.15, 0.05), rotation_x=90, origin_y=0.5, color=color.black)

        self.eye_left_parts = self._build_eye_housing(self.eye_left_pivot, is_left=True)
        self.eye_right_parts = self._build_eye_housing(self.eye_right_pivot, is_left=False)

        self.left_arm_pivot = Entity(parent=self.base_pivot, position=(0.95, -0.1, 0))
        self.right_arm_pivot = Entity(parent=self.base_pivot, position=(-0.95, -0.1, 0))
        self._build_arm_mesh(self.left_arm_pivot, is_left=True)
        self._build_arm_mesh(self.right_arm_pivot, is_left=False)

    def _create_ring_mesh(self, inner_radius, outer_radius, resolution=36):
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

    def _build_eye_housing(self, parent_pivot, is_left=True):
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
        Entity(parent=housing, model=self._create_ring_mesh(0.160, 0.180, 36), position=(x_dir * 0.30, 0.025, -0.640), color=color.black)

        return {"pupil": pupil, "top_flap": top_flap, "bot_flap": bot_flap}

    def _build_arm_mesh(self, parent_pivot, is_left=True):
        x_dir = -1 if is_left else 1
        Entity(parent=parent_pivot, model=Cylinder(resolution=16), position=(-x_dir * 0.15, 0, 0), rotation_z=x_dir * 90, scale=(0.15, 0.30, 0.15), color=color.dark_gray)
        Entity(parent=parent_pivot, model="cube", position=(0, 0, -0.55), scale=(0.15, 0.25, 1.0), color=color.orange)
        Entity(parent=parent_pivot, model=Cylinder(resolution=16), position=(0, 0, -1.15), rotation_x=90, scale=(0.1, 0.25, 0.1), color=color.light_gray)
        Entity(parent=parent_pivot, model="cube", position=(0, 0, -1.35), scale=(0.18, 0.3, 0.25), color=color.gray)
        Entity(parent=parent_pivot, model="cube", position=(0, 0.11, -1.55), scale=(0.16, 0.05, 0.2), color=color.gray)
        Entity(parent=parent_pivot, model="cube", position=(0, -0.11, -1.55), scale=(0.16, 0.05, 0.2), color=color.gray)

    def blink_eyes(self):
        if self.is_blinking: return
        self.is_blinking = True
        for parts in [self.eye_left_parts, self.eye_right_parts]:
            parts["top_flap"].animate_scale_y(0.18, duration=0.1) 
            parts["bot_flap"].animate_scale_y(0.18, duration=0.1) 
            invoke(parts["top_flap"].animate_scale_y, 0.001, duration=0.1, delay=0.15)
            invoke(parts["bot_flap"].animate_scale_y, 0.001, duration=0.1, delay=0.15)
        invoke(self._reset_blink, delay=0.3)
        
    def _reset_blink(self):
        self.is_blinking = False

    # --- THE SSOT SYNC ---
    def sync_to_master(self, master_joints):
        """ Perfectly mirrors the absolute physics calculations from the Master Engine """
        def get_pos(j_name):
            return master_joints[j_name]["current_position"] if j_name in master_joints else 0.0

        if "yaw" in self.JOINT_CONFIG: self.head_pivot.rotation_y = get_pos("yaw")
        if "neck_base_pitch" in self.JOINT_CONFIG: self.neck1_pivot.rotation_x = get_pos("neck_base_pitch")
        if "neck_top_pitch" in self.JOINT_CONFIG: self.neck2_pivot.rotation_x = get_pos("neck_top_pitch")
        if "head_pitch" in self.JOINT_CONFIG: self.head_pivot.rotation_x = get_pos("head_pitch")
        if "left_eye" in self.JOINT_CONFIG: self.eye_left_pivot.rotation_z = get_pos("left_eye")
        if "right_eye" in self.JOINT_CONFIG: self.eye_right_pivot.rotation_z = get_pos("right_eye")
        
        if "left_arm_rot" in self.JOINT_CONFIG: self.left_arm_pivot.rotation_x = get_pos("left_arm_rot")
        if "right_arm_rot" in self.JOINT_CONFIG: self.right_arm_pivot.rotation_x = get_pos("right_arm_rot")

        if "v_eyelid" in self.JOINT_CONFIG and not self.is_blinking:
            val = get_pos("v_eyelid") / 100.0
            scale_val = lerp(0.001, 0.18, val)
            for parts in [self.eye_left_parts, self.eye_right_parts]:
                parts["top_flap"].scale_y = scale_val
                parts["bot_flap"].scale_y = scale_val

        self._update_glow_color(master_joints)

    def _update_glow_color(self, master_joints):
        if "v_glow_color" in master_joints:
            hue_val = master_joints["v_glow_color"]["current_position"]
            if hue_val == 0:
                c = color.rgba(40, 40, 45, 255) 
            elif hue_val >= 255:
                c = color.hsv((time.time() * 60) % 360, 1.0, 1.0) 
            else:
                mapped_hue = ((hue_val - 1) / 253.0) * 360.0
                c = color.hsv(mapped_hue, 1.0, 1.0) 
            
            self.eye_left_parts["pupil"].color = c
            self.eye_right_parts["pupil"].color = c