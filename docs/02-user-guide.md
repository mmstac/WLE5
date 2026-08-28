# WLE5 — User Guide & Studio Manual

**Target Audience:** Makers, Animatronic Designers, Operators, and Developers  
**Companion App:** WLE5 Animation Studio (`WLE5_Studio.exe` / `python/main.py`)

---

## 1. ESP32 Main Controller Installation

### 1.1 Flashing Firmware
1. Open `firmware/esp32_main/Walle-double.ino` in Arduino IDE.
2. Under **Tools**, configure the following board settings:
   - **Board**: `ESP32S3 Dev Module`
   - **PSRAM**: `OPI PSRAM` (or `QSPI PSRAM` depending on board revision)
   - **Flash Size**: `16MB (128Mb)`
   - **Partition Scheme**: `16M Flash (3MB APP/9.9MB FATFS)`
   - **Upload Speed**: `921600`
3. Required Libraries:
   - `TFT_eSPI` (configured for GC9A01 dual displays)
   - `Adafruit_PWMServoDriver`
   - `ESP32Servo`
   - `Audio` (ESP32-audioI2S) + bundled `src/` audio codec driver for ES8311
4. Connect via USB-C and flash `Walle-double.ino`, `z_eye_render.ino`, `z_sys_mgr.ino`, and `robot_config.h`.

### 1.2 First-Time Wi-Fi Setup
Wi-Fi (TCP port `4210`) is the primary link for wireless asset syncing and live joint jogging:
1. Open **WLE5 Studio** on your desktop.
2. Connect to the ESP32 via USB: enter your COM port (e.g., `COM9`) in the **LINK** field and click **CONNECT**.
3. In the menu, select **Toolbox → Wi-Fi Setup** and enter your 2.4 GHz network credentials (SSID and password).
4. Reboot the ESP32. On startup, the IP address will be displayed on the round LCD eye.
5. Type the IP address into the **LINK** field in WLE5 Studio and click **CONNECT** to establish the TCP connection on port `4210`.

> 💡 **Recovery / Safe Mode:** If needed, hold **GPIO0 low at boot** (the standard ESP32 "BOOT" button). This activates `safe_mode_active`, which freezes kinematics and graphics tasks and disables asset loading, allowing recovery of corrupted configs or files.

---

## 2. WLE5 Studio Workspace & Control Panel

Launch `WLE5_Studio.exe` from the `/tools` folder (or run `python python/main.py`). The application expects the directory structure of `/config`, `/anims`, and `/media` to be present.

<img src="Pasted%20image%2020260826191403.png" width="434">

### 2.1 Connection & Synchronization
- **LINK Field**: Enter either a serial COM port (e.g. `COM9`) or an IP address (e.g. `192.168.1.145`) and click **Connect**.
- **Safe Force Sync**: A successful connection triggers `safe_force_sync()` automatically so the robot's configuration is refreshed and synchronized.

### 2.2 Joint Manipulation & Controls
Joints are grouped by logical anatomical regions (*Head*, *Neck*, *Arms*, *Virtual*). Click any region header to collapse or expand it.

<img src="Pasted%20image%2020260826200947.png" width="431">

| Column / Control | Function |
|---|---|
| **POS** | Displays the current live position of the joint. |
| **KEYS** | Keyboard shortcuts for jogging values interactively (e.g. `A`/`D` for yaw, `W`/`S` for neck base pitch, `1`/`2` for eyelids). |
| **SET** | The desired setpoint linked to the Script Editor. Selecting a line in the Script Editor copies all commands in that line to `SET`. |
| **`<PUSH` Button** | Sends the current `SET` values to `POS`. |
| **`SIM>` Button** | Copies `POS` values back to `SET` for joints where a value is already present (or type `0` to force copy). |
| **SPD** | Commanded slew speed (default speed used if omitted). |
| **`>>SIM<<` / `<LIVE>` Toggle** | Master telemetry & live-arm switch. In `>>SIM<<`, you jog joints and preview animations in simulation with no hardware commands sent. In `<LIVE>`, outgoing `0xAA` motion packets stream directly to the physical servos and displays. |

*(Note: Joints highlighted in grey in the studio list are not visually simulated in the Pygame viewport).*

---

## 3. Script Editor & Animation Workflow (Toolbox → 📝)

Select **Script Editor** from the **Toolbox** dropdown on the main control panel.

<img src="Pasted%20image%2020260826202044.png" width="457">

