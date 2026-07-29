import re

class AnimationPlayer:
    def __init__(self, joint_config):
        self.keyframes = []
        self.current_time = 0.0
        self.duration = 0.0
        self.is_playing = False
        self.active_name = "None"
        self.current_state = {} 
        self.active_transitions = {}
        self.next_kf_index = 0
        
        self.joint_config = joint_config
        self.on_network_transmit = None

    def load_script(self, name, script_text):
        self.keyframes = []
        self.active_name = name
        self.current_time = 0.0
        self.is_playing = False
        self.active_transitions = {}
        self.next_kf_index = 0

        # FIXED: splitlines() automatically purges the \r carriage returns causing the Windows Tkinter bugs
        lines = script_text.splitlines()
        in_target_anim = False
        
        for line in lines:
            line = line.split("#")[0].strip()
            if not line: continue

            if line.lower().startswith("[anim:"):
                # Clean extraction of the name regardless of internal spaces or case
                anim_name = line.split(":", 1)[1].strip(" ]")
                in_target_anim = (anim_name.lower() == name.lower())
                continue
                
            if line.startswith("[") and not line.lower().startswith("[anim:"):
                in_target_anim = False
                
            if in_target_anim and line.startswith("@"):
                time_match = re.match(r'@([0-9.]+)s', line)
                if time_match:
                    time_val = float(time_match.group(1))
                    joints = re.findall(r'([a-zA-Z_]+)=([0-9.-]+)(?:,([0-9]+))?', line)
                    
                    joint_targets = {}
                    for match in joints:
                        j_name = match[0].lower() # Enforce lowercase matching
                        if j_name in self.joint_config:
                            j_id = self.joint_config[j_name]["id"]
                            target = float(match[1])
                            speed = int(match[2]) if match[2] else self.joint_config[j_name]["def_spd"]
                            
                            joint_targets[j_name] = {
                                "id": j_id,
                                "target": target,
                                "speed": speed
                            }
                    
                    if joint_targets:
                        self.keyframes.append({"time": time_val, "targets": joint_targets})

        if self.keyframes:
            self.keyframes.sort(key=lambda x: x["time"])
            # Ensure the duration matches the final keyframe timestamp
            self.duration = self.keyframes[-1]["time"] 

    def play(self, live_joint_states):
        if self.keyframes:
            self.current_time = 0.0
            self.is_playing = True
            self.next_kf_index = 0
            self.current_state = dict(live_joint_states)
            self.active_transitions = {}
            # FIXED: Removed the premature _apply_keyframe(0) trigger so timeline is respected

    def _apply_keyframe(self, kf_index):
        if kf_index >= len(self.keyframes): return
        kf = self.keyframes[kf_index]

        if self.on_network_transmit and kf["targets"]:
            self.on_network_transmit(kf["targets"].values())

        for joint_name, data in kf["targets"].items():
            start_val = self.current_state.get(joint_name, data["target"])
            target_val = data["target"]
            speed_param = data["speed"]
            
            # Safely utilize the new Range minimums and maximums
            config = self.joint_config[joint_name]
            total_range = abs(config.get("r_max", 100.0) - config.get("r_min", 0.0))
            if total_range == 0: total_range = 100.0
            
            normalized_speed = max(1, speed_param) / 255.0
            max_units_per_sec = total_range / 0.15
            actual_units_per_sec = max_units_per_sec * normalized_speed
            
            distance = abs(target_val - start_val)
            duration = max(0.05, distance / actual_units_per_sec)

            self.active_transitions[joint_name] = {
                "start": start_val,
                "target": target_val,
                "elapsed": 0.0,
                "duration": duration
            }

    def update(self, dt):
        if not self.is_playing: return self.current_state

        self.current_time += dt

        # Trigger keyframes naturally as the clock catches up to them
        while (self.next_kf_index < len(self.keyframes) and 
               self.current_time >= self.keyframes[self.next_kf_index]["time"]):
            self._apply_keyframe(self.next_kf_index)
            self.next_kf_index += 1

        finished_joints = []
        for joint, trans in self.active_transitions.items():
            trans["elapsed"] += dt
            progress = min(1.0, trans["elapsed"] / trans["duration"])
            smooth_progress = progress * progress * (3 - 2 * progress) 
            
            self.current_state[joint] = trans["start"] + (trans["target"] - trans["start"]) * smooth_progress

            if progress >= 1.0: finished_joints.append(joint)

        for j in finished_joints: del self.active_transitions[j]

        if self.current_time >= self.duration and not self.active_transitions:
            self.is_playing = False
            self.active_name = "None"

        return self.current_state