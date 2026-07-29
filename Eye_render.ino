// ==========================================================
// WLE5 VIRTUAL EYE RENDERING PIPELINE
// This tab is automatically merged with walle_engine.ino
// ==========================================================

#define EXT_R(c) (((c) >> 11) & 0x1F)
#define EXT_G(c) (((c) >> 5) & 0x3F)
#define EXT_B(c) ((c) & 0x1F)
#define PACK_565(r, g, b) (((r) << 11) | ((g) << 5) | (b))
#define SWAP_565(c) (uint16_t)(((c) >> 8) | ((c) << 8))

void renderEyeFrame(float t, bool isRightEye) {
  img.fillSprite(TFT_BLACK);
  
  int gazeX = engine_states[isRightEye && isAsymmetric ? V_R_GAZE_X : V_GAZE_X].current_position;
  int gazeY = engine_states[isRightEye && isAsymmetric ? V_R_GAZE_Y : V_GAZE_Y].current_position;
  int eyelid = engine_states[isRightEye && isAsymmetric ? V_R_EYELID : V_EYELID].current_position;
  
  int pulse = engine_states[V_GLOW_PULSE].current_position;
  int hue = engine_states[V_GLOW_COLOR].current_position;
  int aperture = engine_states[V_APERTURE].current_position;
  int assetIdx = engine_states[V_IMG_SELECT].current_position;
  int assetAlpha = engine_states[V_IMG_OPACITY].current_position;

  // 1. Render Iris Tunnel (Bottom Layer)
  int offsetX = map(gazeX, 0, 255, -40, 40); 
  int offsetY = map(gazeY, 0, 255, -40, 40);
  int r_base = (pulse > 0) ? constrain((int)(127.5 + 127.5 * sin(t * 1.5 + (hue/255.0))), 0, 255) : 100;
  int g_base = (pulse > 0) ? constrain((int)(127.5 + 127.5 * sin(t * 1.1 + 2.0)), 0, 255) : 100;
  int b_base = (pulse > 0) ? constrain((int)(127.5 + 127.5 * sin(t * 0.8 + 4.0)), 0, 255) : 100;

  float pulse_factor = (pulse > 0) ? (pulse / 255.0) : 1.0; 

  uint16_t grad_color[200]; 
  for(int r = 0; r <= 150; r++) {
     float f = 1.0f - ((float)r / 150.0f);
     float intensity = pulse_factor * f * sqrt(f); 
     grad_color[r] = SWAP_565(tft.color565(r_base * intensity, g_base * intensity, b_base * intensity));
  }

  uint16_t* ptr = (uint16_t*)img.getPointer();
  for(int y = 0; y < HEIGHT; y++) {
     int dy = abs(y - (CENTER_Y + offsetY)); if (dy > 119) dy = 119;
     for(int x = 0; x < WIDTH; x++) {
        int dx = abs(x - (CENTER_X + offsetX)); if (dx > 119) dx = 119;
        int r = dist_map[dy][dx];
        if (r <= 150) *ptr = grad_color[r];
        ptr++; 
     }
  }

  // 2. Render Shutter Mechanism (Over Iris)
  float aperture_radius = map(aperture, 0, 255, 20, 90);
  float rot_rad = (t * -13.0) * PI / 180.0;
  int cx = CENTER_X + offsetX; 
  int cy = CENTER_Y + offsetY;

  for (int i = 0; i < 12; i++) {
    float angle1 = (i * (360.0 / 12)) * PI / 180.0 + rot_rad;
    float angle2 = ((i + 1) * (360.0 / 12)) * PI / 180.0 + rot_rad;
    float p1_x = cx + aperture_radius * cos(angle1); float p1_y = cy + aperture_radius * sin(angle1);
    float p2_x = cx + aperture_radius * cos(angle2); float p2_y = cy + aperture_radius * sin(angle2);
    float p3_x = cx + 200.0 * cos(angle2 + (45.0 * PI / 180.0)); float p3_y = cy + 200.0 * sin(angle2 + (45.0 * PI / 180.0));
    float p4_x = cx + 200.0 * cos(angle1 + (45.0 * PI / 180.0)); float p4_y = cy + 200.0 * sin(angle1 + (45.0 * PI / 180.0));

    uint16_t bc = (i % 2 == 0) ? tft.color565(55, 55, 60) : tft.color565(60, 60, 65);
    img.fillTriangle(p1_x, p1_y, p2_x, p2_y, p3_x, p3_y, bc);
    img.fillTriangle(p1_x, p1_y, p3_x, p3_y, p4_x, p4_y, bc);
    img.drawLine(p1_x, p1_y, p2_x, p2_y, tft.color565(80, 80, 85));
    img.drawLine(p1_x, p1_y, p4_x, p4_y, tft.color565(30, 30, 35));
  }

  // 3. Render Anti-Aliased Outer Eye Ring (Fast Memory Pass)
  uint16_t ring_col_raw = tft.color565(25, 25, 30);
  uint16_t ring_col_swap = SWAP_565(ring_col_raw);
  uint16_t* ptr_mask = (uint16_t*)img.getPointer();
  
  for (int y = 0; y < HEIGHT; y++) {
      int dy = abs(y - CENTER_Y); 
      if (dy > 119) dy = 119;
      
      for (int x = 0; x < WIDTH; x++) {
          int dx = abs(x - CENTER_X); 
          if (dx > 119) dx = 119;
          
          uint8_t alpha = bezel_mask[dy][dx];
          if (alpha == 255) {
              *ptr_mask = ring_col_swap;
          } else if (alpha > 0) {
              uint16_t bg = SWAP_565(*ptr_mask);
              uint16_t r = (EXT_R(ring_col_raw) * alpha + EXT_R(bg) * (255 - alpha)) >> 8;
              uint16_t g = (EXT_G(ring_col_raw) * alpha + EXT_G(bg) * (255 - alpha)) >> 8;
              uint16_t b = (EXT_B(ring_col_raw) * alpha + EXT_B(bg) * (255 - alpha)) >> 8;
              *ptr_mask = SWAP_565(PACK_565(r, g, b));
          }
          ptr_mask++;
      }
  }

  // 4. Render Mechanical Eyelids (Top Layer)
  float closure = eyelid / 255.0; 
  if (closure > 0.005) {
    int lid_height = (int)((HEIGHT / 2.0) * closure) + 2;
    uint16_t flap_col = tft.color565(75, 75, 80);
    uint16_t groove_col = tft.color565(40, 40, 45);
    uint16_t edge_col = tft.color565(20, 20, 25);

    img.fillRect(0, 0, WIDTH, lid_height, flap_col);
    img.fillRect(0, HEIGHT - lid_height, WIDTH, lid_height, flap_col);

    for (int y = lid_height - 12; y >= 0; y -= 12) {
        img.drawFastHLine(0, y, WIDTH, groove_col);
    }
    for (int y = HEIGHT - lid_height + 12; y < HEIGHT; y += 12) {
        img.drawFastHLine(0, y, WIDTH, groove_col);
    }

    img.drawFastHLine(0, lid_height - 1, WIDTH, edge_col);
    img.drawFastHLine(0, lid_height - 2, WIDTH, edge_col);
    
    img.drawFastHLine(0, HEIGHT - lid_height, WIDTH, edge_col);
    img.drawFastHLine(0, HEIGHT - lid_height + 1, WIDTH, edge_col);
  }

  // 5. Render Image Layer Overlay (Post-Processing)
  if (assetIdx > 0 && assetIdx < MAX_ASSETS && cachedImages[assetIdx] != nullptr && assetAlpha > 0) {
    uint16_t* fp = (uint16_t*)img.getPointer();
    uint16_t* sp = cachedImages[assetIdx];
    int c = WIDTH * HEIGHT;
    while(c--) {
      if (c % 4000 == 0) taskYIELD(); 
      uint16_t r = (EXT_R(*sp) * assetAlpha + EXT_R(SWAP_565(*fp)) * (255 - assetAlpha)) >> 8;
      uint16_t g = (EXT_G(*sp) * assetAlpha + EXT_G(SWAP_565(*fp)) * (255 - assetAlpha)) >> 8;
      uint16_t b = (EXT_B(*sp) * assetAlpha + EXT_B(SWAP_565(*fp)) * (255 - assetAlpha)) >> 8;
      *fp++ = SWAP_565(PACK_565(r, g, b));
      sp++;
    }
  }
}