### 3.1 Writing Animation Scripts
Animations and autonomous "personality" behaviors are authored in plain text (`.wle` / `.txt`) in `/anims`:
- Each script command starts with an absolute timestamp (e.g., `@1.0s`) followed by target joint values (`yaw=40 head_pitch=-15,10`).
- Target values are in real-world physical units (degrees, percentages, or enum values).
- The speed parameter (`[target],[speed]`) is optional and slows down movement.
- In the Script Editor, pressing **ADD LINE TO SCRIPT** automatically generates a command line from the current `SET` columns.

### 3.2 Testing Scripts
1. Select a loaded script from `/anims`.
2. Choose the animation name in the **Target Anim** dropdown.
3. Click **TEST IN SIM** to preview physical motion in the digital twin simulator.
4. If the `<LIVE>` toggle is active, the script commands stream simultaneously to the physical robot.

---

## 4. Joint Configuration Editor (Toolbox → ⚙️)

Open **Toolbox → Configure Joints** to edit `robot_master.json` (`config_editor.py`).

<img src="Pasted%20image%2020260826200813.png" width="505">

- Modify software ranges (`r_min`, `r_max`, `r_init`), hardware servo pulse limits (`cmd_min`, `cmd_max`), hardware channel mappings, control types, default speeds, and acceleration limits.
- Saving automatically regenerates:
  1. `robot_config.h` (C++ virtual joint constant declarations)
  2. `config.bin` (compact binary payload ready for flashing/syncing)

For a detailed dictionary of all parameters, see [**Scripting & Joint Configuration**](04-scripting-and-joint-configuration.md).

---

## 5. Sync & Media Manager (Toolbox → 🔄)

The **Sync Manager** handles media transcoding and 1-click delta synchronization between your PC and the ESP32.

<img src="Pasted%20image%2020260826200907.png" width="391">

### 5.1 Operating Steps for Syncing
1. **Open Sync Manager**: Click **Toolbox → 🔄 Sync Manager** from the Studio menu.
2. **Optimize Media (Optional)**: If you added new audio or image files to your `/media` folder, click **Optimize Media**. Studio will automatically convert audio files into optimized MP3 format and eye graphics into display-ready RGB565 bitmaps.
3. **1-Click Smart Sync**: Click **Sync All** or **Delta Sync**. Studio automatically:
   - Compiles your latest joint configurations, animation scripts, and idle personality states.
   - Compares content hashes with the robot.
   - Uploads only modified files to the robot's internal flash memory over Wi-Fi or USB.

### 5.2 Files Managed During Sync
- **Joint Configuration** (`config.bin`): Hardware calibration, servo pulse limits, and channel mapping.
- **Animation Scripts** (`anims.bin`): All compiled keyframe sequences from `/anims`.
- **Idle State Machine** (`states.bin`): Autonomous "Alive" behaviors, timing, and randomness weights.
- **Media Files** (`/img`, `/audio`): Custom eye graphic sprites and MP3 sound clips stored on internal flash.

*(For detailed binary file specifications, FreeRTOS memory staging, and PSRAM transfer mechanics, see [**System Architecture**](03-architecture.md) and [**Communication Protocols**](05-communication-protocols.md)).*

---

## 6. Troubleshooting & Diagnostics

| Symptom | Probable Cause | Action |
|---|---|---|
| **Cannot connect over USB** | Incorrect COM port or missing USB-UART driver | Check Device Manager for CP210x/CH340 driver; ensure baud rate is set to 115,200. |
| **Wi-Fi connection fails** | 5 GHz network selected or weak signal | ESP32-S3 only connects to **2.4 GHz** Wi-Fi networks. Verify SSID/password via Toolbox. |
| **Servos buzz or stall** | Power rail current limit or missing common ground | Servos require 5V/6V (3A–5A). Ensure ESP32 GND and Servo PSU GND are tied together. |
| **Displays remain blank** | SPI pin configuration or safe mode | Verify `TFTespi_config.h`. If Safe Mode is enabled, displays will stay in idle state. |
| **Audio playback cuts off** | Bitrate/sample rate mismatch | Re-run Media Optimization in Studio to ensure 16 kHz / 24 kHz MP3 conversion. |
| **Boot loop / continuous reset** | Corrupt configuration in flash | Hold **BOOT** button (GPIO0) during power-up to enter **Safe Mode**, then re-run Smart Sync. |
