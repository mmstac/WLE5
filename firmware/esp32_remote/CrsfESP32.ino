/*
 * radio_esp32.ino  (v0.2 — TTGO Lilygo T-Display bring-up)
 *
 * Companion ESP32 (TTGO T-Display) living near/in the EdgeTX JR module bay.
 * Speaks the private extended-CRSF command protocol (realm 0x50).
 */

#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <HardwareSerial.h>

struct TocEntry;
struct Joint;

#define TFT_CS_PIN  5
#define TFT_DC_PIN  16
#define TFT_RST_PIN 23
#define TFT_BL_PIN  4
#define TFT_SCLK_PIN 18
#define TFT_MOSI_PIN 19

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN);

// ---------------- on-screen debug log ----------------
#define LOG_LINES 8
String logBuf[LOG_LINES];

void screenLog(const String &s) {
  Serial.println(s);
  for (int i = 0; i < LOG_LINES - 1; i++) logBuf[i] = logBuf[i + 1];
  logBuf[LOG_LINES - 1] = s;
  tft.fillScreen(ST77XX_BLACK);
  for (int i = 0; i < LOG_LINES; i++) {
    tft.setCursor(0, i * 16);
    tft.println(logBuf[i]);
  }
}

// ---------------- CRSF link config ----------------
#define CRSF_BAUD     400000
#define CRSF_RX_PIN   25   
#define CRSF_TX_PIN   26   
HardwareSerial CrsfSerial(2);

#define CRSF_MAX_FRAME    64
#define CRSF_SYNC_TX      0xEE   
#define CRSF_ADDR_RADIO   0xEA   
#define CRSF_TYPE_COMMAND 0x32
#define REALM_TOC         0x50

enum Category : uint8_t { CAT_JOINTS = 0, CAT_ANIM = 1, CAT_AUDIO = 2, CAT_IMAGE = 3 };

enum Subcmd : uint8_t {
  SUB_REQUEST_COUNT = 0x01,
  SUB_COUNT_RESP    = 0x02,
  SUB_REQUEST_ENTRY = 0x03,
  SUB_ENTRY_RESP    = 0x04,
  SUB_SELECT_PLAY   = 0x05,
  SUB_ACK           = 0x06,
  SUB_SET_FAVORITE  = 0x07,
  SUB_REQUEST_JOINT = 0x10,
  SUB_JOINT_RESP    = 0x11,
  SUB_WRITE_JOINT   = 0x12,
  SUB_WRITE_ACK     = 0x13,
};

// ---------------- Data model ----------------
#define MAX_NAME_LEN     20
#define MAX_JOINTS       8
#define MAX_TOC_ENTRIES  8

struct TocEntry {
  uint16_t id;
  char name[MAX_NAME_LEN + 1];
  bool favorite;
};

struct Joint {
  uint16_t id;
  char name[MAX_NAME_LEN + 1];
  uint8_t type;        
  int16_t channel;     
  bool reverse;
  uint8_t mode;         
  uint16_t min_us, max_us, min_limit, max_limit;
  int16_t trim;
  bool mappable;        
};

TocEntry tocLists[3][MAX_TOC_ENTRIES];
uint16_t tocCounts[3] = {0, 0, 0};

Joint joints[MAX_JOINTS];
uint16_t jointCount = 0;

// ---------------- hardcoded test data ----------------
void setToc(uint8_t catIdx, uint16_t id, const char *name, bool fav) {
  TocEntry &e = tocLists[catIdx][id];
  e.id = id;
  strlcpy(e.name, name, sizeof(e.name));
  e.favorite = fav;
}

