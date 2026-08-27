# Scripting and Joint configuration

## 1. Scripting Syntax

The WLE5 parser processes scripts (`.wle` / `.txt`) containing three primary block types: Global Configuration, Autonomous Idle States, and Explicit Animations. They can be saved in multiple/separate files or a single file, but should be all kept in the /anims directory.

```wle
[Config]
IdleTimeout = 5.0

[State: Alive]
Interval = 2.0 - 5.0
Play: look_around      w:40   v:15   c:10
Play: curious_tilt     w:60   v:10   c:5
Play: blink            w:80   v:0    c:2

[Anim: look_around]
@0.0s   yaw=20,60       head_pitch=80,40    v_eyelid=100,255
@0.15s  v_eyelid=0,255
@2.0s   yaw=-20,50      v_aperture=50
@4.0s   yaw=0,40        head_pitch=42.5,40  v_aperture=100
```

### Syntax Rules & Block Definitions

1. **Global Configuration Block (`[Config]`)**
   * **`IdleTimeout = <seconds>`**: Period of inactivity in seconds before entering autonomous mode.

2. **Idle State Block (`[State: <StateName>]`)**
   * **`Interval = <min_sec> - <max_sec>`**: Time window between random animation selection.
   * **`Play: <anim_name>  w:<weight>  v:<var%>  c:<cooldown_sec>`**:
     * `w:<weight>`: Selection probability weight.
     * `v:<variance%>`: Speed/timing variance percentage.
     * `c:<cooldown_sec>`: Cooldown before repeat.

3. **Animation Block (`[Anim: <AnimName>]`)**
   * **`@<time>s   <joint>=<target>[,<speed>]`**:
     * `@<time>s`: Keyframe timestamp in seconds.
     * `<target>`: Target value within joint's script range (`r_min` to `r_max`).
     * `<speed>` (optional): Speed byte (`0-255`). If omitted, uses default safe speed (`def_spd`).

	The script syntax is meant to be simple and easy to read. Just knowing the joint names will allow an animation sequence to be easily created. Each script command should start with the keyframe time (ie. @1.0s) followed by a list of joint target specifications (yaw=40  head_pitch-15,10). The target value is the defined "real world" range for each joint, so this maybe the rotational position or whatever value makes the most sense to the animator. The speed is optional, but is useful for slowing down motions.
---
## 2. Idle ("Alive") behavior at runtime

