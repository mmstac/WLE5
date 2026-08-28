# WLE5 Technical Specification: Communication Protocols

**Document Version:** 1.0  
**Transports Covered:** Wi-Fi TCP (`4210`), USB-Serial (`115200`), UDP Broadcast, CRSF Serial (`400k`), ESP-NOW (`0xE5`)

---

## 1. Protocol Architecture & Transports

WLE5 employs a multi-tiered communication architecture tailored for real-time motion, high-speed binary synchronization, and radio telemetry:

| Transport | Physical Layer / Port | Purpose & Data Carried |
|---|---|---|
| **USB Serial** | `115200` baud | Initial setup, configuration, Wi-Fi provisioning, and fallback link. |
| **Wi-Fi TCP** | Port `4210` | Primary desktop link for WLE5 Studio (live jogging, file sync, telemetry). |
| **Wi-Fi UDP** | Port `4210` | Fire-and-forget live joint commands (`0xAA` frames, zero ACK overhead). |
| **CRSF Serial** | Wired UART @ `400,000` baud | EdgeTX Radio module bay $\leftrightarrow$ Remote ESP32 Table-of-Contents (`0x50`). |
| **ESP-NOW** | 2.4 GHz Peer-to-Peer (`0xE5`) | Low-latency wireless RC manual stick driving (remote ESP32 $\to$ main ESP32). |

---

## 2. Live Joint Command Packet (`0xAA`)

Used identically across **TCP, USB Serial, and UDP**. The command packet was designed to be compact, utilizing a 2-byte header plus 3-bytes per joint target (up to 16).  

```
Byte 0        : 0xAA                     (Frame Header)
Byte 1        : count                    (1 to 16 commands in this frame)
Bytes 2..N    : count × 3-byte command tuples:
                  [0] joint_id  (uint8_t, 0–255; 100–118 are Virtual Joints)
                  [1] setpoint  (uint8_t, 0–255 normalized target value)
                  [2] speed     (uint8_t, 0–255; 255 = instant snap)
```

### Normalization Formula:
$$\text{wire\_setpoint} = \text{clamp}\left(\text{round}\left( \frac{\text{target} - r_{\text{min}}}{r_{\text{max}} - r_{\text{min}}} \times 255 \right), 0, 255\right)$$

### Command Priority:
Receiving a command for any joint immediately cancels any running animation on that joint (`active_anim_id = 0`). Live operator inputs always override autonomous behaviors.

---

## 3. Maintenance & File Sync Protocol (`'W' 'L' 'E'`)

Available exclusively on **TCP and USB Serial**. All multi-byte integers are serialized in little-endian byte order.

| Sub-Header | Direction | Purpose | Description |
|---|:---:|---|---|
| **`0x02`** | Studio $\to$ Robot | **PSRAM Asset Transfer** | Streams binary blobs (`config.bin`, `anims.bin`, `states.bin`, media). |
| **`0xBB`** | Studio $\to$ Robot | Query Config Version | Queries current `config.bin` version u32. |
| **`0xCC`** | Studio $\to$ Robot | Query Animation Hash | Queries current `anims.bin` content hash u32. |
| **`0xEE 0x01`** | Studio $\to$ Robot | Request Flash Manifest | Lists all files stored in `/img` and `/audio` (terminated by `END_OF_MANIFEST`). |
| **`0xEE 0x05`** | Studio $\to$ Robot | Delete Named File | Removes a file from internal FFat flash. |
| **`0xEE 0x06`** | Studio $\to$ Robot | Reload Media Cache | Flushes RAM caches and re-indexes all image/audio assets. |
| **`0xFF 0x01`** | Studio $\to$ Robot | **Wi-Fi Provisioning** | Transmits SSID and password; robot saves to flash and reboots. |

---

### 3.1 PSRAM Burst File Transfer Sequence (`0x02`)

```
Studio                                                    ESP32 Main Controller
  │                                                                 │
  │─── 'W''L''E' 0x02 + [type][size_u32][crc_u32][filename_64B] ───>│ Allocates PSRAM Buffer
  │                                                                 │
  │<────────────────────────── 0x01 (ACK) ──────────────────────────│ Buffer Ready
  │                                                                 │
  │═══════════════ Stream payload bytes (up to 4MB) ═══════════════>│ Streams into PSRAM
  │                                                                 │
  │                                                                 │ Validates CRC32 &
  │                                                                 │ Flushes to FFat Flash
  │<──────────────── 0x01 (Success) / 0x00 (Error) ─────────────────│ Dispatches Loader
```

#### Dispatched Loaders on Write Completion (`processCompletedFile()`):
- **`config.bin`**: Calls `loadHardwareConfig()`, refreshing `ROBOT_CONFIG[]` table.
- **`states.bin`**: Calls `loadIdleStates()`, refreshing idle state weights and intervals.
- **`anims.bin`**: Calls `loadAnimations()`, parsing animation offsets and keyframe tables.
- **Media Files**: Calls `loadAllAssets()`, reloading graphics buffers and audio catalogs.

