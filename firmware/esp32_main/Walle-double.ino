// Last Updated: 2026-08-10
/*
 * ESP32-S3 Dual 1.28" Round Display (GC9A01)
 * WLE5 Animation Engine - Real-Time Kinematics & Probabilistic Idle States
 */

#include <TFT_eSPI.h>
#include <SPI.h>
#include <ESP32Servo.h>
#include <Adafruit_PWMServoDriver.h> 
#include "FS.h"
#include "SD_MMC.h"
#include <Wire.h>
#include <FFat.h> 
#include <WiFi.h>
#include <WiFiUdp.h>
#include <Preferences.h>
#include "robot_config.h" 

// --- RESTORED AUDIO DRIVERS ---
#include "src/I2C_Driver.h"
#include "src/I2S_Driver.h"
#include "src/Audio_ES8311.h"

extern "C" {
  #include "src/es8311.h"
}
#include <Audio.h>

// --- HARDWARE PIN DEFINITIONS ---
#define TFT_SCLK 41
#define TFT_MOSI 42
#define TFT_DC   45
#define TFT_CS1  47
#define TFT_RST1 48
#define TFT_BL1  46
#define TFT_CS2  38
#define TFT_RST2 8
#define TFT_BL2  39

#define I2S_MCLK 12 
#define I2S_BCLK 13 
#define I2S_LRC  14 
#define I2S_DOUT 15 

#define AUX_I2C_SDA 4
#define AUX_I2C_SCL 5

#define ACK_BYTE 0x01

// --- TELEMETRY & HEARTBEAT TRACKERS ---
unsigned long lastTickReport = 0;
uint16_t physicsTickCounter = 0;
uint16_t gfxTickCounter = 0;
uint16_t current_physics_hz = 0;
uint16_t current_gfx_hz = 0;

unsigned long last_tcp_rx_time = 0;
unsigned long last_heartbeat_time = 0;

// ==========================================
// BINARY FILE STRUCTURES
// ==========================================
struct __attribute__((packed)) BinJointConfig {
    uint8_t id;
    char name[32];
    uint8_t region;
    uint8_t control_type;
    int8_t hardware_address;
    float r_min;
    float r_max;
    float r_init;
    int16_t cmd_min;
    int16_t cmd_max;
    int16_t cmd_init;
    uint8_t def_spd;
    uint8_t max_spd;
    uint8_t max_acc;
};

struct __attribute__((packed)) BinCommand {
    uint8_t joint_id;
    uint8_t setpoint;
    uint8_t speed;
};

struct __attribute__((packed)) BinKeyframe {
    uint16_t time_tenths; 
    uint8_t cmd_count;
    BinCommand commands[16]; 
};

struct BinAnimation {
    char name[32];
    uint16_t kf_count;
    BinKeyframe* keyframes; 
};

struct BinIdleAction {
    char anim_name[32];
    uint8_t weight;
    uint8_t variance;
    uint16_t cooldown_sec;
    unsigned long last_played_time; 
    int linked_anim_index;          
};

struct EngineState {
    int32_t current_position;
    int32_t target_position;
    int32_t current_velocity;
    int32_t target_velocity;
};

// --- GLOBAL ENGINE STATES ---
BinJointConfig ROBOT_CONFIG[256]; 
bool joint_is_active[256] = {false}; 
EngineState engine_states[256];
bool isAsymmetric = false;
bool enable_debug_log = false; 
bool safe_mode_active = false; 
bool SHOW_DEBUG = false; 

// --- VIRTUAL JOINT AUTO-MODES ---
bool auto_mode_active[256] = {false};
uint8_t auto_mode_speed[256] = {255};


// --- WIFI, NVS & TCP GLOBALS ---
Preferences preferences;
WiFiUDP udp;
WiFiServer tcpServer(4210);
WiFiClient activeClient;
File uploadFile;

BinAnimation* activeAnimations = nullptr;
uint8_t activeAnimationCount = 0;

// Idle State Globals
float idle_timeout_sec = 5.0;
float interval_min_sec = 2.0;
float interval_max_sec = 5.0;
uint8_t idle_action_count = 0;
BinIdleAction* idle_actions = nullptr;

