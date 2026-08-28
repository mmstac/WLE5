# WLE5 Technical Specification: Hardware BOM & Wiring Guide

**Document Version:** 1.0  
**Target Hardware:** Waveshare ESP32-S3-DualEye-Touch-LCD-1.28 + PCA9685 16-Channel PWM Driver

---

## 1. Bill of Materials (BOM)

| Component | Specification | Function |
|---|---|---|
| **Main Controller** | Waveshare ESP32-S3 Dual-Eye 1.28" Board | Dual round GC9A01 LCDs, ESP32-S3 WROOM-1, 8MB PSRAM, onboard ES8311 DAC + Speaker |
| **PWM Driver** | PCA9685 16-Channel 12-Bit I2C Driver | Drives physical micro-servos (SG90 / MG90S or digital bus servos) |
| **Power Supply (Servos)** | 5V / 6V DC (3A–5A Peak) | Powers high-current servo power rail (V+) |
| **Power Supply (Logic)** | 5V USB-C / Regulator | Powers ESP32-S3 and I2C logic lines |

---

## 2. Pinout & Bus Mappings

### 2.1 I2C Bus (Shared)
The I2C bus controls the external PCA9685 PWM driver (`0x40`) and configures the onboard ES8311 audio codec.

| Function | ESP32-S3 Pin | PCA9685 Pin | Notes |
|---|:---:|:---:|---|
| **SDA** | `GPIO 4` | SDA | 4.7kΩ pull-up to 3.3V (onboard) |
| **SCL** | `GPIO 5` | SCL | 4.7kΩ pull-up to 3.3V (onboard) |
| **VCC (Logic)** | `3.3V` | VCC | Powers PCA9685 logic |
| **GND** | `GND` | GND | **Common ground with servo PSU** |

### 2.2 I2S Digital Audio Bus (Onboard)
Streams uncompressed audio from FFat flash directly to the onboard ES8311 DAC on Core 0.

| Signal | ESP32-S3 Pin | Function |
|---|:---:|---|
| **I2S MCLK** | `GPIO 2` | Master Clock |
| **I2S BCLK** | `GPIO 1` | Bit Clock |
| **I2S LRCK / WS** | `GPIO 3` | Left/Right Word Select Clock |
| **I2S DOUT** | `GPIO 42` | Serial Audio Data Output |

### 2.3 Dual GC9A01 SPI Display Bus (Onboard)
Dual 240x240 round LCDs are driven over a shared high-speed SPI bus with independent Chip Selects (CS).

| Signal | ESP32-S3 Pin | Function |
|---|:---:|---|
| **SPI MOSI** | `GPIO 11` | Shared Serial Data |
| **SPI SCLK** | `GPIO 12` | Shared Serial Clock (40–80 MHz) |
| **Left Eye CS** | `GPIO 10` | Left LCD Chip Select |
| **Right Eye CS**| `GPIO 9` | Right LCD Chip Select |
| **DC / RS** | `GPIO 8` | Data / Command Control |
| **RST** | `GPIO 14` | Hardware Reset |
| **Backlight** | `GPIO 13` | PWM Backlight Control |

---

## 3. Power Distribution Diagram

```
+--------------------------+
|  5V/6V High-Current PSU  |---+
+--------------------------+   | (5V-6V Servo V+)
                               v
                       [ PCA9685 Driver ] ---> [ Servos 0..15 ]
                               ^ (3.3V Logic)
                               |
+--------------------------+   | (SDA / SCL)
| ESP32-S3 Main Controller |---+
+--------------------------+
  | (GND)                      | (GND)
  +----------------------------+  <--- **CRITICAL: Shared Common Ground**
```

> ⚠️ **Common Ground Rule**: Always connect the GND of the ESP32 to the GND of the external servo power supply. Without a shared ground reference, I2C communication and PWM control pulses will experience severe signal degradation and jitter.