void seedTestData() {
  const char *animNames[6] = {"wave_hello", "sit", "stand", "bow", "dance_1", "look_around"};
  const char *audioNames[6] = {"greeting", "laugh", "alert_beep", "chime", "growl", "purr"};
  const char *imageNames[6] = {"happy_face", "confused", "heart_eyes", "sleep_zzz", "wink", "surprised"};
  for (uint16_t i = 0; i < 6; i++) {
    setToc(0, i, animNames[i], i < 3);
    setToc(1, i, audioNames[i], i < 2);
    setToc(2, i, imageNames[i], i < 1);
  }
  tocCounts[0] = 6; tocCounts[1] = 6; tocCounts[2] = 6;

  jointCount = 6;
  const char *jointNames[6] = {"shoulder_l", "shoulder_r", "elbow_l", "head_pan", "speaker_gain", "play_audio"};
  uint8_t jointTypes[6]    = {0, 0, 0, 0, 1, 1};
  int16_t jointChannels[6] = {0, 1, 2, -1, -1, -1};
  bool jointReverse[6]     = {false, true, false, false, false, false};
  uint8_t jointModes[6]    = {0, 0, 0, 0, 1, 0};
  bool jointMappable[6]    = {true, true, true, true, true, false}; 
  for (uint16_t i = 0; i < 6; i++) {
    Joint &j = joints[i];
    j.id = i;
    strlcpy(j.name, jointNames[i], sizeof(j.name));
    j.type = jointTypes[i];
    j.channel = jointChannels[i];
    j.reverse = jointReverse[i];
    j.mode = jointModes[i];
    j.mappable = jointMappable[i];
    if (j.type == 0) { 
      j.min_us = 1000; j.max_us = 2000;
      j.min_limit = (i == 3) ? 1200 : 1100; 
      j.max_limit = (i == 3) ? 1800 : 1900;
    } else { 
      j.min_us = 0; j.max_us = 255;
      j.min_limit = 0; j.max_limit = 255;
    }
    j.trim = 0;
  }

  screenLog("Seeded 6/6/6 lists");
}

// ---------------- CRSF low level ----------------
uint8_t crsfCrc8(const uint8_t *data, uint8_t len) {
  uint8_t crc = 0;
  for (uint8_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (uint8_t j = 0; j < 8; j++)
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0xD5) : (uint8_t)(crc << 1);
  }
  return crc;
}

void crsfSendExtCommand(uint8_t subcmd, const uint8_t *payload, uint8_t payloadLen) {
  uint8_t buf[CRSF_MAX_FRAME];
  uint8_t i = 0;
  buf[i++] = CRSF_ADDR_RADIO;
  uint8_t lenIdx = i++;
  uint8_t typeStart = i;
  buf[i++] = CRSF_TYPE_COMMAND;
  buf[i++] = CRSF_ADDR_RADIO;
  buf[i++] = CRSF_SYNC_TX;
  buf[i++] = REALM_TOC;
  buf[i++] = subcmd;
  if (payloadLen > 0 && i + payloadLen < CRSF_MAX_FRAME - 1) {
    memcpy(&buf[i], payload, payloadLen);
    i += payloadLen;
  }
  uint8_t crc = crsfCrc8(&buf[typeStart], i - typeStart);
  buf[i++] = crc;
  buf[lenIdx] = i - typeStart; 

  CrsfSerial.write(buf, i);
  CrsfSerial.flush();               

  delayMicroseconds(100);
  while (CrsfSerial.available()) CrsfSerial.read();

  Serial.printf("TX subcmd=0x%02X (%u bytes)\n", subcmd, i);
}

void sendCountResp(uint8_t category, uint16_t count) {
  uint8_t p[3] = { category, (uint8_t)(count & 0xFF), (uint8_t)(count >> 8) };
  crsfSendExtCommand(SUB_COUNT_RESP, p, 3);
}

void sendAck(uint8_t category, uint16_t index, uint8_t status) {
  uint8_t p[4] = { category, (uint8_t)(index & 0xFF), (uint8_t)(index >> 8), status };
  crsfSendExtCommand(SUB_ACK, p, 4);
}

void sendEntryResp(uint8_t category, uint16_t index, TocEntry &e) {
  uint8_t p[4 + MAX_NAME_LEN];
  p[0] = category;
  p[1] = index & 0xFF;
  p[2] = index >> 8;
  p[3] = e.favorite ? 0x01 : 0x00;
  uint8_t nameLen = strlen(e.name);
  memcpy(&p[4], e.name, nameLen);
  crsfSendExtCommand(SUB_ENTRY_RESP, p, 4 + nameLen);
}

