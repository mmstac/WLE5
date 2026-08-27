
# WLE5 Hardware BOM & Wiring Guide

The WLE5 engine is specifically designed around the **Waveshare ESP32-S3-DualEye-Touch-LCD-1.28** development board. This significantly simplifies wiring, however a different ESP32-S3 board can also be used with the components wired up manually..

## 🛒 Bill of Materials (BOM)

1. **Main Controller & Eyes:** Waveshare ESP32-S3-DualEye-Touch-LCD-1.28
    
    - _Features:_ Onboard dual GC9A01 1.28" TFT screens, ESP32-S3 WROOM, and 8MB PSRAM
    - **Onboard audio DAC:** ES8311 I2S Audio Codec/Amplifier with speaker
    
2. **Servo Driver:** PCA9685 16-Channel 12-bit PWM Controller

## 🔌 Wiring & Pinout Mappings

The waveshare board includes and I/O connector with the I2C, SPI, and UART pins broken out.
### 1. I2C Bus (Shared)

The I2C bus is used to drive the PCA9685 servo controller and configure the ES8311 audio codec. _Note: The PCA9685 is hardcoded in the firmware to address `0x40`._

|   |   |   |
|---|---|---|
|**Device / Function**|**ESP32-S3 Pin**|**Notes**|
|**SDA**|`GPIO 4`|Shared I2C Data|
|**SCL**|`GPIO 5`|Shared I2C Clock|

### 2. I2S Digital Audio Bus (onboard for waveshare board)

The WLE5 engine utilizes a dedicated FreeRTOS task on Core 0 to stream digital audio to an external ES8311 DAC without blocking the physical kinematics.

|   |   |   |
|---|---|---|
|**ES8311 Pin**|**ESP32-S3 Pin**|**Bus Protocol**|
|**MCLK**|`GPIO 12`|I2S Master Clock|
|**BCLK**|`GPIO 13`|I2S Bit Clock|
|**LRC / WS**|`GPIO 14`|I2S Word Select (Left/Right)|
|**DOUT**|`GPIO 15`|I2S Data Out|

### 3. SPI Display Bus - Dual GC9A01 TFTs

These pins are internally routed on the Waveshare Dual-Eye board. If you are building a custom circuit instead of using the AIO board, you must follow this exact mapping.

|Screen / Function|ESP32-S3 Pin|Notes|
|---|---|---|
|**Shared SCLK**|`GPIO 41`|SPI Clock|
|**Shared MOSI**|`GPIO 42`|SPI Data Out|
|**Shared DC**|`GPIO 45`|Data/Command Toggle|
|**Left Eye CS1**|`GPIO 47`|Chip Select 1|
|**Left Eye RST1**|`GPIO 48`|Reset 1|
|**Left Eye BL1**|`GPIO 46`|Backlight 1|
|**Right Eye CS2**|`GPIO 38`|Chip Select 2|
|**Right Eye RST2**|`GPIO 8`|Reset 2|
|**Right Eye BL2**|`GPIO 39`|Backlight 2|