uint8_t active_idle_state = 1;
unsigned long last_interaction_time = 0;
unsigned long next_idle_trigger = 0;

// Playback Controls
uint8_t active_anim_id = 0;        
uint16_t current_frame_idx = 0;
unsigned long anim_start_time = 0;

// Hardware Drivers
TFT_eSPI tft = TFT_eSPI(); 
TFT_eSprite img = TFT_eSprite(&tft); 
Servo physical_servos[6];
Adafruit_PWMServoDriver pca9685 = Adafruit_PWMServoDriver(0x40); 

Audio audio;
TaskHandle_t AudioTask;
TaskHandle_t GfxTask;

// --- Audio Globals ---
uint8_t current_master_volume = 80;
uint8_t current_audio_track = 255;
volatile unsigned long last_audio_trigger = 0;

#define MAX_ASSETS 60
uint16_t* cachedImages[MAX_ASSETS] = {nullptr};
String audioPaths[MAX_ASSETS] = {""};
volatile int requestedAudioIndex = -1;

const int WIDTH = 234; const int HEIGHT = 234;
const int CENTER_X = 117;
const int CENTER_Y = 117; const int OFFSET = 3; 

uint8_t dist_map[120][120];
uint8_t bezel_mask[120][120]; 

unsigned long lastFrameTime = 0;
int currentFPS = 0;
unsigned long last_render_time_ms = 0;
unsigned long last_spi_time_ms = 0;

// --- FORWARD DECLARATIONS ---
void renderEyeFrame(float t, bool isRightEye);
void updateJointPhysics(uint8_t joint_id); 
void setMasterVolume(uint8_t vol_0_100);
void pushCommandToEngine(uint8_t id, uint8_t setpoint, uint8_t speed);
void loadHardwareConfig();
void loadAnimations();
void loadIdleStates();
void loadAllAssets();
void processStream(Stream &stream);

uint32_t calculateCRC32(const uint8_t *data, size_t length);
void processCompletedFile(uint8_t type, const char* filename);

// --- AUDIO & VOLUME CONTROL (Pinned to Core 1) ---
void setMasterVolume(uint8_t vol_0_100) {
  if (vol_0_100 > 100) vol_0_100 = 100;
  Volume_adjustment(90); 
  uint8_t sw_vol = map(vol_0_100, 0, 100, 0, 21);
  audio.setVolume(sw_vol);
}

void audioTaskCode(void * parameter) {
  int loop_cnt = 0;
  for(;;) {
    if (requestedAudioIndex > 0 && requestedAudioIndex < MAX_ASSETS) {
      if (audioPaths[requestedAudioIndex] != "") {
          audio.setVolume(0);
          audio.connecttoFS(FFat, audioPaths[requestedAudioIndex].c_str());
          setMasterVolume(current_master_volume); 
      }
      requestedAudioIndex = -1;
    } else if (requestedAudioIndex == 255) {
      audio.stopSong();
      requestedAudioIndex = -1;
    }
    
    if (audio.isRunning()) {
        audio.loop();
        if (++loop_cnt > 100) { 
            vTaskDelay(1 / portTICK_PERIOD_MS);
            loop_cnt = 0; 
        }
    } else {
        vTaskDelay(20 / portTICK_PERIOD_MS);
    }
  }
}