When there has been no live input for `idle_timeout_sec`, and the current idle state has
`active_idle_state > 0`, `loop()` periodically (per each state's configured `Interval`)
performs a weighted-random pick among that state's still-eligible `Play:` entries
(eligible = not on cooldown), then plays that animation exactly as if it had been
triggered manually. This is the same keyframe playback path used for any other animation
— idle behavior is just an automatic *selector*, not a separate playback engine.

Layered on top of (and independent from) the named idle states, `KinematicsTask` always
runs two small procedural generators directly on virtual joints, regardless of idle state:

- **Autonomous blink** (`V_EYELID`) — random interval (6–10 s) close/hold/reopen cycle.
- **Aperture "focus hunt" twitch** (`V_APERTURE`) — random target within a dilation range,
  followed by a partial backtrack at half speed, on a 4–9 s random interval.

Both are toggled per-joint via an `auto_mode_active[]` flag, so live control of a joint
(e.g. someone jogging the eyelid manually) can suppress the autonomous generator for that
joint without affecting the others.

# 3. Joint Configuration Reference

Every physical or "virtual" degree of freedom is a **joint**, described by a `BinJointConfig` record (packed struct, mirrors `config/robot_master.json`):
The script uses human-readable physical value range  (e.g., `90 degrees`) which are automatically mapped to the command signal equivalent (e.g. servo PWM pulse) in each joint configuration.

All parameters are defined via the IDE's Config Editor and stored in `robot_master.json` / `config.bin`.

## 3-1. Hardware Control Types (`Ctrl Type`)
Defines the internal driver and frequency used to output the physical signal.
This can be used to control servos, motor drivers, LEDs, or mosfet switches.
`control_type` selects the output driver used by `updateJointPhysics()`:

| `control_type` | Output                                                                           | `hardware_address` meaning          |
| -------------- | -------------------------------------------------------------------------------- | ----------------------------------- |
| 0              | Direct `ESP32Servo` pin, `writeMicroseconds()`                                   | GPIO pin (0–5, six direct channels) |
| 1              | `PCA9685.setPWM()`, standard hobby-servo PWM                                     | PCA9685 channel 0–15                |
| 3              | `PCA9685.setPWM()`, full pwm, raw 12-bit linear value (dimming/LED-style output) | PCA9685 channel 0–15                |
| 4              | `PCA9685.setPWM()`, binary on/off (full-on / full-off)                           | PCA9685 channel 0–15                |
| 5              | ESP32 native `ledcWrite()` PWM (motor driver)                                    | GPIO pin                            |
Note that the PCA9685 is set to 50hz for matching to hobby servos. For driving motors, a higher PWM frequency may be desired, hence the use of the ESP32 ledc (type 5).

## 3-2. Parameter Dictionary

### Addressing

- **`ID`**: Internal system identifier (0-255). Must be unique.
- **`Region`**: UI sorting integer used to group joints in the IDE.
- **`HW Addr`**: The physical output pin. Maps to a PCA9685 port (0-15) or an ESP32 GPIO pin, depending on the `Ctrl Type`.
### Software Range (`R_` Parameters)
The human-readable bounds used in the IDE and animation scripts (e.g., degrees or percentages).

- **`R_Min`**: Minimum software limit (e.g., `-90.0`).
- **`R_Max`**: Maximum software limit (e.g., `90.0`). _Note: Setting this to 101.0 for Virtual Joints allows sending a `255` magic flag to trigger autonomous modes._
- **`R_Init`**: Default starting position on boot.
### Hardware Command Range (`Cmd_` Parameters)
The absolute physical signals sent to the drivers. The engine automatically maps the `R_` range to this `Cmd_` range via linear interpolation.

- **`Cmd_Min`**: The physical output mapped to `R_Min`. (Pulse width in µs for servos, or 0-4095 duty cycle for motors).
- **`Cmd_Max`**: The physical output mapped to `R_Max`.
- **`Cmd_Init`**: The immediate hardware lock signal sent on boot before software initializes.
### Kinematics & Physics Limits
The engine calculates trajectories 50 times per second. These constraints cannot be overridden by scripts.

- **`Def_Spd`**: The baseline velocity applied if an animation script omits a speed value.
- **`Max_Spd`**: Absolute velocity cap. The physics engine will forcibly clamp any script requesting a speed higher than this.
- **`Max_Acc`**: The smoothing/easing factor.
    - `1 - 15`: Heavy S-curve acceleration (smooth, organic, safe for heavy parts).
    - `255`: Instantaneous acceleration (robotic snapping, instant throttle).

```c
struct __attribute__((packed)) BinJointConfig {
    uint8_t id;
    char    name[32];
    uint8_t region;            // logical grouping (head, arm, etc.)
    uint8_t control_type;      // how the joint is driven, see table below
    int8_t  hardware_address;  // pin / PCA9685 channel
    float   r_min, r_max, r_init;      // real-world range (deg, or arbitrary units)
    int16_t cmd_min, cmd_max, cmd_init; // raw command range (e.g. servo µs)
    uint8_t def_spd, max_spd, max_acc;  // motion profile limits
};
```

## 4. Virtual Joints (control_type=2)
These will be used to control the eye animations, audio playback, as well as certain system settings.
The IDs **100 and up** will be used and are defined in `robot_config.h`. 

These never reach `updateJointPhysics()` for physical output — they're
intercepted in `pushCommandToEngine()` and instead drive eye-rendering parameters, trigger
audio playback, or toggle engine modes. They use the exact same 3-byte command wire format
as physical joints, which is what lets one uniform protocol control both the robot's body
and its face/voice.

## 4-1. Virtual Joint Parameter Reference Guide (`0–100` Scale)

All virtual joints accept target values from **`0` to `100`** (percentages, hue angles, indices, or positions). Python scales these targets to raw MCU bytes (`0–255`) automatically.

### Speed Parameter (`[Speed_Value]`) Behavior
* **Omitted**: Falls back to `def_spd` in configuration.
* **1 to 254**: Calculates smooth acceleration and transit speed (`50` = slow fade/move, `200` = rapid).
* **255 (Instant Snap)**: Bypasses acceleration math; immediately snaps value on the next frame.

### Joint Parameter Definitions

| Category            | Joint Name      | Target.Value Range.Meaning..................                                            | Speed Behavior                      | Function Description                  |
| :------------------ | :-------------- | :-------------------------------------------------------------------------------------- | :---------------------------------- | :------------------------------------ |
| **Visual Graphics** | `v_eyelid`      | **0 to 101**<br>• 0=Open, 100=Closed<br>• 101 = Auto blink                              | 0 to 255                            | Coordinates  eyelids'/blink           |
| **Visual Graphics** | `v_aperture`    | **0 to 101**<br>• 0=Open, 100=Closed<br>• 101 = Auto twitch                             | 0 to 255                            | Controls eye dilation size.           |
| **Visual Graphics** | `v_glow_color`  | **0 to 101**<br>• `0` = Glow Off<br>• 1 to 254 = Color Wheel<br>• 101 = Rainbow Cycling | `1 to 254` <br>`255` (Instant snap) | Adjusts the background iris glow hue  |
| **Visual Graphics** | `v_glow_pulse`  | **0 to 100**<br>• `0` = Static 80% bright<br>• `1 to 100` = Brightness                  | `0 to 255` (Transition)             | Sets iris glow brightness level       |
| **Visual Graphics** | `v_img_select`  | **0 to 255** <br>Select image index                                                     | 255                                 | Select image to fade in               |
| **Visual Graphics** | `v_img_opacity` | **0 to 100**<br>• `0` = Invisible<br>• `100` = Solid                                    | 0 to 255<br>(Fade speed)            | Sets opacity of selected image        |
| **Visual Graphics** | `v_gaze_x`      | **0 to 100**<br>• `0` = Left<br>• `50` = Center<br>• `100` = Right                      | 0 to 255                            | Controls horizontal pupil gaze offset |
| **Visual Graphics** | `v_gaze_y`      | **0 to 100**<br>• `0` = Up<br>• `50` = Center<br>• `100` = Down                         | 0 to 255                            | Controls vertical pupil gaze offset   |
| **Asymmetry Link**  | `v_asymmetry`   | **0 or 1**<br>• `0` = Linked<br>• `1` = Asymmetric Mode                                 | 255                                 | Enable separate eye rendering         |
| **Asymmetric Eye**  | `v_r_eyelid`    | **0 to 100**                                                                            | 0 to 255                            | Right eye eyelid closure percentage   |
| **Asymmetric Eye**  | `v_r_gaze_x`    | **0 to 100**                                                                            | 0 to 255                            | Right eye horizontal gaze             |
| **Asymmetric Eye**  | `v_r_gaze_y`    | **0 to 100**                                                                            | 0 to 255                            | Right eye vertical gaze               |
| **System Command**  | `v_audio_play`  | 0 to 255<br>select audio index<br>• `255` = Stop Audio                                  | Speed = Volume                      | Play audio file                       |
| **System Command**  | v_play_anim     | **0 to 255**<br>Play animation index                                                    | 255                                 | Play animation                        |
| **System Command**  | `v_idle_state`  | **0 to 255**<br>• `0` = Idle Engine Off<br>Select idle state index                      | 255                                 | Set Idle State behavior               |

---

# 4-2. How the Asymmetry Toggle Works

By default, the C++ `Eye_render.ino` engine reads a single set of rendering variables (`v_gaze_x`, `v_gaze_y`, `v_eyelid`) and mirrors them identically across both GC9A01 circular displays.

When `v_asymmetry=100,255` is transmitted:
1. The engine flips a master C++ flag (`isAsymmetric = true`).
2. The right screen instantly detaches from default channels and routes rendering calculations to designated "right eye" channels (`v_r_gaze_x`, `v_r_gaze_y`, `v_r_eyelid`).
3. Left screen continues listening to standard channels (`v_gaze_x`, `v_gaze_y`, `v_eyelid`).

### Asymmetric Wink & Chameleon Gaze Example
```wle
[Anim: Asym_Test]
# 1. Turn on the asymmetry switch (Speed 255 = instant)
@0.0s   v_asymmetry=100,255

# 2. Eyes look in opposite directions (Left looks hard left, Right looks hard right)
@0.1s   v_gaze_x=0,100    v_r_gaze_x=100,100

# 3. Wink the right eye (Snap right eyelid shut, keep left eye open)
@1.5s   v_eyelid=0,255    v_r_eyelid=100,255

# 4. Open right eye, snap gaze back to center (50), and relink screens
@3.0s   v_r_eyelid=0,100  v_gaze_x=50,255  v_r_gaze_x=50,255
@3.5s   v_asymmetry=0,255
```
