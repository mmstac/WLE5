import re

class AnimationPlayer:
    def __init__(self, joint_config):
        self.keyframes = []
        self.current_time = 0.0
        self.duration = 0.0
        self.is_playing = False
        self.active_name = "None"
        self.next_kf_index = 0
        
        self.joint_config = joint_config
        
        # New Callback: We will bind this to our Master Engine in main.py
        self.on_keyframe_triggered = None 

    def load_script(self, name, script_text):
        self.keyframes = []
        self.active_name = name
        self.current_time = 0.0
        self.is_playing = False
        self.next_kf_index = 0

        lines = script_text.splitlines()
        in_target_anim = False
        
        for line in lines:
            line = line.split("#")[0].strip()
            if not line: continue

            if line.lower().startswith("[anim:"):
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
                        j_name = match[0].lower()
                        if j_name in self.joint_config:
                            target = float(match[1])
                            speed = int(match[2]) if match[2] else self.joint_config[j_name]["def_spd"]
                            
                            joint_targets[j_name] = {
                                "target": target,
                                "speed": speed
                            }
                    
                    if joint_targets:
                        self.keyframes.append({"time": time_val, "targets": joint_targets})

        if self.keyframes:
            self.keyframes.sort(key=lambda x: x["time"])
            self.duration = self.keyframes[-1]["time"] 

    def play(self):
        if self.keyframes:
            self.current_time = 0.0
            self.is_playing = True
            self.next_kf_index = 0

    def update(self, dt):
        if not self.is_playing: return

        self.current_time += dt

        # Trigger keyframes as the clock catches up
        while (self.next_kf_index < len(self.keyframes) and 
               self.current_time >= self.keyframes[self.next_kf_index]["time"]):
            
            kf = self.keyframes[self.next_kf_index]
            if self.on_keyframe_triggered and kf["targets"]:
                self.on_keyframe_triggered(kf["targets"])
            
            self.next_kf_index += 1

        if self.current_time >= self.duration:
            self.is_playing = False
            self.active_name = "None"