// --- KINEMATICS TASK (Pinned to Core 1, Priority 3) ---
void kinematicsTaskCode(void * parameter) {
    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xFrequency = 20 / portTICK_PERIOD_MS; // Exactly 50Hz
    
    for(;;) {
        vTaskDelayUntil(&xLastWakeTime, xFrequency);
        
        // --- SAFE MODE BYPASS ---
        if (safe_mode_active) continue; 
        
        unsigned long currentMillis = millis();

        // --- 1. AUTONOMOUS BLINK GENERATOR ---
        static unsigned long next_blink = 0; 
        static bool is_blinking = false;
        static unsigned long blink_hold_timer = 0; // NEW: Tracks how long the eye has been closed

        if (auto_mode_active[V_EYELID]) {
            // Time to blink! Force target closed (254 is max manual range)
            if (!is_blinking && currentMillis > next_blink) {
                is_blinking = true;
                blink_hold_timer = 0; // Reset the hold timer
                engine_states[V_EYELID].target_position = 254; 
                engine_states[V_EYELID].target_velocity = auto_mode_speed[V_EYELID];
            }
            
            if (is_blinking) {
                // Once closed, start the hold timer
                if (engine_states[V_EYELID].current_position >= 248 && engine_states[V_EYELID].target_position != 0) {
                    if (blink_hold_timer == 0) blink_hold_timer = currentMillis;
                    
                    // ---------------------------------------------------------
                    // *** 1. ADJUST BLINK HOLD DURATION HERE (in milliseconds) 
                    // ---------------------------------------------------------
                    if (currentMillis - blink_hold_timer >= 150) {
                        engine_states[V_EYELID].target_position = 0; 
                    }
                }
                
                // Once fully open again, calculate organic interval
                if (engine_states[V_EYELID].current_position <= 5 && engine_states[V_EYELID].target_position == 0) {
                    is_blinking = false;
                    
                    // ---------------------------------------------------------
                    // *** 2. ADJUST TIME BETWEEN BLINKS HERE (Min ms, Max ms) 
                    // ---------------------------------------------------------
                    next_blink = currentMillis + random(6000, 10000); 
                }
            }
        }

// --- 2. AUTONOMOUS APERTURE TWITCH GENERATOR (WITH FOCUS HUNT) ---
        static unsigned long next_twitch = 0; 
        static int twitch_phase = 0; // 0: waiting, 1: primary snap, 2: backtrack
        static int primary_tgt = 0;
        static int prev_tgt = 0;

        if (auto_mode_active[V_APERTURE]) {
            // Time to twitch! Pick a random dilation size between 50% (127) and 90% (230)
            if (twitch_phase == 0 && currentMillis > next_twitch) {
                twitch_phase = 1;
                prev_tgt = engine_states[V_APERTURE].current_position;
                primary_tgt = random(100, 230); 
                
                engine_states[V_APERTURE].target_position = primary_tgt;
                engine_states[V_APERTURE].target_velocity = auto_mode_speed[V_APERTURE];
            }
            
            if (twitch_phase == 1) {
                // Once primary target is reached, trigger the 30% focus hunt backtrack
                if (abs(engine_states[V_APERTURE].current_position - primary_tgt) <= 5) {
                    twitch_phase = 2;
                    int delta = prev_tgt - primary_tgt; 
                    engine_states[V_APERTURE].target_position = primary_tgt + (delta * 0.50);
                    
                    // Halve the speed for the subtle backtrack motion
                    engine_states[V_APERTURE].target_velocity = max(1, auto_mode_speed[V_APERTURE] / 2);
                }
            }

            if (twitch_phase == 2) {
                // Once backtrack completes, hold and calculate next twitch
                if (abs(engine_states[V_APERTURE].current_position - engine_states[V_APERTURE].target_position) <= 5) {
                    twitch_phase = 0;
                    next_twitch = currentMillis + random(4000, 9000); 
                }
            }
        }

        // --- 3. STANDARD PHYSICS UPDATES ---
        for (int i = 0; i < 256; i++) {
            if (joint_is_active[i]) {
                updateJointPhysics(i);
            }
        }
        physicsTickCounter++;
    }
}

