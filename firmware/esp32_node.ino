/*
 * Gage Monitoring Node — ESP32 (Wokwi / breadboard)
 * DHT22 + soil (pot) + LDR -> OLED, LED, buzzer, and POST to the Gage backend.
 * Libraries: "DHT sensor library" (Adafruit), "Adafruit SSD1306", "Adafruit GFX".
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <Wire.h>
#include <Adafruit_SSD1306.h>

// ---- configuration ----
const char* WIFI_SSID = "Hide yo wifi";   // real board: your SSID
const char* WIFI_PASS = "Zaid@017";              // real board: your password
const char* BACKEND   = "http://192.168.1.100:8000";
const char* NODE_KEY  = "demo-node-key-123";
const char* FIRMWARE  = "1.1.0";

// ---- pins ----
#define DHT_PIN     4     // DHT22 DATA
#define DHT_TYPE    DHT22
#define SOIL_PIN    34    // potentiometer SIG (input-only ADC1)
#define LIGHT_PIN   35    // LDR module AO    (input-only ADC1)
#define LED_PIN     2     // -> 220R -> LED anode, cathode -> GND
#define BUZZER_PIN  15    // buzzer +, other leg -> GND
#define SDA_PIN     21    // OLED SDA
#define SCL_PIN     22    // OLED SCL

// Calibration — every probe differs, measure yours once.
const int SOIL_DRY   = 3200;  // ADC in dry air -> 0 %   (pot demo: 4095)
const int SOIL_WET   = 1300;  // ADC in water   -> 100 % (pot demo: 0)
const int LIGHT_DARK = 3000;  // ADC in darkness -> 0 %
const int LIGHT_SUN  = 400;   // ADC in bright light -> 100 %

// Alert thresholds (mirror backend/config.py)
const float SOIL_MIN = 20.0, TEMP_MAX = 40.0, HUM_MAX = 90.0;

const unsigned long SENSOR_INTERVAL_MS    = 30000;
const unsigned long HEARTBEAT_INTERVAL_MS = 60000;
const unsigned long WIFI_TIMEOUT_MS       = 15000;

DHT dht(DHT_PIN, DHT_TYPE);
Adafruit_SSD1306 display(128, 64, &Wire, -1);
unsigned long lastSensor = 0, lastHeartbeat = 0, lastBlink = 0;
bool alert = false;

float pct(int raw, int lo, int hi) {          // lo -> 0 %, hi -> 100 %
  return constrain(100.0f * (lo - raw) / (float)(lo - hi), 0.0f, 100.0f);
}

void showStatus(const String& l1, const String& l2, const String& l3 = "") {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);  display.println("Gage Node");
  display.setCursor(0, 20); display.println(l1);
  display.setCursor(0, 34); display.println(l2);
  display.setCursor(0, 48); display.println(l3);
  display.display();
}

void beep(int ms) { tone(BUZZER_PIN, 2000, ms); }   // works for passive piezo

int postJson(const char* path, const String& body) {
  if (WiFi.status() != WL_CONNECTED) return -1;
  HTTPClient http;
  http.begin(String(BACKEND) + path);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Node-Key", NODE_KEY);
  int code = http.POST(body);
  http.end();
  return code;
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  dht.begin();
  Wire.begin(SDA_PIN, SCL_PIN);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) Serial.println("no OLED at 0x3C");
  showStatus("Connecting WiFi", WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < WIFI_TIMEOUT_MS) {
    delay(250);
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
  }
  digitalWrite(LED_PIN, WiFi.status() == WL_CONNECTED);
  showStatus(WiFi.status() == WL_CONNECTED ? "WiFi connected" : "Offline mode",
             WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "sensors only");
  beep(80);
}

void loop() {
  unsigned long now = millis();

  if (now - lastSensor >= SENSOR_INTERVAL_MS || lastSensor == 0) {
    lastSensor = now;
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    float soil  = pct(analogRead(SOIL_PIN),  SOIL_DRY,   SOIL_WET);
    float light = pct(analogRead(LIGHT_PIN), LIGHT_DARK, LIGHT_SUN);

    if (isnan(t) || isnan(h)) {
      showStatus("DHT read error", "check pin " + String(DHT_PIN));
      alert = true;
    } else {
      alert = soil < SOIL_MIN || t > TEMP_MAX || h > HUM_MAX;
      String body = "{\"temperature\":" + String(t, 1) +
                    ",\"humidity\":" + String(h, 1) +
                    ",\"soil_moisture\":" + String(soil, 1) +
                    ",\"battery\":100}";
      int code = postJson("/node/sensors", body);
      showStatus("T:" + String(t, 1) + "C  H:" + String(h, 0) + "%",
                 "Soil:" + String(soil, 0) + "%  Lux:" + String(light, 0) + "%",
                 code == 200 ? "sent" : (code < 0 ? "offline" : "http " + String(code)));
      if (alert || code > 0 && code != 200) beep(150);
      if (light < 15) Serial.println("too dark for a useful camera shot");
    }
  }

  if (now - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeat = now;
    postJson("/node/heartbeat",
             "{\"source\":\"esp32\",\"battery\":100,\"wifi_strength\":" +
             String(WiFi.RSSI()) + ",\"firmware_version\":\"" + FIRMWARE + "\"}");
    if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
  }

  // LED: steady = healthy, blinking = alert
  if (alert && now - lastBlink >= 400) {
    lastBlink = now;
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
  } else if (!alert) {
    digitalWrite(LED_PIN, HIGH);
  }
}