// Last Updated: 2026-08-09
// ==========================================================
// WLE5 SYSTEM MANAGEMENT & COMMUNICATIONS
// This tab handles File Loading, TCP/USB parsing, and Wi-Fi Syncing.
// Automatically merged with Walle-double.ino by the Arduino IDE.
// ==========================================================

enum FileTransferType {
    FILE_TYPE_JOINT_CFG   = 0,
    FILE_TYPE_IDLE_STATE  = 1,
    FILE_TYPE_ANIM_SCRIPT = 2,
    FILE_TYPE_IMAGE_ASSET = 3,
    FILE_TYPE_AUDIO_ASSET = 4
};

// --- HARDWARE VERIFICATION ---
uint32_t calculateCRC32(const uint8_t *data, size_t length) {
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < length; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++) {
            crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320 : 0);
        }
    }
    return ~crc;
}

// --- POST-TRANSFER ROUTING ---
void processCompletedFile(uint8_t type, const char* filename) {
    if (safe_mode_active) return; // Protect RAM while in File Server mode
    
    switch(type) {
        case FILE_TYPE_JOINT_CFG:
            loadHardwareConfig();
            break;
        case FILE_TYPE_IDLE_STATE:
            loadIdleStates();
            break;
        case FILE_TYPE_ANIM_SCRIPT:
            loadAnimations();
            break;
        case FILE_TYPE_IMAGE_ASSET:
            loadAllAssets(); 
            break;
        case FILE_TYPE_AUDIO_ASSET:
            loadAllAssets(); 
            break;
    }
}

// --- ASSET LOADERS ---
void loadHardwareConfig() {
    for (int i = 0; i < 256; i++) joint_is_active[i] = false;
    if (!FFat.exists("/config.bin")) return;

    File f = FFat.open("/config.bin", "r");
    if (!f) return;

    char header[4];
    f.readBytes(header, 4);
    if (strncmp(header, "WLEC", 4) != 0) { f.close(); return; }

    uint32_t version;
    f.readBytes((char*)&version, 4);
    
    uint8_t count;
    f.readBytes((char*)&count, 1);

    for (uint8_t i = 0; i < count; i++) {
        BinJointConfig temp;
        f.readBytes((char*)&temp, sizeof(BinJointConfig));
        
        ROBOT_CONFIG[temp.id] = temp;
        joint_is_active[temp.id] = true;

        int16_t mapped_default = temp.cmd_init; 
        
        engine_states[temp.id].current_position = mapped_default;
        engine_states[temp.id].target_position = mapped_default;
        engine_states[temp.id].current_velocity = 0;
        engine_states[temp.id].target_velocity = temp.def_spd;
    }
    f.close();
}

void loadAnimations() {
    if (!FFat.exists("/anims.bin")) return;
    File f = FFat.open("/anims.bin", "r");
    if (!f) return;

    char header[4];
    f.readBytes(header, 4);
    if (strncmp(header, "WLEA", 4) != 0) { f.close(); return; }

    uint32_t hash;
    f.readBytes((char*)&hash, 4);
    
    uint8_t new_count;
    f.readBytes((char*)&new_count, 1);
    
    // --- Safely free old PSRAM memory ---
    if (activeAnimations != nullptr) {
        for (uint8_t i = 0; i < activeAnimationCount; i++) {
            if (activeAnimations[i].keyframes != nullptr) {
                heap_caps_free(activeAnimations[i].keyframes); 
            }
        }
        delete[] activeAnimations;
        activeAnimations = nullptr;
    }

    activeAnimationCount = new_count;
    activeAnimations = new BinAnimation[activeAnimationCount];
    
    for (uint8_t i = 0; i < activeAnimationCount; i++) {
        f.readBytes(activeAnimations[i].name, 32);
        f.readBytes((char*)&activeAnimations[i].kf_count, 2);
        
        if (activeAnimations[i].kf_count > 2048) {
            Serial.println("Warning: Animation keyframes exceed safe limits. Clamping to 2048.");
            activeAnimations[i].kf_count = 2048;
        }
        
        // Route heavy keyframe arrays to 8MB PSRAM to save TFT Buffer SRAM
        activeAnimations[i].keyframes = (BinKeyframe*)heap_caps_malloc(activeAnimations[i].kf_count * sizeof(BinKeyframe), MALLOC_CAP_SPIRAM);
        
        for (uint16_t k = 0; k < activeAnimations[i].kf_count; k++) {
            f.readBytes((char*)&activeAnimations[i].keyframes[k].time_tenths, 2);
            f.readBytes((char*)&activeAnimations[i].keyframes[k].cmd_count, 1);
            
            for (uint8_t c = 0; c < activeAnimations[i].keyframes[k].cmd_count; c++) {
                f.readBytes((char*)&activeAnimations[i].keyframes[k].commands[c], sizeof(BinCommand));
            }
        }
    }
    f.close();
}