// --- DEDICATED GRAPHICS TASK (Pinned to Core 0) ---
void graphicsTaskCode(void * parameter) {
  for(;;) {
      // --- SAFE MODE FREEZE ---
      if (safe_mode_active) {
          vTaskDelay(100 / portTICK_PERIOD_MS); 
          continue;
      }
      
      unsigned long currentMillis = millis();
      float t = currentMillis / 1000.0;
      if (currentMillis - lastFrameTime > 0) currentFPS = 1000 / (currentMillis - lastFrameTime);
      lastFrameTime = currentMillis;
      
      if (!isAsymmetric) {
        // --- SYMMETRIC MODE ---
        unsigned long render_start = micros();
        renderEyeFrame(t, false);
        last_render_time_ms = (micros() - render_start) / 1000;
        
        digitalWrite(TFT_CS1, LOW); digitalWrite(TFT_CS2, LOW);
        unsigned long spi_start = micros();
        img.pushSprite(OFFSET, OFFSET);
        last_spi_time_ms = (micros() - spi_start) / 1000;
        digitalWrite(TFT_CS1, HIGH); digitalWrite(TFT_CS2, HIGH);

      } else {
        // --- ASYMMETRIC MODE ---
        unsigned long render_start_L = micros();
        renderEyeFrame(t, false);
        last_render_time_ms = (micros() - render_start_L) / 1000;
        
        digitalWrite(TFT_CS1, LOW);
        unsigned long spi_start_L = micros();
        img.pushSprite(OFFSET, OFFSET); 
        last_spi_time_ms = (micros() - spi_start_L) / 1000;
        digitalWrite(TFT_CS1, HIGH);
        
        unsigned long render_start_R = micros();
        renderEyeFrame(t, true);
        last_render_time_ms = (micros() - render_start_R) / 1000;
        
        digitalWrite(TFT_CS2, LOW);
        unsigned long spi_start_R = micros();
        img.pushSprite(OFFSET, OFFSET); 
        last_spi_time_ms = (micros() - spi_start_R) / 1000;
        digitalWrite(TFT_CS2, HIGH);
      }

      gfxTickCounter++;
      vTaskDelay(1 / portTICK_PERIOD_MS);
  }
}

// --- COMMAND INGESTION ---
void pushCommandToEngine(uint8_t id, uint8_t setpoint, uint8_t speed) {
    if (id == V_AUDIO_PLAY) { 
        if (setpoint != current_audio_track || (millis() - last_audio_trigger > 250)) {
            requestedAudioIndex = setpoint;
            current_audio_track = setpoint;
            last_audio_trigger = millis();
        }
        if (speed != current_master_volume) {
            current_master_volume = speed;
            setMasterVolume(speed); 
        }
        return;
    }
    
    if (id == V_ASYMMETRY) { isAsymmetric = (setpoint > 0); return; } 
    
    if (id == V_IDLE_STATE) { 
        // --- NEW: Intercept Debug Overlay Command ---
        if (setpoint == 255) { SHOW_DEBUG = true; return; }
        if (setpoint == 254) { SHOW_DEBUG = false; return; }

        if (active_idle_state != setpoint) {
            active_idle_state = setpoint;
            if (active_idle_state == 0) {                
                if (idle_actions != nullptr) {
                    delete[] idle_actions;
                    idle_actions = nullptr;
                }
                idle_action_count = 0;
            } 
            else {
                loadIdleStates();
            }
            last_interaction_time = millis();
        }
        return; 
    }
    
    if (id == V_PLAY_ANIM) { 
        active_anim_id = setpoint;
        current_frame_idx = 0; 
        anim_start_time = millis(); 
        return; 
    }

    // --- VIRTUAL JOINT BEHAVIOR HIJACK ---
    // Catch magic 255 flags before they hit the real physics targets
    if (id == V_EYELID || id == V_APERTURE) {
        if (setpoint == 255) {
            auto_mode_active[id] = true;
            auto_mode_speed[id] = speed; // Save the physical speed for the action
            return; // Exit early so the generator retains full control
        } else {
            auto_mode_active[id] = false; // Instantly kill auto mode on manual command
            // Do NOT return here; let the manual command fall through to the KE
        }
    }
    
    if (joint_is_active[id]) {
        int32_t new_target = ROBOT_CONFIG[id].cmd_min + ((setpoint * (ROBOT_CONFIG[id].cmd_max - ROBOT_CONFIG[id].cmd_min)) / 255);
        if (speed == 255 && engine_states[id].target_position == new_target) return; 
        
        engine_states[id].target_position = new_target;
        engine_states[id].target_velocity = speed;
    }
}

