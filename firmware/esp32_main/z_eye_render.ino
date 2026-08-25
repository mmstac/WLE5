// ==========================================================
// WLE5 VIRTUAL EYE RENDERING PIPELINE
// This tab is automatically merged with walle_engine.ino
// ==========================================================

#include "robot_config.h" 

// --- DEBUG SETTINGS ---
extern bool SHOW_DEBUG; // Pulled from Walle-double.ino

// Pull global variables from Walle-double.ino
extern uint16_t current_physics_hz;     
extern uint16_t current_gfx_hz;
extern int currentFPS;
extern unsigned long last_render_time_ms;
extern unsigned long last_spi_time_ms;

#define EXT_R(c) (((c) >> 11) & 0x1F)
#define EXT_G(c) (((c) >> 5) & 0x3F)
#define EXT_B(c) ((c) & 0x1F)
#define PACK_565(r, g, b) (((r) << 11) | ((g) << 5) | (b))
#define SWAP_565(c) (uint16_t)(((c) >> 8) | ((c) << 8))

// --- ASCII GLYPH MATRICES (16x20) ---
const char* heart_pixels[] = {
    "....................",
    "....####....####....",
    "..#######..#######..",
    ".##################.",
    ".##################.",
    ".##################.",
    ".##################.",
    "..################..",
    "...##############...",
    "....############....",
    ".....##########.....",
    ".......######.......",
    "........####........",
    ".........##.........",
    ".........##.........",
    "...................."
};

const char* smiley_pixels[] = {
    "......########......",
    "....############....",
    "...##############...",
    "..################..",
    ".##################.",
    ".##################.",
    "####################",
    "###...########...###",
    "###...########...###",
    "###...########...###",
    "####################",
    "###..............###",
    "####............####",
    ".######......######.",
    "..################..",
    "..################..",
    "...##############...",
    "...##############...",
    "....############....",
    "......########......"
};

const char* plant_pixels[] = {
    ".........#..........",
    ".......#.#.#........",
    "......##.#.##.......",
    "......##.#.##.......",
    ".....###.#.###......",
    "....####.#.####.....",
    "....####.#.####.....",
    "......##.#.##.......",
    "..##.....#.....##...",
    "..###....#....###...",
    "...####..#..####....",
    "...#####.#.#####....",
    "....####.#.####.....",
    ".....###.#.###......",
    ".......#.#.#........",
    ".........#..........",
};

// --- ROW BOUNDS TRACKER (Calculated on Boot) ---
static uint8_t min_x[234];
static uint8_t max_x[234];
static bool bounds_calculated = false;

// --- OPTIMIZED VOXEL BLENDING CORE ---
void blend_voxel(int x, int y, int size, uint16_t main_color, uint16_t gap_color, uint8_t a) {
  if (a == 0) return;
  uint16_t* frame_ptr = (uint16_t*)img.getPointer();
  
  // FAST BLEND: Scale alpha to 0-32 to prevent channel bleed
  uint32_t a5 = a >> 3;
  uint32_t inv_a5 = 32 - a5;
  
  // Pre-split the Red/Blue and Green channels
  uint32_t m_rb = main_color & 0xF81F;
  uint32_t m_g  = main_color & 0x07E0;
  uint32_t g_rb = gap_color & 0xF81F;
  uint32_t gap_g = gap_color & 0x07E0;
  
  for (int iy = max(0, y); iy < min(HEIGHT, y + size); iy++) {
    int row_offset = iy * WIDTH;
    for (int ix = max(0, x); ix < min(WIDTH, x + size); ix++) {
      int i = row_offset + ix;
      
      uint16_t bg_raw = SWAP_565(frame_ptr[i]);
      uint32_t bg_rb = bg_raw & 0xF81F;
      uint32_t bg_g  = bg_raw & 0x07E0;
      
      bool is_gap = (ix == x + size - 1) || (iy == y + size - 1);
      uint32_t fg_rb = is_gap ? g_rb : m_rb;
      uint32_t fg_g  = is_gap ? gap_g : m_g;
      
      // Parallel multiply and shift down by 5 (divide by 32)
      uint32_t rb = ((fg_rb * a5 + bg_rb * inv_a5) >> 5) & 0xF81F;
      uint32_t g_blend = ((fg_g * a5 + bg_g * inv_a5) >> 5) & 0x07E0;
      
      frame_ptr[i] = SWAP_565((uint16_t)(rb | g_blend));
    }
  }
}