void sendJointResp(Joint &j) {
  uint8_t p[16 + MAX_NAME_LEN];
  uint8_t i = 0;
  p[i++] = j.id & 0xFF; p[i++] = j.id >> 8;
  p[i++] = j.type;
  p[i++] = (j.channel < 0) ? 0xFF : (uint8_t)j.channel;
  p[i++] = j.reverse ? 0x01 : 0x00; 
  if (j.mappable) p[i - 1] |= 0x02;
  p[i++] = j.mode;
  p[i++] = j.min_us & 0xFF; p[i++] = j.min_us >> 8;
  p[i++] = j.max_us & 0xFF; p[i++] = j.max_us >> 8;
  p[i++] = j.min_limit & 0xFF; p[i++] = j.min_limit >> 8;
  p[i++] = j.max_limit & 0xFF; p[i++] = j.max_limit >> 8;
  p[i++] = (uint16_t)j.trim & 0xFF; p[i++] = ((uint16_t)j.trim) >> 8;
  uint8_t nameLen = strlen(j.name);
  memcpy(&p[i], j.name, nameLen);
  i += nameLen;
  crsfSendExtCommand(SUB_JOINT_RESP, p, i);
}

void sendWriteAck(uint16_t index, uint8_t status) {
  uint8_t p[3] = { (uint8_t)(index & 0xFF), (uint8_t)(index >> 8), status };
  crsfSendExtCommand(SUB_WRITE_ACK, p, 3);
}

String hexDump(const uint8_t *buf, uint8_t len) {
  String s = "";
  for (uint8_t i = 0; i < len; i++) {
    if (buf[i] < 0x10) s += "0";
    s += String(buf[i], HEX);
    s += " ";
  }
  return s;
}

void handleCommand(const uint8_t *payload, uint8_t payloadLen) {
  if (payloadLen < 1) return;
  uint8_t subcmd = payload[0];
  const uint8_t *p = payload + 1;
  uint8_t plen = payloadLen - 1;

  switch (subcmd) {
    case SUB_REQUEST_COUNT: {
      if (plen < 1) return;
      uint8_t cat = p[0];
      
      // FIXED: Screen log commented out to prevent SPI delay from breaking 400k baud CRSF link
      // screenLog("RX COUNT req cat=" + String(cat));
      
      if (cat == CAT_JOINTS) sendCountResp(cat, jointCount);
      else if (cat >= CAT_ANIM && cat <= CAT_IMAGE) sendCountResp(cat, tocCounts[cat - 1]);
      break;
    }
    case SUB_REQUEST_ENTRY: {
      if (plen < 3) return;
      uint8_t cat = p[0];
      uint16_t idx = p[1] | (p[2] << 8);
      
      // FIXED: Screen log commented out 
      // screenLog("RX ENTRY req cat=" + String(cat) + " idx=" + String(idx));
      
      if (cat >= CAT_ANIM && cat <= CAT_IMAGE) {
        uint8_t ci = cat - 1;
        if (idx < tocCounts[ci]) sendEntryResp(cat, idx, tocLists[ci][idx]);
        else sendAck(cat, idx, 1);
      }
      break;
    }
    case SUB_SELECT_PLAY: {
      if (plen < 3) return;
      uint8_t cat = p[0];
      uint16_t idx = p[1] | (p[2] << 8);
      uint16_t count = (cat == CAT_JOINTS) ? jointCount : (cat >= CAT_ANIM && cat <= CAT_IMAGE ? tocCounts[cat - 1] : 0);
      if (idx < count) {
        String name = (cat >= CAT_ANIM && cat <= CAT_IMAGE) ? tocLists[cat - 1][idx].name : "?";
        screenLog("PLAY cat=" + String(cat) + " " + name);
        sendAck(cat, idx, 0);
      } else {
        screenLog("PLAY out of range");
        sendAck(cat, idx, 1);
      }
      break;
    }
    case SUB_SET_FAVORITE: {
      if (plen < 4) return;
      uint8_t cat = p[0];
      uint16_t idx = p[1] | (p[2] << 8);
      uint8_t fav = p[3];
      if (cat >= CAT_ANIM && cat <= CAT_IMAGE && idx < tocCounts[cat - 1]) {
        tocLists[cat - 1][idx].favorite = (fav != 0);
        screenLog("FAV cat=" + String(cat) + " idx=" + String(idx) + "=" + String(fav));
        sendAck(cat, idx, 0);
      } else {
        sendAck(cat, idx, 1);
      }
      break;
    }
    case SUB_REQUEST_JOINT: {
      if (plen < 2) return;
      uint16_t idx = p[0] | (p[1] << 8);
      
      // No screenLog here natively, but confirming it stays clean
      if (idx < jointCount) sendJointResp(joints[idx]);
      else sendWriteAck(idx, 1);
      break;
    }
    case SUB_WRITE_JOINT: {
      if (plen < 16) return;
      uint16_t idx = p[0] | (p[1] << 8);
      if (idx >= jointCount) { sendWriteAck(idx, 1); break; }
      Joint &j = joints[idx];
      j.type = p[2];
      if (j.mappable) {
        j.channel = (p[3] == 0xFF) ? -1 : (int16_t)p[3];
      }
      j.reverse = p[4] & 0x01;
      j.mode = p[5];
      j.min_us = p[6] | (p[7] << 8);
      j.max_us = p[8] | (p[9] << 8);
      j.min_limit = p[10] | (p[11] << 8);
      j.max_limit = p[12] | (p[13] << 8);
      j.trim = (int16_t)(p[14] | (p[15] << 8));
      screenLog("WRITE joint " + String(idx));
      sendWriteAck(idx, 0);
      break;
    }
    default:
      screenLog("Unknown subcmd " + String(subcmd, HEX));
  }
}