// --- REAL-TIME KINEMATICS ENGINE ---
void updateJointPhysics(uint8_t joint_id) {
    BinJointConfig config = ROBOT_CONFIG[joint_id];
    EngineState& state = engine_states[joint_id];
    
    if (config.max_acc == 0) config.max_acc = 1; 

    int32_t distanceTo = state.target_position - state.current_position;
    int32_t vel = state.current_velocity;
    int32_t max_acc = config.max_acc;
    
    int32_t max_spd = state.target_velocity;
    if (max_spd > config.max_spd) max_spd = config.max_spd;
    
    if (distanceTo == 0 && vel == 0) return;

    if (state.target_velocity == 255) {
        state.current_position = state.target_position;
        state.current_velocity = 0;
    } 
    else {
        float a = (float)max_acc;
        float d = (float)abs(distanceTo);
        int32_t v_safe = (int32_t)((-a + sqrt(a * a + 8.0f * a * d)) / 2.0f);

        int32_t next_v = vel;
        if (distanceTo > 0) {
            if (vel < 0) {
                next_v = vel + max_acc;
            } else {
                next_v = vel + max_acc;
                if (next_v > v_safe) next_v = v_safe;
                if (next_v < vel - max_acc) next_v = vel - max_acc;
                if (next_v < 1) next_v = 1;
            }
        } else {
            if (vel > 0) {
                next_v = vel - max_acc;
            } else {
                next_v = vel - max_acc;
                if (next_v < -v_safe) next_v = -v_safe;
                if (next_v > vel + max_acc) next_v = vel + max_acc;
                if (next_v > -1) next_v = -1;
            }
        }

        if (abs(distanceTo) <= max_acc && abs(vel) <= max_acc * 2) {
            next_v = distanceTo;
        }

        if (distanceTo > 0 && next_v > distanceTo) next_v = distanceTo;
        if (distanceTo < 0 && next_v < distanceTo) next_v = distanceTo;
        
        if (next_v > max_spd) next_v = max_spd;
        if (next_v < -max_spd) next_v = -max_spd;

        state.current_velocity = next_v;
        state.current_position += next_v;
    }

    if (distanceTo > 0 && state.current_position > state.target_position) state.current_position = state.target_position;
    if (distanceTo < 0 && state.current_position < state.target_position) state.current_position = state.target_position;

    if (enable_debug_log && joint_id == 1 && abs(distanceTo) > 0) { 
        Serial.printf("DistLeft:%5d | Vel:%4d | Pos:%4d\n", 
            (int)distanceTo, (int)state.current_velocity, (int)state.current_position);
    }

    if (config.control_type == 0 && config.hardware_address >= 0 && config.hardware_address < 6) { 
        if (!physical_servos[config.hardware_address].attached()) {
             physical_servos[config.hardware_address].attach(config.hardware_address);
        }
        physical_servos[config.hardware_address].writeMicroseconds(state.current_position);
    } 
    else if (config.control_type == 1 && config.hardware_address >= 0 && config.hardware_address < 16) { 
        uint16_t pulse_width_ticks = (state.current_position * 4096) / 20000;
        uint16_t on_tick = (config.hardware_address * 256) % 4096; 
        uint16_t off_tick = (on_tick + pulse_width_ticks) % 4096;
        pca9685.setPWM(config.hardware_address, on_tick, off_tick);
    }
    else if (config.control_type == 3 && config.hardware_address >= 0 && config.hardware_address < 16) { 
        uint16_t pwm_val = constrain(state.current_position, 0, 4095);
        if (pwm_val >= 4095) {
            pca9685.setPWM(config.hardware_address, 4096, 0);      
        } else if (pwm_val <= 0) {
            pca9685.setPWM(config.hardware_address, 0, 4096);      
        } else {
            pca9685.setPWM(config.hardware_address, 0, pwm_val);   
        }
    }
    else if (config.control_type == 4 && config.hardware_address >= 0 && config.hardware_address < 16) { 
        if (state.current_position > 0) {
            pca9685.setPWM(config.hardware_address, 4096, 0); 
        } else {
            pca9685.setPWM(config.hardware_address, 0, 4096); 
        }
    }
    else if (config.control_type == 5 && config.hardware_address >= 0) {
        uint8_t pin = config.hardware_address;
        
        static bool esp_motor_init[256] = {false};
        if (!esp_motor_init[joint_id]) {
            ledcAttach(pin, 20000, 12); 
            esp_motor_init[joint_id] = true;
        }
        
        uint32_t pwm_val = constrain(state.current_position, 0, 4095);
        ledcWrite(pin, pwm_val);
    }
}


