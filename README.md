# WLE5 — Animatronic Robot Control System

WLE5 is an animation and control platform designed for lifelike animatronic characters (such as Wall-E). 
It combines an **ESP32-S3** microcontroller (handling eye animations, audio, motion control, communications, and onboard media management). 
Paired with a desktop companion app (**WLE5 Studio**) for creating and simulating animations as well as managing configurations and synchronizing files.


## Features

- **Kinematics Motion Engine**: calculating rampu up/down speeds for smooth motion at 50hz
- **Digital Twin Simulation**: Built-in 3D Pygame simulator that mirrors physical robot motions and constraints in real time.
- **Scripting & Keyframe Engine**: Human-readable timeline scripts for choreographing multi-joint motions,  speeds, and autonomous idle behaviors.
- **Dynamic Joint Configuration**: Configurable centralized joint definitions, servo pulse limits, and channel mappings 
- **Dual Display Eye Animations**: Eye graphics rendered at 20-40fps.
- **Integrated Audio Playback**: Smooth MP3/WAV playback 
- **Easy Sync**: One click synchronizing configurations, scripts, or medial files over Wi-Fi or USB.

## Hardware
The following ESP32-S3 board was selected because of its compact footprint, low cost, and wiring simplicity. It includes dual 1.28" round LCD displays, onboard audio (ES8311, amp, and speaker), 8MB PSRAM/16MB Flash, breakout connector for i2c/SPI/UART, and other peripherals (mic, card reader) for under $20.  Other ESP32-S3 boards can also be used.

Waveshare ESP32-S3 1.28inch Double Eye Round LCD AIoT Development Board
![DevBoard](docs/Pasted%20image%2020260826143745.png)


## Animation Studio
A multi-window interface designed for ease of use.

![Studio](docs/Pasted%20image%2020260827103029.png)





---

## Complete Documentation Index

- [**01. Quickstart & Operator Reference**](docs/01-quickstart.md) — 3-minute setup, essential studio buttons, and scripting cheat sheet.
- [**02. User Guide & Studio Manual**](docs/02-user-guide.md) — Step-by-step manual for WLE5 Studio, Joint Configurator, and Sync Manager.
- [**03. System Architecture**](docs/03-architecture.md) — FreeRTOS task partition, kinematics physics math, Python Studio modules, and binary payload specifications.
- [**04. Scripting & Joint Engine**](docs/04-scripting-and-joint-configuration.md) — Keyframe syntax, joint parameter dictionary, and virtual joints (100–118).
- [**05. Communication Protocols**](docs/05-communication-protocols.md) — Wire specifications for `0xAA` motion packets, `'W''L''E'` PSRAM burst sync, telemetry, and EdgeTX CRSF.
- [**06. Hardware & Wiring Guide**](docs/06-hardware-and-wiring.md) — Pinout diagrams, PCA9685 I2C connections, and power safety rules.
- [**07. RC Manual Control Design**](docs/07-rc-manual-control-design.md) — EdgeTX CRSF channel decoding, transmitter Lua menu, and ESP-NOW peer-to-peer radio link.

---

## Directory Structure

```
.
├── anims/                # Human-readable .wle animation and personality scripts
├── config/               # robot_master.json master joint calibration schema
├── docs/                 # Documentation, schematics, and design guides
├── firmware/
│   ├── esp32_main/       # ESP32-S3 robot controller firmware (Walle-double.ino)
│   └── esp32_remote/     # EdgeTX radio transmitter firmware and Gjoints.lua script
├── media/                # Source audio (.mp3, .wav) and image assets (.png, .jpg)
├── python/               # WLE5 Studio desktop application (Tkinter / Pygame)
└── tools/                # Compiled standalone executables (WLE5_Studio.exe)
```