---

## 4. Telemetry Heartbeat Frame (Robot $\to$ Studio)

Sent unsolicited over TCP every 10 seconds when the link has been idle for >15 seconds. Keeps the connection alive and provides health telemetry without polling:

```
Bytes 0..2    : 'W' 'L' 'E'              (ASCII Header)
Byte 3        : 0xAA                     (Telemetry Identifier)
Bytes 4..5    : uint16_t phys_hz         (Kinematics tick rate, target: 50 Hz)
Bytes 6..7    : uint16_t gfx_fps         (Display rendering frame rate, 30–45 FPS)
Bytes 8..11   : uint32_t free_sram       (Available internal heap in bytes)
Bytes 12..15  : uint32_t free_psram      (Available external PSRAM in bytes)
Byte 16       : int8_t rssi              (Wi-Fi signal strength in dBm)
```

`CommManager.read_telemetry()` parses this 17-byte frame and feeds a 30-second connection watchdog timer.

---

## 5. EdgeTX CRSF Table-of-Contents (TOC) Protocol (Realm `0x50`)

A dedicated wired CRSF serial link at 400,000 baud connects the EdgeTX radio module bay to a remote ESP32 (`firmware/esp32_remote/CrsfESP32.ino`). The EdgeTX Lua script `Gjoints.lua` runs on the transmitter to provide a visual browsing and calibration interface.

### Frame Format (CRSF Command Frame Extension)
```
Byte 0        : 0xEA                     (CRSF_ADDR_RADIO sync address)
Byte 1        : frame_len                (Length of payload + CRC)
Byte 2        : 0x32                     (CRSF Frame Type: COMMAND)
Byte 3        : 0xEA                     (Destination Address: Radio)
Byte 4        : 0xEE                     (Origin Address: TX Module)
Byte 5        : 0x50                     (REALM_TOC: WLE5 Private Extension)
Byte 6        : subcmd                   (Sub-command ID)
Bytes 7..N    : subcmd_payload           (Command-specific data)
Byte N+1      : crc8                     (Polynomial 0xD5 over [type..payload])
```

### TOC Sub-Commands
| Sub-Cmd | Identifier | Direction | Purpose |
|---|---|:---:|---|
| `0x01` | `SUB_REQUEST_COUNT` | Lua $\to$ Remote ESP32 | Queries number of items in a category (`0=Joints, 1=Anims, 2=Audio, 3=Images`). |
| `0x02` | `SUB_COUNT_RESP` | Remote ESP32 $\to$ Lua | Returns count for requested category. |
| `0x03` | `SUB_REQUEST_ENTRY` | Lua $\to$ Remote ESP32 | Requests details for a specific item index. |
| `0x04` | `SUB_ENTRY_RESP` | Remote ESP32 $\to$ Lua | Returns item name, index, and favorite status. |
| `0x05` | `SUB_SELECT_PLAY` | Lua $\to$ Remote ESP32 | Triggers playback of selected animation/audio/image. |
| `0x06` | `SUB_ACK` | Remote ESP32 $\to$ Lua | Acknowledges operation status. |
| `0x07` | `SUB_SET_FAVORITE` | Lua $\to$ Remote ESP32 | Toggles item favorite flag. |
| `0x10` | `SUB_REQUEST_JOINT` | Lua $\to$ Remote ESP32 | Fetches full calibration parameters for a joint index. |
| `0x11` | `SUB_JOINT_RESP` | Remote ESP32 $\to$ Lua | Returns joint calibration struct + name. |
| `0x12` | `SUB_WRITE_JOINT` | Lua $\to$ Remote ESP32 | Writes updated calibration parameters to joint. |
| `0x13` | `SUB_WRITE_ACK` | Remote ESP32 $\to$ Lua | Acknowledges calibration write. |

---

## 6. RC Manual Control & ESP-NOW Packet (`0xE5`)

For live manual RC stick driving, the remote ESP32 converts 11-bit CRSF channels into direct joint setpoints and broadcasts them over peer-to-peer ESP-NOW at 50 Hz.

```c
struct __attribute__((packed)) EspNowManualCtrlPacket {
    uint8_t magic;      // 0xE5 — Application Identifier
    uint8_t seq;        // Rolling sequence counter (0–255)
    uint8_t count;      // Number of joint updates (1–16)
    struct {
        uint8_t joint_id; // Physical (0–99) or Virtual (100–118)
        uint8_t setpoint; // 0–255 normalized position
        uint8_t speed;    // 0–255 slew rate (255 = instant)
    } cmds[16];
    uint8_t failsafe;   // 1 = Radio link lost / transmitter disarmed
};
```

For full details on channel arming state machines, failsafe watchdogs, and Wi-Fi coexistence, see [**RC Manual Control Design**](07-rc-manual-control-design.md).