// --- SETUP ROUTINE ---
void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);

  // --- 1. IMMEDIATE SCREEN INIT ---
  pinMode(TFT_CS1, OUTPUT); pinMode(TFT_CS2, OUTPUT);
  pinMode(TFT_RST1, OUTPUT); pinMode(TFT_RST2, OUTPUT);
  pinMode(TFT_BL1, OUTPUT);  pinMode(TFT_BL2, OUTPUT);

  // Hardware reset pulse
  digitalWrite(TFT_BL1, LOW);  digitalWrite(TFT_BL2, LOW);
  digitalWrite(TFT_RST1, LOW); digitalWrite(TFT_RST2, LOW);
  delay(50);
  digitalWrite(TFT_RST1, HIGH); digitalWrite(TFT_RST2, HIGH);
  delay(120);

  digitalWrite(TFT_CS1, LOW); digitalWrite(TFT_CS2, LOW);
  tft.init();
  digitalWrite(TFT_CS1, HIGH); digitalWrite(TFT_CS2, HIGH);
  
  // FIX: Set rotation AND wipe the entire 240x240 hardware buffer to kill border static
  digitalWrite(TFT_CS1, LOW); 
  tft.setRotation(1); 
  tft.fillScreen(TFT_BLACK); 
  digitalWrite(TFT_CS1, HIGH);
  
  digitalWrite(TFT_CS2, LOW); 
  tft.setRotation(3); 
  tft.fillScreen(TFT_BLACK); 
  digitalWrite(TFT_CS2, HIGH);

  // Turn backlights on now that the static is cleared
  digitalWrite(TFT_BL1, HIGH);  
  digitalWrite(TFT_BL2, HIGH);

  // Prep the sprite buffer for the terminal
  img.setColorDepth(16);
  img.createSprite(WIDTH, HEIGHT);
  img.fillSprite(TFT_BLACK);
  img.setTextColor(tft.color565(50, 255, 50), TFT_BLACK); // Retro Green
  img.setTextDatum(TL_DATUM);

  // Lambda function to progressively log to the screen
  int boot_y = 25;
  auto bootLog = [&](String text) {
      img.drawString(text, 30, boot_y, 2);
      boot_y += 18;
      digitalWrite(TFT_CS1, LOW); digitalWrite(TFT_CS2, LOW);
      img.pushSprite(OFFSET, OFFSET);
      digitalWrite(TFT_CS1, HIGH); digitalWrite(TFT_CS2, HIGH);
  };

  bootLog("== WLE5 Kernel v1.0");

  // --- 2. SAFE MODE TRAP ---
  pinMode(0, INPUT_PULLUP);
  delay(100); 
  if (digitalRead(0) == LOW) {
      safe_mode_active = true;
      bootLog("WARN: SAFE MODE ACTIVE");
      Serial.println("\n--- SAFE MODE ACTIVE ---");
  }
  
  // --- 4. WIFI CONNECTION ---
  preferences.begin("wifi", false);
  String ssid = preferences.getString("ssid", "");
  String pass = preferences.getString("pass", "");
  
  if (ssid != "") {
      bootLog("Network found: " + ssid);
      WiFi.begin(ssid.c_str(), pass.c_str());
      int attempts = 0;
      while (WiFi.status() != WL_CONNECTED && attempts < 10) { 
          delay(500);
          attempts++; 
      }
      
      if (WiFi.status() == WL_CONNECTED) {
          bootLog("IP: " + WiFi.localIP().toString());
          udp.begin(4210); tcpServer.begin();
      } else {
          bootLog("WIFI: TIMEOUT");
      }
  } else {
      bootLog("WIFI: OFFLINE");
  }

  // --- 3. MOUNT FILE SYSTEM ---
  bootLog("Mounting file system...");
  if (!FFat.begin(true)) {
      bootLog("ERROR: FFAT FAILED!");
  } else {
      bootLog("Ffat online");
  }

  // --- 5. ASSET & LOGIC LOADING ---
  if (!safe_mode_active) {
      bootLog("Accessing...");
      loadAllAssets();       // PSRAM Images & Audio Paths
      loadHardwareConfig();  // Physics Limits
      loadAnimations();      // Keyframes
      loadIdleStates();      // Logic triggers
      bootLog("Assets loaded");
  }
  
  // --- 6. HARDWARE INIT ---
  bootLog("Servos enabled");
  I2C_Init(); 
  pca9685.begin(); 
  pca9685.setPWMFreq(50); 
  
  bootLog("Starting audio...");
  I2S_Init(24000); Audio_Init(24000); setMasterVolume(80);
  Audio_PA_EN(); i2s.end(); 
  audio.settings.DMA_DESC_NUM = 24;
  audio.settings.DMA_FRAME_NUM = 512;
  audio.setPinout(I2S_BCLK, I2S_LRC, I2S_DOUT, I2S_MCLK);
  
  bootLog("** System online **");
  
  // FIX: Exact 2-second delay before clearing out the boot sequence
  delay(2000); 
  
  // Calculate spatial maps in the background right before launch
  for(int y=0; y<120; y++) {
    for(int x=0; x<120; x++) {
      float d = sqrt(x*x + y*y);
      dist_map[y][x] = (uint8_t)min(255.0f, d);
      if (d < 104.0) bezel_mask[y][x] = 0;   
      else if (d >= 105.5) bezel_mask[y][x] = 255;
      else bezel_mask[y][x] = (uint8_t)((d - 104.0) * 170.0); 
    }
  }

  // --- 7. FINAL LAUNCH ---
  if (safe_mode_active) {
      tft.fillScreen(TFT_RED);
      tft.setTextColor(TFT_WHITE, TFT_RED);
      tft.setTextDatum(MC_DATUM);
      digitalWrite(TFT_CS1, LOW); digitalWrite(TFT_CS2, LOW);
      tft.drawString("SAFE MODE", CENTER_X, CENTER_Y - 20, 4);
      
      tft.setTextDatum(TC_DATUM);
      String wifiStr = (WiFi.status() == WL_CONNECTED) ? WiFi.SSID() : "WIFI OFFLINE";
      tft.drawString(wifiStr, CENTER_X, CENTER_Y + 10, 2);
      if (WiFi.status() == WL_CONNECTED) {
          tft.drawString(WiFi.localIP().toString(), CENTER_X, CENTER_Y + 30, 2);
      }
      digitalWrite(TFT_CS1, HIGH); digitalWrite(TFT_CS2, HIGH);
  } else {
      // Launch standard operating tasks
      xTaskCreatePinnedToCore(audioTaskCode, "AudioTask", 8192, NULL, 2, &AudioTask, 0);
      xTaskCreatePinnedToCore(graphicsTaskCode, "GfxTask", 8192, NULL, 1, &GfxTask, 1);
      
      TaskHandle_t kinTask;
      xTaskCreatePinnedToCore(kinematicsTaskCode, "KinematicsTask", 4096, NULL, 3, &kinTask, 1);
  }

  randomSeed(analogRead(0));
}

