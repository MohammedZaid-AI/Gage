/*
 * Gage Monitoring Node — ESP32 firmware (reference)
 * -------------------------------------------------
 * Reads DHT22 + soil moisture, shows status on an OLED, blinks a status LED,
 * beeps a buzzer on alerts, and pushes to the Gage backend over Wi-Fi.
 *
 * The ESP32 handles SENSORS ONLY. The Android phone handles the camera + GPS
 * and posts images separately to POST /node/image. The backend merges the two.
 *
 * Endpoints (authenticate with the node's API key via the X-Node-Key header):
 *   POST /node/sensors    { temperature, humidity, soil_moisture, battery }
 *   POST /node/heartbeat  { source:"esp32", battery, wifi_strength, firmware_version }
 *
 * Libraries: WiFi.h, HTTPClient.h, DHT sensor library, Adafruit_SSD1306.
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <Wire.h>
#include <Adafruit_SSD1306.h>

// ---- configuration ----
const char* WIFI_SSID = "your-wifi";
const char* WIFI_PASS = "your-pass";
const char* BACKEND   = "http://192.168.1.100:8000";   // Gage backend base URL
const char* NODE_KEY  = "demo-node-key-123";            // this node's API key
const char* FIRMWARE  = "1.0.0";

// ---- pins ----
#define DHT_PIN     4
#define DHT_TYPE    DHT22
#define SOIL_PIN    34   // analog
#define LED_PIN     2
#define BUZZER_PIN  15

// Soil-moisture calibration. ADC reads HIGH in dry air, LOW in water — measure
// YOUR probe once and set these two constants; every probe differs.
// ponytail: linear map is enough; swap for a per-probe lookup only if it drifts.
const int SOIL_DRY = 3200;   // ADC value in dry air  -> 0 %
const int SOIL_WET = 1300;   // ADC value in water     -> 100 %

const unsigned long SENSOR_INTERVAL_MS    = 30000;  // push sensors every 30 s
const unsigned long HEARTBEAT_INTERVAL_MS = 60000;  // heartbeat every 60 s

DHT dht(DHT_PIN, DHT_TYPE);
Adafruit_SSD1306 display(128, 64, &Wire, -1);
unsigned long lastSensor = 0, lastHeartbeat = 0;

float readSoilPercent() {
  int raw = analogRead(SOIL_PIN);
  float pct = 100.0f * (SOIL_DRY - raw) / (float)(SOIL_DRY - SOIL_WET);
  return constrain(pct, 0.0f, 100.0f);
}

int postJson(const char* path, const String& body) {
  HTTPClient http;
  http.begin(String(BACKEND) + path);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Node-Key", NODE_KEY);
  int code = http.POST(body);
  http.end();
  return code;
}

void showStatus(const String& line1, const String& line2) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("Gage Node");
  display.setCursor(0, 24);
  display.println(line1);
  display.setCursor(0, 40);
  display.println(line2);
  display.display();
}

void beep(int ms) {
  digitalWrite(BUZZER_PIN, HIGH);
  delay(ms);
  digitalWrite(BUZZER_PIN, LOW);
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  dht.begin();
  Wire.begin();
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  showStatus("Connecting WiFi", WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
  }
  digitalWrite(LED_PIN, HIGH);
  showStatus("WiFi connected", WiFi.localIP().toString());
}

void loop() {
  unsigned long now = millis();

  if (now - lastSensor >= SENSOR_INTERVAL_MS) {
    lastSensor = now;
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    float soil = readSoilPercent();
    if (isnan(t) || isnan(h)) {
      showStatus("DHT read error", "retrying...");
    } else {
      String body = "{\"temperature\":" + String(t, 1) +
                    ",\"humidity\":" + String(h, 1) +
                    ",\"soil_moisture\":" + String(soil, 1) +
                    ",\"battery\":100}";
      int code = postJson("/node/sensors", body);
      showStatus("T:" + String(t, 1) + " H:" + String(h, 0),
                 "Soil:" + String(soil, 0) + "% (" + String(code) + ")");
      if (code != 200) beep(120);  // audible failure
    }
  }

  if (now - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeat = now;
    String body = "{\"source\":\"esp32\",\"battery\":100,\"wifi_strength\":" +
                  String(WiFi.RSSI()) + ",\"firmware_version\":\"" + FIRMWARE + "\"}";
    postJson("/node/heartbeat", body);
  }
}