void loadIdleStates() {
    if (!FFat.exists("/states.bin")) return;
    File f = FFat.open("/states.bin", "r");
    if (!f) return;

    char header[4];
    f.readBytes(header, 4);
    if (strncmp(header, "WLES", 4) != 0) { f.close(); return; }

    f.readBytes((char*)&idle_timeout_sec, 4);
    
    uint8_t total_states;
    f.readBytes((char*)&total_states, 1);

    if (idle_actions != nullptr) {
        delete[] idle_actions;
        idle_actions = nullptr;
    }
    idle_action_count = 0;

    for (uint8_t s = 0; s < total_states; s++) {
        uint8_t state_id;
        float s_min, s_max;
        uint8_t num_actions;
        
        f.readBytes((char*)&state_id, 1);
        f.readBytes((char*)&s_min, 4);
        f.readBytes((char*)&s_max, 4);
        f.readBytes((char*)&num_actions, 1);
        
        if (state_id == active_idle_state) {
            interval_min_sec = s_min;
            interval_max_sec = s_max;
            idle_action_count = num_actions;
            
            if (idle_action_count > 0) {
                idle_actions = new BinIdleAction[idle_action_count];
                for (uint8_t i = 0; i < idle_action_count; i++) {
                    f.readBytes(idle_actions[i].anim_name, 32);
                    f.readBytes((char*)&idle_actions[i].weight, 1);
                    f.readBytes((char*)&idle_actions[i].variance, 1);
                    f.readBytes((char*)&idle_actions[i].cooldown_sec, 2);
                    
                    idle_actions[i].last_played_time = 0;
                    idle_actions[i].linked_anim_index = -1;
                    
                    for (int a = 0; a < activeAnimationCount; a++) {
                        if (strncmp(idle_actions[i].anim_name, activeAnimations[a].name, 32) == 0) {
                            idle_actions[i].linked_anim_index = a;
                            break;
                        }
                    }
                }
            }
            break; 
        } else {
            f.seek(f.position() + (num_actions * 36)); 
        }
    }
    f.close();
    next_idle_trigger = millis() + random((long)(interval_min_sec * 1000), (long)(interval_max_sec * 1000));
}

void loadAllAssets() {
  File imgDir = FFat.open("/img");
  if (imgDir && imgDir.isDirectory()) {
    File file = imgDir.openNextFile();
    while (file) {
      String fname = file.name();
      int slashIdx = fname.lastIndexOf('/');
      if (slashIdx >= 0) fname = fname.substring(slashIdx + 1);
      int idx = fname.toInt();
      if (idx >= 0 && idx < MAX_ASSETS && cachedImages[idx] == nullptr) {
        size_t sz = file.size();
        void* psramBuf = heap_caps_malloc(sz, MALLOC_CAP_SPIRAM);
        if (psramBuf) {
          file.read((uint8_t*)psramBuf, sz);
          cachedImages[idx] = (uint16_t*)psramBuf;
        }
      }
      file.close(); file = imgDir.openNextFile();
    }
  }

  File audioDir = FFat.open("/audio");
  if (audioDir && audioDir.isDirectory()) {
    File file = audioDir.openNextFile();
    while (file) {
      String fname = file.name();
      int slashIdx = fname.lastIndexOf('/');
      if (slashIdx >= 0) fname = fname.substring(slashIdx + 1);
      int idx = fname.toInt();
      
      if (idx >= 0 && idx < MAX_ASSETS) {
        audioPaths[idx] = file.path();
      }
      file.close(); file = audioDir.openNextFile();
    }
  }
}