// --- MAIN LOOP ---
void loop() {
  unsigned long currentMillis = millis();
  
  if (tcpServer.hasClient()) {
      if (!activeClient || !activeClient.connected()) {
          if (activeClient) activeClient.stop();
          activeClient = tcpServer.available();
          last_tcp_rx_time = currentMillis; // Track new connection
          Serial.println("New TCP Client Connected!");
      } else {
          WiFiClient rejectClient = tcpServer.available();
          rejectClient.stop();
      }
  }

  // Instantly purge dead sockets to prevent lockouts
  if (activeClient && !activeClient.connected()) {
      activeClient.stop();
  }

  if (activeClient && activeClient.connected()) {
      processStream(activeClient); 

      // --- IDLE TELEMETRY HEARTBEAT (17 Bytes) ---
      // Triggers every 10s only if the socket has been idle for > 15s
      if ((currentMillis - last_tcp_rx_time > 15000) && (currentMillis - last_heartbeat_time > 10000)) {
          last_heartbeat_time = currentMillis;
          
          uint8_t hb[17];
          hb[0] = 'W'; hb[1] = 'L'; hb[2] = 'E'; hb[3] = 0xAA; 
          
          uint16_t phys = current_physics_hz;
          uint16_t gfx = current_gfx_hz;
          uint32_t free_sram = ESP.getFreeHeap();
          uint32_t free_psram = ESP.getFreePsram();
          int8_t rssi = (int8_t)WiFi.RSSI();

          memcpy(&hb[4], &phys, 2);
          memcpy(&hb[6], &gfx, 2);
          memcpy(&hb[8], &free_sram, 4);
          memcpy(&hb[12], &free_psram, 4);
          hb[16] = (uint8_t)rssi;

          if (activeClient.write(hb, 17) != 17) {
              activeClient.stop(); // Clean up immediately if write fails
              Serial.println("Heartbeat failed: Dead socket pruned.");
          }
      }
  }
  
  if (Serial.available() > 0) processStream(Serial);       

  int packetSize = udp.parsePacket();
  if (packetSize) {
      uint8_t header = udp.read();
      if (header == 0xAA) {
          uint8_t count = udp.read();
          if (count <= 16) {
              for (uint8_t i = 0; i < count; i++) {
                  uint8_t packet[3];
                  if (udp.read(packet, 3) == 3) {
                      last_interaction_time = currentMillis;
                      if (joint_is_active[packet[0]] && active_anim_id != 0) active_anim_id = 0;
                      pushCommandToEngine(packet[0], packet[1], packet[2]);
                  }
              }
          }
      }
  }

  if (active_anim_id != 0 && activeAnimations != nullptr) {
      int target_index = active_anim_id - 1;
      if (target_index >= 0 && target_index < activeAnimationCount) {
          BinAnimation* anim = &activeAnimations[target_index];
          uint32_t elapsed_tenths = (currentMillis - anim_start_time) / 100;

          while (current_frame_idx < anim->kf_count && anim->keyframes[current_frame_idx].time_tenths <= elapsed_tenths) {
              BinKeyframe& kf = anim->keyframes[current_frame_idx];
              for(int c = 0; c < kf.cmd_count; c++) {
                  pushCommandToEngine(kf.commands[c].joint_id, kf.commands[c].setpoint, kf.commands[c].speed);
              }
              current_frame_idx++;
          }

          if (current_frame_idx >= anim->kf_count) {
              active_anim_id = 0;
              next_idle_trigger = currentMillis + random((long)(interval_min_sec * 1000), (long)(interval_max_sec * 1000));
          }
      } else {
          active_anim_id = 0;
      }
  } 
  else if (active_idle_state > 0 && idle_actions != nullptr && idle_action_count > 0 && (currentMillis - last_interaction_time > idle_timeout_sec * 1000)) {
      if (currentMillis >= next_idle_trigger) {
          int total_weight = 0;
          int valid_actions[32];
          int valid_count = 0;

          for (int i = 0; i < idle_action_count; i++) {
              if (idle_actions[i].linked_anim_index >= 0) {
                  unsigned long cooldown_ms = idle_actions[i].cooldown_sec * 1000UL;
                  if (idle_actions[i].last_played_time == 0 || (currentMillis - idle_actions[i].last_played_time >= cooldown_ms)) {
                      valid_actions[valid_count++] = i;
                      total_weight += idle_actions[i].weight;
                  }
              }
          }

          if (total_weight > 0) {
              int r = random(0, total_weight);
              int cumulative = 0;
              int selected_idx = -1;
              for (int i = 0; i < valid_count; i++) {
                  int idx = valid_actions[i];
                  cumulative += idle_actions[idx].weight;
                  if (r < cumulative) { selected_idx = idx; break; }
              }

              if (selected_idx >= 0) {
                  active_anim_id = idle_actions[selected_idx].linked_anim_index + 1;
                  current_frame_idx = 0;
                  anim_start_time = currentMillis;
                  idle_actions[selected_idx].last_played_time = currentMillis;
              }
          } else {
              next_idle_trigger = currentMillis + 1000;
          }
      }
  }

  if (millis() - lastTickReport >= 1000) {
      current_physics_hz = physicsTickCounter;
      current_gfx_hz = gfxTickCounter;
      
      physicsTickCounter = 0;
      gfxTickCounter = 0;
      lastTickReport = millis();
  }
  
  vTaskDelay(10 / portTICK_PERIOD_MS);
}
// --- END OF FILE ---