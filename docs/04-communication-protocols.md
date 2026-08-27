# Communication Protocols

The main link for syncing data between the desktop studio and the ESP32 will be via TCP over wifi. The USB serial link is needed for the initial wifi setup, and can also be used for syncing although it will be slower than wifi for larger files. For commanding the ESP32, UDP and ESP-NOW have been provisioned to offer a flexibility of adding various Remote Control devices.

The main ESP32 exposes the **same command surface** over three transports, all handled by
one parser (`processStream()` in `z_sys_mgr.ino`, called for both the active TCP client and
`Serial`), plus a fourth transport (`WiFiUDP`) that speaks a subset of the same framing
directly in `loop()`.

| Transport | Endpoint | Used for |
|---|---|---|
| USB Serial | 115200 baud | Same protocol as TCP; used when Wi-Fi isn't available/desired |
| TCP | port `4210` | Primary link for WLE5 Studio (live jog, sync, telemetry) |
| UDP | port matching `udp` listener | Fire-and-forget live joint commands only (0xAA frame, no ACK/telemetry) |
| CRSF (wired serial, 400 kbaud) | between EdgeTX radio and the **remote** ESP32 | TOC/joint config query protocol (realm `0x50`) — separate device, see §4 |
| ESP-NOW *(planned)* | main ESP32 ↔ remote ESP32 | Manual joint control from the radio — see [05-rc-manual-control-design.md](05-rc-manual-control-design.md) |

## 1. Live joint command packet (`0xAA`)
The command packet was designed to be compact, utilizing a 2-byte header plus 3-bytes per joint target (up to 16).
Used on **TCP, USB Serial, and UDP** identically. This is the hot path — the frame the
robot receives many times a second while it's being live-jogged from WLE5 Studio.

```
Byte 0        : 0xAA                     (frame header)
Byte 1        : count                    (0–16 commands in this frame)
Bytes 2..N    : count × 3-byte commands:
                  [0] joint_id  (uint8, 0–255; 100–118 are "virtual" joints)
                  [1] setpoint  (uint8, 0–255 normalized target position)
                  [2] speed     (uint8, 0–255; 255 = snap instantly)
```

Receiving a command for a joint cancels any animation currently driving that joint
(`active_anim_id` is cleared) — live input always takes priority. `comm_link.py`
(`CommManager.send_packets`) is the PC-side producer: it clamps each joint's engineering
value to its configured range, normalizes to a byte, and batches up to 16 commands per
frame.

`CommManager.send_play_command()` reuses this exact frame to trigger an animation by name,
by targeting the virtual joint `V_PLAY_ANIM` (116) with the animation's numeric ID as the
setpoint.

## 2. File Sync/Maintenance ('W' 'L' 'E')

TCP and USB Serial only (not UDP). A 3-byte ASCII preamble `W`(0x57) `L`(0x4C) `E`(0x45)
routes into a secure sub-protocol used for anything beyond live motion: firmware asset
sync, manifests, and Wi-Fi provisioning. All multi-byte integers are little-endian.

| Sub-header | Direction | Purpose |
|---|---|---|
| `0x02` | Studio → robot | **PSRAM asset transfer** (see below) |
| `0xBB` | Studio → robot | Query `config.bin` version (for "is my joint config up to date?" checks) |
| `0xCC` | Studio → robot | Query `anims.bin` content hash/version |
| `0xEE 0x01` | Studio → robot | Request a manifest of files under `/img` and `/audio` on the robot's flash, terminated by `END_OF_MANIFEST` |
| `0xEE 0x05` | Studio → robot | Delete a named file from flash |
| `0xEE 0x06` | Studio → robot | Free cached image buffers and reload all media assets |
| `0xFF 0x01` | Studio → robot | **Push Wi-Fi credentials** (SSID/password), robot reboots after ACK |

### 2.1 File transfer (`0x02`)

```
'W' 'L' 'E' 0x02
uint8   file_type        (see table below)
uint32  expected_size     (payload byte count, ≤ 4 MiB — PSRAM safety limit)
uint32  expected_crc      (CRC32 of payload)
char[64] filename         (null-terminated target path)
--- robot replies 0x01 (ACK) once a PSRAM buffer of expected_size is allocated ---
<expected_size bytes of file payload, streamed>
--- robot validates CRC32, writes to FFat at filename, calls processCompletedFile() ---
```

`file_type` values dispatch post-write handling in `processCompletedFile()`:

| `file_type` | File | Effect on ACK |
|---|---|---|
| Joint config | `config.bin` | Reloads `ROBOT_CONFIG[]` / `engine_states[]` (`loadHardwareConfig`) |
| Idle-state table | `states.bin` | Reloads idle "Alive/Shifty/Sleepy…" behavior weights (`loadIdleStates`) |
| Animation script | `anims.bin` | Reloads compiled animations (`loadAnimations`) |
| Image asset | media file | Reloads all cached media (`loadAllAssets`) |
| Audio asset | media file | Reloads all cached media (`loadAllAssets`) |