// =========================================================================
// HYBRID STREAM PARSER (Fast 1-Byte for Servos, Secure 3-Byte for System)
// =========================================================================
void processStream(Stream &stream) {
    if (stream.available() > 0) {
        last_tcp_rx_time = millis(); // Reset idle timer when data arrives
    }

    while (stream.available() > 0) {
        uint8_t header = stream.read();
        
        // --- 1. FAST 1-BYTE ROUTE (Live Servos / Animations) ---
        if (header == 'd') {
            enable_debug_log = !enable_debug_log;
            Serial.println(enable_debug_log ? "\n--- KINEMATICS DEBUG ENABLED ---" : "\n--- KINEMATICS DEBUG DISABLED ---");
        }
        else if (header == 'm') {
            engine_states[1].target_position = (engine_states[1].target_position > 1500) ? 500 : 2500;
            engine_states[1].target_velocity = 80;
            joint_is_active[1] = true;
            ROBOT_CONFIG[1].max_acc = 4;
            ROBOT_CONFIG[1].max_spd = 120;
        }
        else if (header == 0xAA) {
            uint8_t count;
            unsigned long wait_t = millis();
            while (stream.available() < 1 && (millis() - wait_t < 50)) { delay(1); }
            
            if (stream.readBytes(&count, 1) == 1 && count <= 16) {
                int expected_bytes = count * 3;
                wait_t = millis();
                while (stream.available() < expected_bytes && (millis() - wait_t < 100)) { delay(1); }
                
                if (stream.available() >= expected_bytes) {
                    for (uint8_t i = 0; i < count; i++) {
                        uint8_t packet[3];
                        stream.readBytes(packet, 3);
                        last_interaction_time = millis(); 
                        if (joint_is_active[packet[0]] && active_anim_id != 0) active_anim_id = 0;
                        pushCommandToEngine(packet[0], packet[1], packet[2]);
                    }
                }
            } 
        }
        
        // --- 2. SECURE 3-BYTE PREAMBLE ROUTE ('W' 'L' 'E') FOR SYSTEM/FILES ---
        else if (header == 0x57) { // 'W'
            unsigned long wait_t = millis();
            while (stream.available() < 3 && (millis() - wait_t < 250)) { vTaskDelay(1); }
            
            if (stream.available() >= 3) {
                if (stream.read() == 0x4C && stream.read() == 0x45) { // 'L' 'E'
                    uint8_t sys_header = stream.read();
                    
                    if (sys_header == 0x02) {
                        // --- UNIFIED PSRAM TRANSFER PIPELINE (BLOCKING) ---
                        wait_t = millis();
                        while (stream.available() < 73 && (millis() - wait_t < 1000)) { vTaskDelay(1); }
                        
                        if (stream.available() >= 73) {
                            uint8_t file_type = stream.read();
                            uint32_t expected_size;
                            uint32_t expected_crc;
                            
                            // FIX: Increased buffer to 64 bytes to survive long paths
                            char filename[64] = {0}; 
                            
                            stream.readBytes((char*)&expected_size, 4);
                            stream.readBytes((char*)&expected_crc, 4);
                            stream.readBytes(filename, 64);
                            filename[63] = '\0'; // Hard safety null-terminator
                            
                            if (expected_size > 4194304) {
                                Serial.println("Transfer rejected: File exceeds 4MB PSRAM safety limit.");
                                while(stream.available()) stream.read();
                                continue; 
                            }
                            
                            uint8_t* psram_buf = (uint8_t*)heap_caps_malloc(expected_size, MALLOC_CAP_SPIRAM);
                            
                            if (psram_buf != nullptr) {
                                stream.write(ACK_BYTE); // Initial PSRAM Allocation ACK
                                uint32_t received = 0;
                                unsigned long last_data_time = millis();
                                
                                while (received < expected_size) {
                                    int avail = stream.available();
                                    if (avail > 0) {
                                        int to_read = min((uint32_t)avail, expected_size - received);
                                        stream.readBytes(psram_buf + received, to_read);
                                        received += to_read;
                                        last_data_time = millis();
                                    }
                                    
                                    if (received > 0 && (millis() - last_data_time > 2000)) {
                                        Serial.println("Transfer aborted: 2-second timeout exceeded mid-stream.");
                                        break; 
                                    }
                                    
                                    if ((Stream*)&activeClient == &stream && !activeClient.connected()) {
                                        Serial.println("Transfer aborted: TCP Client disconnected.");
                                        break;
                                    }
                                    
                                    vTaskDelay(1);
                                }
                                
                                if (received == expected_size) {
                                    if (calculateCRC32(psram_buf, expected_size) == expected_crc) {
                                        String path = String(filename);
                                        if (!path.startsWith("/")) path = "/" + path;
                                        if (path.startsWith("/audio") && !FFat.exists("/audio")) FFat.mkdir("/audio");
                                        if (path.startsWith("/img") && !FFat.exists("/img")) FFat.mkdir("/img");
                                        
                                        File f = FFat.open(path, FILE_WRITE);
                                        if (f) {
                                            f.write(psram_buf, expected_size);
                                            f.close();
                                            processCompletedFile(file_type, filename); 
                                            stream.write(ACK_BYTE); // Final Success ACK
                                        }
                                    } else {
                                        Serial.println("Transfer failed: CRC mismatch.");
                                    }
                                }
                                heap_caps_free(psram_buf);
                            } else {
                                Serial.println("Transfer failed: Insufficient PSRAM.");
                                while(stream.available()) stream.read();
                            }
                        }
                    }
                    else if (sys_header == 0xBB) {
                        uint8_t cmd;
                        if (stream.readBytes(&cmd, 1) == 1 && cmd == 0x01) {
                            uint32_t cv = 0;
                            if (FFat.exists("/config.bin")) {
                                File f = FFat.open("/config.bin", "r");
                                if (f && f.size() >= 8) { f.seek(4); f.read((uint8_t*)&cv, 4); }
                                if (f) f.close();
                            }
                            stream.write((uint8_t*)&cv, 4);
                        }
                    }
                    else if (sys_header == 0xCC) {
                        uint8_t cmd;
                        if (stream.readBytes(&cmd, 1) == 1 && cmd == 0x01) {
                            uint32_t ch = 0;
                            if (FFat.exists("/anims.bin")) {
                                File f = FFat.open("/anims.bin", "r");
                                if (f && f.size() >= 8) { f.seek(4); f.read((uint8_t*)&ch, 4); }
                                if (f) f.close();
                            }
                            stream.write((uint8_t*)&ch, 4);
                        }
                    }
                    else if (sys_header == 0xEE) {
                        uint8_t cmd;
                        if (stream.readBytes(&cmd, 1) == 1) {
                            if (cmd == 0x01) { 
                                String dirs[2] = {"/img", "/audio"};
                                for (int d = 0; d < 2; d++) {
                                    File dir = FFat.open(dirs[d]);
                                    if (dir && dir.isDirectory()) {
                                        File file = dir.openNextFile();
                                        while (file) {
                                            String path = file.path();
                                            if (!path.startsWith("/")) path = "/" + path;
                                            stream.print(path + ":" + String(file.size()) + "\n");
                                            file.close();
                                            file = dir.openNextFile();
                                        }
                                        dir.close();
                                    }
                                }
                                stream.print("END_OF_MANIFEST\n");
                            }
                            else if (cmd == 0x05) { 
                                uint8_t nameLen;
                                if (stream.readBytes(&nameLen, 1) == 1) {
                                    char fName[64] = {0};
                                    if (stream.readBytes(fName, nameLen) == nameLen) {
                                        FFat.remove(String(fName));
                                        stream.write(ACK_BYTE);
                                    }
                                }
                            }
                            else if (cmd == 0x06) { 
                                for(int i = 0; i < MAX_ASSETS; i++) {
                                    if (cachedImages[i] != nullptr) {
                                        heap_caps_free(cachedImages[i]);
                                        cachedImages[i] = nullptr;
                                    }
                                }
                                loadAllAssets(); 
                                stream.write(ACK_BYTE);
                            }
                        }
                    }
                    else if (sys_header == 0xFF) {
                        uint8_t cmd;
                        if (stream.readBytes(&cmd, 1) == 1 && cmd == 0x01) {
                            uint8_t lengths[2];
                            if (stream.readBytes(lengths, 2) == 2) {
                                char ssid_buf[64] = {0};
                                char pass_buf[64] = {0};
                                if (stream.readBytes(ssid_buf, lengths[0]) == lengths[0] &&
                                    stream.readBytes(pass_buf, lengths[1]) == lengths[1]) {
                                    preferences.begin("wifi", false);
                                    preferences.putString("ssid", String(ssid_buf));
                                    preferences.putString("pass", String(pass_buf));
                                    preferences.end();
                                    stream.write(ACK_BYTE);
                                    delay(100);
                                    ESP.restart();
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
// --- END OF FILE ---