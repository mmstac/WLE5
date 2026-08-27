# User Guide

## 1. ESP32 Main Controller Installation

1. Flash the ESP32-S3 firmware
	Using the Arduino IDE, connect to the ESP32-S3. Flash the walle-double.ino, z_eye_render.ino, z_sys_mgr.ino, and robot_config.h (contains virtual joint settings) with the libraries it includes: `TFT_eSPI`, `ESP32Servo`, `Adafruit_PWMServoDriver`,`Audio`, plus the bundled `src/` audio codec driver.
	
2. To connect via wifi (recommended for larger file transfers) you will need to do the following:
		a. Open WLE5 Studio on your desktop and connect to the ESP32 via USB
		b. Enter the COM port number (ie 'COM9')in the LINK box and click CONNECT
		c. Clilck on the TOOLBOX menu and select Wi-Fi Setup and enter your wifi credentials
		d. Reboot the ESP32 and note the IP address displayed on the screen
		e. Type the IP address ain the LINK field and click CONNECT. This will establish a TCP connection on port 4210.

	**Recovery / safe mode:** if needed, hold GPIO0 low at boot (the standard ESP32 "BOOT" button) sets `safe_mode_active`, which freezes the kinematics/graphics tasks and disables asset loading.


## 2. WLE5 Studio
Run wle5_studio.exe from the /tools folder. It expects the directory structure of /config, /anims, and /media to also be present (this can be copied from the /release folder).

# Control Panel
The main control panel for connecting to the ESP32, monitoring/updating current joint positions, and launching maintenance screens.

![[Pasted image 20260826191403.png|434]]
# Connect to ESP32-S3
- Type the COM port (ie. 'COM9') into the LINK field to connect via USB or the IP address of the ESP32 to connect via wifi.  Click **Connect**, a  successful connect triggers `safe_force_sync()` automatically so the robot's config is refreshed and synced

# Manipulate Joints
Joints are listed by region, you can collapse or expand them by clicking on it.
The POS column shows the current position of the joint. Some joints will have keyboard shortcuts for jogging their values (keys).
The SET column is the desired set point and this can be linked to the script editor. 
Selecting a line in the script editor will copy all the commands in that line. You can use the '<PUSH' button to send the SET values to the current POS. The 'SIM>' button copies the POS to the SET column, but only for joints where there is already a value (you can type in 0 to force the copy). In the script editor, the SET values can automatically create a command line using the ADD LINE TO SCRIPT button.

SPD : The desired travel speed (default speed will be used if not specified)

The simulator will animate and move with the changes in POS values. Note that not all joints are shown in the simulator (those highlighted in grey are not simulated).
![[Pasted image 20260826200947.png|431]]

To update the ESP32 simultaneously, the command stream  must be enabled by toggling :
- **`>>SIM<<` / `<LIVE>` toggle**: this is the telemetry/live-arm switch
  (`CommManager.toggle_telemetry`). In `>>SIM<<` you can jog joints and preview
  animations against the **digital twin** (`digital_twin.py`) with zero physical
  movement or wire traffic. Flipping to `<LIVE>` arms outgoing `0xAA` frames to the
  actual robot and starts the telemetry heartbeat watchdog.

# Writing scripts
Animations and autonomous "personality" behavior are authored as plain text
(`anims/mster_script.txt`), edited live in WLE5 Studio, simulated, tested, and compiled to binary blobs the robot loads from flash. This doc covers the text format, the compiled format, and how the runtime picks what to play when nobody's driving it.

The script syntax is meant to be simple and easy to read. Just knowing the joint names will allow an animation sequence to be easily created. Each script command should start with the keyframe time (ie. @1.0s) followed by a list of joint target specifications (yaw=40  head_pitch-15,10). The target value is the defined "real world" range for each joint, so this maybe the rotational position or whatever value makes the most sense to the animator. The speed is optional, but is useful for slowing down motions. 
For more details refer to 03-scripting-and-joint-configuration