// --- GLYPH DRAWING FUNCTIONS ---
void draw_heart(int cx, int cy, uint8_t alpha) {
  int pixel_size = 10; 
  int start_x = cx - 10 * pixel_size + 5; 
  int start_y = cy - 8 * pixel_size + 8;
  uint16_t gap_color = tft.color565(120, 15, 25);
  
  for (int row = 0; row < 16; row++) {
    for (int col = 0; col < 20; col++) {
      if (heart_pixels[row][col] == '#') {
        uint16_t color = tft.color565(220, 20, 40);
        if ((row == 2 && col >= 3 && col <= 5) || (row == 3 && col >= 3 && col <= 4)) {
            color = tft.color565(255, 120, 130);
        }
        blend_voxel(start_x + col * pixel_size, start_y + row * pixel_size, pixel_size, color, gap_color, alpha);
      }
    }
  }
}

void draw_smiley(int cx, int cy, uint8_t alpha) {
  int pixel_size = 10; 
  int start_x = cx - 10 * pixel_size + 3; 
  int start_y = cy - 10 * pixel_size + 3;
  uint16_t gap_color = tft.color565(180, 130, 0); 
  
  for (int row = 0; row < 20; row++) {
    for (int col = 0; col < 20; col++) {
      if (smiley_pixels[row][col] == '#') {
        uint16_t color = tft.color565(255, 220, 20); 
        blend_voxel(start_x + col * pixel_size, start_y + row * pixel_size, pixel_size, color, gap_color, alpha);
      }
    }
  }
}

void draw_plant(int cx, int cy, uint8_t alpha) {
  int pixel_size = 10; 
  int start_x = cx - 10 * pixel_size + 5; 
  int start_y = cy - 8 * pixel_size + 8;
  uint16_t gap_color = tft.color565(10, 120, 20); 
  
  for (int row = 0; row < 16; row++) {
    for (int col = 0; col < 20; col++) {
      if (plant_pixels[row][col] == '#') {
        uint16_t color = tft.color565(30, 220, 50); 
        blend_voxel(start_x + col * pixel_size, start_y + row * pixel_size, pixel_size, color, gap_color, alpha);
      }
    }
  }
}

