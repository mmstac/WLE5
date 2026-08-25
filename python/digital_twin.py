import math

class DigitalTwinEngine:
    def __init__(self, joint_config):
        self.JOINT_CONFIG = joint_config
        self.joints = {}
        self.accumulator = 0.0
        self.TICK_RATE = 1.0 / 50.0  # Strict 50Hz (20ms) physics tick to mirror the ESP32

        # Initialize the Master State Dictionary
        for j_name, cfg in self.JOINT_CONFIG.items():
            start_pos = float(cfg.get("r_init", 0.0))
            r_min = float(cfg.get("r_min", -180.0))
            r_max = float(cfg.get("r_max", 180.0))
            cmd_min = float(cfg.get("cmd_min", 500))
            cmd_max = float(cfg.get("cmd_max", 2500))
            
            # Standard PWM Mapping - Enforce 1:1 in config by making r_min == cmd_min
            norm = (start_pos - r_min) / (abs(r_max - r_min) or 1)
            setpoint = int(norm * 255)
            hw_pos = int(cmd_min + (setpoint * (cmd_max - cmd_min)) / 255)

            self.joints[j_name] = {
                'id': cfg["id"],
                'r_min': r_min, 'r_max': r_max,
                'cmd_min': cmd_min, 'cmd_max': cmd_max,
                
                'user_target': start_pos,        # Target in Degrees (for UI/TX)
                'current_position': start_pos,   # Current in Degrees (for 3D Model)
                
                'hw_current_pos': hw_pos,
                'hw_target_pos': hw_pos,
                'hw_current_vel': 0,
                
                'target_velocity': float(cfg.get("def_spd", 100)),
                'max_spd': float(cfg.get("max_spd", 255)),
                'max_acc': float(cfg.get("max_acc", 10)),
                
                'tx_required': False,
                'tx_speed': 0
            }

    def set_target(self, name, target, speed=None):
        """ All Inputs (WASD, Animations, UI) write ONLY to this method. """
        if name in self.joints:
            joint = self.joints[name]
            
            clamped_target = max(joint['r_min'], min(joint['r_max'], float(target)))
            new_speed = float(speed) if speed is not None else joint['target_velocity']

            if joint['user_target'] != clamped_target or joint['target_velocity'] != new_speed:
                joint['user_target'] = clamped_target
                joint['target_velocity'] = new_speed
                joint['tx_required'] = True
                joint['tx_speed'] = int(new_speed)
                
                norm = (clamped_target - joint['r_min']) / (abs(joint['r_max'] - joint['r_min']) or 1)
                setpoint = int(norm * 255)
                joint['hw_target_pos'] = int(joint['cmd_min'] + (setpoint * (joint['cmd_max'] - joint['cmd_min'])) / 255)

    def force_tx_all(self):
        """ Flags ALL joints to transmit their current state on the next tick """
        for state in self.joints.values():
            state['tx_required'] = True

    def get_tx_packets(self):
        packets = []
        for name, state in self.joints.items():
            if state['tx_required']:
                packets.append({
                    "id": state['id'],
                    "target": state['user_target'],
                    "speed": state['tx_speed']
                })
                state['tx_required'] = False
        return packets

    def update_physics(self, dt):
        self.accumulator += dt
        while self.accumulator >= self.TICK_RATE:
            self.accumulator -= self.TICK_RATE
            self._physics_tick()

    def _physics_tick(self):
        for name, state in self.joints.items():
            
            # Perform all math on the hardware PWM scale (e.g. 500-2500)
            distanceTo = int(state['hw_target_pos']) - int(state['hw_current_pos'])
            vel = int(state['hw_current_vel'])
            max_acc = int(max(1.0, state['max_acc']))
            max_spd = int(min(state['target_velocity'], state['max_spd']))

            if distanceTo == 0 and vel == 0:
                continue

            a_float = float(max_acc)
            d_float = float(abs(distanceTo))
            v_safe = int((-a_float + math.sqrt(a_float * a_float + 8.0 * a_float * d_float)) / 2.0)

            next_v = vel

            if distanceTo > 0:
                if vel < 0: next_v = vel + max_acc
                else:
                    next_v = vel + max_acc
                    if next_v > max_spd: next_v = max_spd
                    if next_v > v_safe: next_v = v_safe
                    if next_v < vel - max_acc: next_v = vel - max_acc
                    if next_v < 1: next_v = 1
            else:
                if vel > 0: next_v = vel - max_acc
                else:
                    next_v = vel - max_acc
                    if next_v < -max_spd: next_v = -max_spd
                    if next_v < -v_safe: next_v = -v_safe
                    if next_v > vel + max_acc: next_v = vel + max_acc
                    if next_v > -1: next_v = -1

            if abs(distanceTo) <= max_acc and abs(vel) <= max_acc * 2:
                next_v = distanceTo

            if distanceTo > 0 and next_v > distanceTo: next_v = distanceTo
            if distanceTo < 0 and next_v < distanceTo: next_v = distanceTo

            state['hw_current_vel'] = float(next_v)
            state['hw_current_pos'] += float(next_v)

            if distanceTo > 0 and state['hw_current_pos'] > state['hw_target_pos']:
                state['hw_current_pos'] = state['hw_target_pos']
            if distanceTo < 0 and state['hw_current_pos'] < state['hw_target_pos']:
                state['hw_current_pos'] = state['hw_target_pos']
                
            # THE DIGITAL TWIN BRIDGE: Map hardware pos back to degrees
            hw_range = state['cmd_max'] - state['cmd_min']
            if hw_range == 0: hw_range = 1
            norm = (state['hw_current_pos'] - state['cmd_min']) / hw_range
            state['current_position'] = state['r_min'] + (norm * abs(state['r_max'] - state['r_min']))