# **Script Editor** (Toolbox → 📝)
Select the SCRIPT EDITOR from the TOOLBOX dropdown on the main control panel.
![[Pasted image 20260826202044.png|457]]

# Testing scripts
Load a script file (.wle or .txt) from /anims, select the animation script name you wish to test in the Target Anim dropdown and click the TEST IN SIM button.
If the LIVE toggle is also enabled, the script commands will be streamed to the robot.

# Configure Joints (Toolbox → ⚙️)
Add or modify joint settings including ranges, servo limits, hardware channel mapping, control type, speed/accel limits
 Saving  regenerates `robot_config.h` (virtual joint IDs) and `config.bin` which should be synced with the ESP32 (see below).
 For more details refer to 03-scripting-and-joint-configuration
 Edit `robot_master.json`  (`config_editor.py`). 

![[Pasted image 20260826200813.png|505]]


# Sync Manager (Toolbox → 🔄)
  runs `run_smart_sync()` — queries the robot's current
Allows for adding media files and automatically syncs files and configurations between the desktop and the ESP32
![[Pasted image 20260826200907.png|391]]
# Adding image and audio files
- **Media**: `optimize_media.py` transcodes source audio/images into the compact formats
  the robot expects (requires `ffmpeg` on the PC) before `media_sync.py` pushes them.

* Audio files will be automatically indexed and converted to 16khz mp3 files for saving space*
	(due to a bug in the mp3 decoding library, audio files longer than 12s will be converted to 24khz for smooth playback)
* Image files will be automatically indexed and converted to RGB565 234x234 binary image file*

# Compiling and syncing script/config files

`wle_compiler.py` turns the authored assets into three binary files the firmware
memory-maps into its runtime tables, and pushes them over the PSRAM asset-transfer
protocol (`0x02`, see [02-communication-protocols.md](04-communication-protocols.md)):

| File | Header magic | Contents |
|---|---|---|
| `config.bin` | `"WLEC"` | version(u32) + joint count(u8) + `BinJointConfig[]` — the joint/hardware map |
| `anims.bin` | `"WLEA"` | content-hash(u32) + animation count(u8) +, per animation: name(32B), keyframe count, then packed `BinKeyframe`/`BinCommand` records |
| `states.bin` | `"WLES"` | `idle_timeout_sec`(u32) + state count(u8), then per state: id, interval min/max, and its weighted list of `(anim_name, weight, variance, cooldown)` entries |

`run_smart_sync()` is the "smart" part: before uploading, it queries the robot's current
`config.bin`/`anims.bin` version via the `0xBB`/`0xCC` sub-headers and only re-uploads
files that are actually stale, rather than always pushing everything.

On the firmware side, each file's loader (`loadHardwareConfig`, `loadAnimations`,
`loadIdleStates` in `z_sys_mgr.ino`) validates the 4-byte magic, then rebuilds the
corresponding in-RAM table (`ROBOT_CONFIG[]`, `activeAnimations[]`, `idle_actions[]`),
freeing any previously-allocated PSRAM buffers first.














The Sync & Media Manager




## 3. The EdgeTX Lua "TOC" menu (existing radio-side feature)

Independent of Studio, the remote ESP32 wired into the radio's CRSF bus lets a user browse
and play animations/audio/images and edit joint calibration directly from the radio
screen, via `Gjoints.lua` running as an EdgeTX "Tools" script. This is a
configuration/browsing UI, not a live motion controller — see
[02-communication-protocols.md](04-communication-protocols.md) §4 for the protocol, and
note that in this snapshot the remote ESP32 answers from seeded test data rather than the
real robot's asset list (an open wiring gap, discussed in
[05-rc-manual-control-design.md](05-rc-manual-control-design.md)).

## 4. Manual RC control (in development)

Live, stick-driven manual control from the radio isn't wired up yet. See
[05-rc-manual-control-design.md](05-rc-manual-control-design.md) for the current state and
the proposed design.