void renderEyeFrame(float t, bool isRightEye) {
// Pre-calculate circular bounds on the very first frame to avoid edge math
  if (!bounds_calculated) {
      for (int y = 0; y < HEIGHT; y++) {
          int dy = abs(y - CENTER_Y);
          if (dy > 119) dy = 119;
          int start = 0;
          int end = WIDTH - 1;
          // FIX: Expanded from 116 to 118 to cover the absolute edge of the 234x234 buffer
          while (start < CENTER_X && dist_map[dy][abs(start - CENTER_X)] >= 118) start++;
          while (end > CENTER_X && dist_map[dy][abs(end - CENTER_X)] >= 118) end--;
          min_x[y] = start;
          max_x[y] = end;
      }
      bounds_calculated = true;
  }
  
  int gazeX = engine_states[isRightEye && isAsymmetric ? V_R_GAZE_X : V_GAZE_X].current_position;
  int gazeY = engine_states[isRightEye && isAsymmetric ? V_R_GAZE_Y : V_GAZE_Y].current_position;
  int eyelid = engine_states[isRightEye && isAsymmetric ? V_R_EYELID : V_EYELID].current_position;
  
  int current_pulse = engine_states[V_GLOW_PULSE].current_position; 
  int target_hue = engine_states[V_GLOW_COLOR].target_position;
  int aperture = engine_states[V_APERTURE].current_position;
  int assetIdx = engine_states[V_IMG_SELECT].current_position;
  int assetAlpha = engine_states[V_IMG_OPACITY].current_position;

  int offsetX = map(gazeX, 0, 255, -40, 40); 
  int offsetY = map(gazeY, 0, 255, -40, 40);
  int cx = CENTER_X + offsetX; 
  int cy = CENTER_Y + offsetY;

  // --- 1. LOCAL MINIMUM TROUGH SYNC (COLOR ONLY) ---
  static int active_hue = target_hue;
  static float last_breath = 0.0f;
  static bool breath_is_falling = false;
  
  float organic_breath = sin(t * 0.8f); 

  if (organic_breath < last_breath) {
      breath_is_falling = true;
  } else if (breath_is_falling) {
      active_hue = target_hue; 
      breath_is_falling = false;
  }
  last_breath = organic_breath;

  // --- 2. CALCULATE ENVELOPE BREATHING & BASE HUES ---
  int r_base = 0, g_base = 0, b_base = 0;
  float pulse_factor = 0.0;

  if (active_hue == 0) {
      r_base = 40; g_base = 40; b_base = 45;
      pulse_factor = 0.3f;
  } else {
      uint8_t current_hue = (active_hue == 255) ? (uint8_t)((int)(t * 60.0) % 255) : map(active_hue, 1, 254, 0, 255);
      
      if (current_hue < 85) { r_base = 255 - current_hue * 3; g_base = current_hue * 3; b_base = 0; } 
      else if (current_hue < 170) { current_hue -= 85; r_base = 0; g_base = 255 - current_hue * 3; b_base = current_hue * 3; } 
      else { current_hue -= 170; r_base = current_hue * 3; g_base = 0; b_base = 255 - current_hue * 3; }

      float target_intensity = (current_pulse == 0) ? 0.8f : (0.4f + ((current_pulse / 255.0f) * 0.6f)); 
      float breath_mult = 0.6f + 0.4f * ((organic_breath + 1.0f) / 2.0f); 
      pulse_factor = target_intensity * breath_mult; 
  }

  int focus_radius = map(aperture, 0, 255, 20, 80); 
  int max_g_rad = (focus_radius - 2) > 5 ? (focus_radius - 2) : 5;

  uint16_t grad_color[120]; 
  for(int r = 0; r < 120; r++) {
     if (r >= max_g_rad) {
         grad_color[r] = SWAP_565(tft.color565(25, 25, 30));
     } else {
         float f = 1.0f - ((float)r / (float)max_g_rad);
         float intensity = pulse_factor * (f * (2.0f - f)); 
         
         grad_color[r] = SWAP_565(tft.color565(
             (uint8_t)(r_base * intensity), 
             (uint8_t)(g_base * intensity), 
             (uint8_t)(b_base * intensity)
         ));
     }
  }

  // --- 3. SET UP COLOR PALETTE & BOUNDARIES ---
  uint16_t bg_color    = SWAP_565(tft.color565(45, 45, 50)); 
  uint16_t ring_light  = SWAP_565(tft.color565(75, 75, 85));
  // uint16_t ring_light  = SWAP_565(tft.color565(160, 160, 170)); 
  uint16_t ring_dark   = SWAP_565(tft.color565(35, 35, 40));    

  int r_glow_sq       = (focus_radius - 2) * (focus_radius - 2);     
  int r_inner_dark_sq = focus_radius * focus_radius;           
  int r_light_sq      = (focus_radius + 15) * (focus_radius + 15); 
  int r_outer_dark_sq = (focus_radius + 17) * (focus_radius + 17); 

  uint16_t* ptr = (uint16_t*)img.getPointer();
  
  // --- 4. UNIFIED SINGLE-PASS PIXEL SHADER (Row Bounded) ---
  for(int y = 0; y < HEIGHT; y++) {
      int dy_screen = abs(y - CENTER_Y);
      if (dy_screen > 119) dy_screen = 119;
      
      int x_start = min_x[y];
      int x_end = max_x[y];

      // A. Fast-clear left dead corner
      if (x_start > 0) {
          memset(ptr, 0, x_start * 2); // 2 bytes per pixel
          ptr += x_start;
      }

      // B. Process visible pixels ONLY
      for(int x = x_start; x <= x_end; x++) {
          int dx_screen = abs(x - CENTER_X);
          int dist_screen = dist_map[dy_screen][dx_screen];

          if (dist_screen > 97) {
              // FIX: Stretch the bezel gradient out to the 118 boundary and cleanly fade to 0
              int v_int = map(dist_screen, 98, 118, 30, 0); 
              
              // CLAMP: Prevent integer underflow wrapping to bright green!
              if (v_int < 0) v_int = 0; 
              
              *ptr++ = SWAP_565(tft.color565(v_int, v_int, v_int));
              continue; 
          }

          int dx = abs(x - cx);
          int dy = abs(y - cy);
          int dist_sq = dx * dx + dy * dy; 

          if (dist_sq <= r_glow_sq) {
              if (dx > 119) dx = 119; if (dy > 119) dy = 119; 
              int dist_iris = dist_map[dy][dx];
              if (dist_iris > 119) dist_iris = 119;
              *ptr++ = grad_color[dist_iris];
          } 
          else if (dist_sq <= r_inner_dark_sq) { *ptr++ = ring_dark; } 
          else if (dist_sq <= r_light_sq) { *ptr++ = ring_light; } 
          else if (dist_sq <= r_outer_dark_sq) { *ptr++ = ring_dark; } 
          else { *ptr++ = bg_color; }
      }
      
      // C. Fast-clear right dead corner
      int skip_right = WIDTH - 1 - x_end;
      if (skip_right > 0) {
          memset(ptr, 0, skip_right * 2);
          ptr += skip_right;
      }
  }

  // --- 5. Render Mechanical Eyelids (Top Layer) ---
  float closure = eyelid / 255.0; 
  if (closure > 0.005) {
    int lid_height = (int)((HEIGHT / 2.0) * closure) + 2;
    uint16_t flap_col = tft.color565(75, 75, 80);
    uint16_t groove_col = tft.color565(40, 40, 45);
    uint16_t edge_col = tft.color565(20, 20, 25);

    img.fillRect(0, 0, WIDTH, lid_height, flap_col);
    img.fillRect(0, HEIGHT - lid_height, WIDTH, lid_height, flap_col);

    for (int y = lid_height - 12; y >= 0; y -= 12) { img.drawFastHLine(0, y, WIDTH, groove_col); }
    for (int y = HEIGHT - lid_height + 12; y < HEIGHT; y += 12) { img.drawFastHLine(0, y, WIDTH, groove_col); }

    img.drawFastHLine(0, lid_height - 1, WIDTH, edge_col);
    img.drawFastHLine(0, lid_height - 2, WIDTH, edge_col);
    img.drawFastHLine(0, HEIGHT - lid_height, WIDTH, edge_col);
    img.drawFastHLine(0, HEIGHT - lid_height + 1, WIDTH, edge_col);
  }

  // --- 6. OPTIMIZED IMAGE BLENDING (Row Bounded & Math-Optimized) ---
  if (assetAlpha > 0) {
      if (assetIdx == 100) { draw_heart(cx, cy, assetAlpha); } 
      else if (assetIdx == 101) { draw_smiley(cx, cy, assetAlpha); } 
      else if (assetIdx == 102) { draw_plant(cx, cy, assetAlpha); } 
      else if (assetIdx > 0 && assetIdx < 20 && cachedImages[assetIdx] != nullptr) {
          uint16_t* fp = (uint16_t*)img.getPointer();
          uint16_t* sp = cachedImages[assetIdx];
          
          // FAST BLEND: Scale alpha to 0-32
          uint32_t a5 = assetAlpha >> 3;
          uint32_t inv_a5 = 32 - a5;
          
          for(int y = 0; y < HEIGHT; y++) {
              if (y % 16 == 0) taskYIELD(); // Feed the watchdog safely
              
              int x_start = min_x[y];
              int x_end = max_x[y];
              
              fp += x_start;
              sp += x_start;
              
              for(int x = x_start; x <= x_end; x++) {
                  uint16_t fg = *sp++;
                  uint16_t bg_raw = SWAP_565(*fp);
                  
                  // Split R/B and G channels separately
                  uint32_t fg_rb = fg & 0xF81F;
                  uint32_t fg_g  = fg & 0x07E0;
                  uint32_t bg_rb = bg_raw & 0xF81F;
                  uint32_t bg_g  = bg_raw & 0x07E0;
                  
                  // Blend in parallel and collapse
                  uint32_t rb = ((fg_rb * a5 + bg_rb * inv_a5) >> 5) & 0xF81F;
                  uint32_t g_blend = ((fg_g * a5 + bg_g * inv_a5) >> 5) & 0x07E0;
                  
                  *fp++ = SWAP_565((uint16_t)(rb | g_blend));
              }
              
              int skip_right = WIDTH - 1 - x_end;
              fp += skip_right;
              sp += skip_right;
          }
      }
  }

  // --- 7. DEBUG OVERLAY ---
  if (SHOW_DEBUG) {
      char line1[48];
      snprintf(line1, sizeof(line1), "Phys:%u | Loop:%u", current_physics_hz, current_gfx_hz);
      img.setTextDatum(BC_DATUM);
      img.setTextColor(TFT_GREEN, TFT_BLACK);
      img.drawString(line1, WIDTH / 2, HEIGHT - 5);
      
      char line2[24];
      snprintf(line2, sizeof(line2), "%d FPS", currentFPS);
      img.setTextDatum(TC_DATUM);
      img.drawString(line2, CENTER_X, 15, 2);
      
      char line3[48];
      snprintf(line3, sizeof(line3), "SPI: %lums | Rnd: %lums", last_spi_time_ms, last_render_time_ms);
      img.drawString(line3, CENTER_X, 35, 2);
  }
}
// === END OF FILE Eye_render.ino ===