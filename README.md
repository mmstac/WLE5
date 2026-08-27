# WLE5 — Animation Studio and Robot Engine

WLE5 is a compact platform for animating a robot/animatronic character (like Wall-E).
The robot brain will be handled by a single ESP32-S3 which provides eye animations, audio, motion control, communications, and onboard media management.
The desktop animation studio is used for a) configuring the robot, b) creating, testing and simulating animations, and c) synchronizing all data with the robot..
The link between the ESP32 and the animation studio is via USB or wifi, and provision for additional remote control devices using wifi or a second ESP32 connected to an EdgeTX radio controller.

The platform supports 
* dynamic joint configurations (no need to recompile or reflash firmware.)
* idle behavior and animations running from simple scripts
* motion control managed by kinematics engine running at 50hz calculating ramp up/down based on joint speed/acceleration settings
* smooth mp3/wav audio playback
* dual display symmetric or asymmetric eye animations
* loading and storage of all media files on the ESP32


## MAIN CONTROLLER
The following ESP32-S3 board was selected because of its compact footprint, low cost, and wiring simplicity. It includes dual 1.28" round LCD displays, onboard audio (ES8311, amp, and speaker), 8MB PSRAM/16MB Flash, breakout connector for i2c/SPI/UART, and other peripherals (mic, card reader) for under $20.  Other ESP32-S3 boards can also be used.

Waveshare ESP32-S3 1.28inch Double Eye Round LCD AIoT Development Board
![[Pasted image 20260826143745.png|199]]






## STUDIO INTERFACE
![[Pasted image 20260827103029.png]]


## Contents

| Doc | Covers |
|---|---|
| [01-architecture.md](01-architecture.md) | Hardware, firmware task layout, joint/animation engine, PC-side app structure |
| [02-communication-protocols.md](02-communication-protocols.md) | Every wire protocol in the system today: TCP/USB/UDP live command channel, PSRAM file-transfer protocol, telemetry heartbeat, and the CRSF "TOC" config protocol used by the EdgeTX Lua script |
| [03-animation-authoring.md](03-animation-authoring.md) | The `.wle`/master-script animation format, compiler, and idle-state behavior engine |
| [04-usage-guide.md](04-usage-guide.md) | Getting the robot running: flashing, Wi-Fi setup, WLE5 Studio workflow, syncing media/animations, live jogging |
| [05-rc-manual-control-design.md](05-rc-manual-control-design.md) | **In development.** The second ESP32 ("RC TX") that reads CRSF channels from an EdgeTX radio and will drive the robot live over ESP-NOW. Documents what exists today and proposes the ESP-NOW packet design for the missing piece. |