void handleFrame(const uint8_t *buf, uint8_t totalLen) {
  uint8_t type = buf[2];
  if (type != CRSF_TYPE_COMMAND) return;
  if (totalLen < 8) return;
  uint8_t realm = buf[5];
  if (realm != REALM_TOC) return;
  const uint8_t *cmdPayload = &buf[6];
  uint8_t cmdPayloadLen = totalLen - 6 - 1;
  handleCommand(cmdPayload, cmdPayloadLen);
}

// ---------------- CRSF RX framer ----------------
uint8_t rxBuf[CRSF_MAX_FRAME];
uint8_t rxLen = 0;

void pollCrsfRx() {
  while (CrsfSerial.available()) {
    uint8_t b = CrsfSerial.read();
    if (rxLen == 0) { rxBuf[rxLen++] = b; continue; }
    if (rxLen == 1) {
      if (b < 2 || b > CRSF_MAX_FRAME - 2) { rxBuf[0] = b; rxLen = 1; continue; }
      rxBuf[rxLen++] = b;
      continue;
    }
    rxBuf[rxLen++] = b;
    uint8_t declaredLen = rxBuf[1];
    uint8_t totalExpected = declaredLen + 2;
    if (rxLen >= totalExpected) {
      uint8_t crc = crsfCrc8(&rxBuf[2], declaredLen - 1);
      uint8_t recvCrc = rxBuf[totalExpected - 1];
      Serial.println("RX: " + hexDump(rxBuf, totalExpected));
      if (crc == recvCrc) handleFrame(rxBuf, totalExpected);
      else screenLog("CRC fail, resync");
      rxLen = 0;
    }
    if (rxLen >= CRSF_MAX_FRAME) rxLen = 0;
  }
}

// ---------------- Setup / loop ----------------
void setup() {
  Serial.begin(115200);
  delay(200);

  SPI.begin(TFT_SCLK_PIN, -1, TFT_MOSI_PIN, TFT_CS_PIN);
  tft.init(135, 240);           
  tft.setRotation(1);           
  pinMode(TFT_BL_PIN, OUTPUT);
  analogWrite(TFT_BL_PIN, 255);   
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextColor(ST77XX_GREEN, ST77XX_BLACK);
  tft.setTextSize(1);

  screenLog("radio_esp32 v0.2 boot");
  seedTestData();

  CrsfSerial.begin(CRSF_BAUD, SERIAL_8N1, CRSF_RX_PIN, CRSF_TX_PIN, true);
  screenLog("CRSF UART up @400k");
}

void loop() {
  pollCrsfRx();
}