This is the pipeline `wle_compiler.py` (`run_smart_sync`) and `media_sync.py` drive for
"push my changes to the robot."

## 3. Telemetry heartbeat (robot → Studio)

Sent unsolicited over the active TCP connection every 10 s once the link has been idle for
>15 s (keeps the connection alive and gives Studio live health stats without polling):

```
'W' 'L' 'E' 0xAA
uint16  phys_hz     (kinematics tick rate, target 50)
uint16  gfx_fps      (eye-render frame rate)
uint32  free_sram
uint32  free_psram
int8    rssi         (Wi-Fi signal strength)
```

`CommManager.read_telemetry()` parses this 17-byte frame and also uses receipt of *any*
data (including this heartbeat) to feed a 30 s connection watchdog.



## 4. CRSF "TOC" config protocol (realm `0x50`) — remote ESP32 ↔ EdgeTX radio

This is a **separate physical link**: a wired CRSF (Crossfire) serial connection at
400,000 baud between the EdgeTX radio's external module bay and a second, dedicated ESP32
(`firmware/esp32_remote/CrsfESP32.ino`, currently prototyped on a TTGO T-Display). The
radio side is a standalone EdgeTX Lua "Tools" script (`Gjoints.lua`) that renders a menu
UI (browse animations/audio/images, mark favorites, play them, and view/edit joint
calibration) entirely from the radio's screen, using the remote ESP32 as a proxy back to
the robot's data.

This protocol is **read/write configuration and browsing**, not real-time motion control —
it is unrelated to the live joint command frame in §1, and unrelated to the
manual-control-over-ESP-NOW feature that's still being built (§5 below / see
[05-rc-manual-control-design.md](05-rc-manual-control-design.md)).

### Frame format

Implemented as a private extension of the standard CRSF "COMMAND" frame type:

```
Byte 0    : 0xEA          device/sync address (CRSF_ADDR_RADIO)
Byte 1    : frame_len      length of [type..payload..crc]
Byte 2    : 0x32           CRSF frame type = COMMAND
Byte 3    : 0xEA           destination address (radio)
Byte 4    : 0xEE           origin address (TX module)
Byte 5    : 0x50           REALM_TOC — marks this as the private WLE5 extension
Byte 6    : subcmd
Bytes 7..N: subcmd payload
Byte N+1  : CRC-8 (poly 0xD5) over [type..payload]
```

### Sub-commands

| Sub-cmd | Direction | Payload | Purpose |
|---|---|---|---|
| `0x01 SUB_REQUEST_COUNT` | Lua → ESP32 | `category` | How many entries exist in a TOC category |
| `0x02 SUB_COUNT_RESP` | ESP32 → Lua | `category, count(u16)` | Reply to above |
| `0x03 SUB_REQUEST_ENTRY` | Lua → ESP32 | `category, index(u16)` | Fetch one TOC entry |
| `0x04 SUB_ENTRY_RESP` | ESP32 → Lua | `category, index, favorite, name` | TOC entry data |
| `0x05 SUB_SELECT_PLAY` | Lua → ESP32 | `category, index(u16)` | Play the selected animation/audio/image |
| `0x06 SUB_ACK` | ESP32 → Lua | `category, index, status` | Generic ack/error status |
| `0x07 SUB_SET_FAVORITE` | Lua → ESP32 | `category, index(u16), fav` | Toggle favorite flag |
| `0x10 SUB_REQUEST_JOINT` | Lua → ESP32 | `index(u16)` | Fetch one joint's calibration |
| `0x11 SUB_JOINT_RESP` | ESP32 → Lua | joint fields + name | Joint calibration data |
| `0x12 SUB_WRITE_JOINT` | Lua → ESP32 | joint fields (16 bytes) | Write updated joint calibration |
| `0x13 SUB_WRITE_ACK` | ESP32 → Lua | `index, status` | Ack for a write |

Categories: `0 = Joints, 1 = Animations, 2 = Audio, 3 = Images`.

> **Note on current implementation state:** `CrsfESP32.ino` as included in this snapshot
> answers these queries from **hardcoded seed/test data** (`seedTestData()`), not from the
> live robot's actual asset list or joint table — the remote ESP32 does not yet have its
> own link back to the main ESP32 to fetch real data. Wiring that up (and/or reusing the
> same channel for manual control) is part of the open work tracked in
> [05-rc-manual-control-design.md](05-rc-manual-control-design.md).

## 5. To be implemented

None of the transports above currently carry **live, continuous manual control input from
the RC transmitter** (stick/switch movements mapped to joints, streamed in real time).
That is the one subsystem still under development — a fourth transport (ESP-NOW) with its
own packet format, connecting the remote ESP32 to the main ESP32 directly. See
[05-rc-manual-control-design.md](05-rc-manual-control-design.md) for what exists today and
a proposed design for the rest.
