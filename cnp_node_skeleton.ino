// ============================================================
//  Codessa Node Protocol v1 — ESP32-C3 Firmware Skeleton
//  File: cnp_node_skeleton.ino
//
//  This is the BASE firmware all CNP nodes inherit from.
//  To build a specific node:
//    1. Fill in NODE_* constants below
//    2. Implement readSensors() with your sensor logic
//    3. Implement handleActuator() with your actuator logic
//    4. Add any custom setup in nodeSetup()
//
//  Requires:
//    - ArduinoJson  (6.x)   — Library Manager
//    - HTTPClient   (built-in with ESP32 core)
// ============================================================

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ============================================================
//  NODE IDENTITY — EDIT THESE FOR EACH NODE
// ============================================================
#define NODE_ID           "cnp-office-temp-01"
#define NODE_NAME         "Office Climate Node"
#define NODE_TYPE         "sensor"   // sensor | actuator | hybrid | gateway
#define NODE_ZONE         "office"
#define FIRMWARE_VERSION  "1.0.0"
#define PROTOCOL_VERSION  "CNPv1"

// ============================================================
//  NETWORK CONFIG
// ============================================================
#define WIFI_SSID     "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define GATEWAY_URL   "http://192.168.1.100:5000"  // Your local gateway IP
#define NODE_TOKEN    "YOUR_NODE_TOKEN"             // Simple auth token

// ============================================================
//  TIMING (seconds)
// ============================================================
#define HEARTBEAT_INTERVAL_SEC  30
#define REPORT_INTERVAL_SEC     60
#define WIFI_RETRY_DELAY_MS     500
#define WIFI_TIMEOUT_MS         15000
#define HTTP_TIMEOUT_MS         5000

// ============================================================
//  HARDWARE — adjust for your board variant
// ============================================================
#define LED_PIN  8   // Onboard LED (try 7 if this doesn't work)

// ============================================================
//  INTERNAL STATE — do not edit
// ============================================================
static bool      registered       = false;
static uint32_t  lastHeartbeatMs  = 0;
static uint32_t  lastReportMs     = 0;
static uint32_t  heartbeatIntervalMs = HEARTBEAT_INTERVAL_SEC * 1000UL;
static uint32_t  reportIntervalMs   = REPORT_INTERVAL_SEC * 1000UL;
static uint32_t  eventCounter     = 0;
static char      commandBuffer[512];
static bool      pendingCommand   = false;

// ============================================================
//  ██████╗ SENSOR DATA STRUCT — add your fields here
// ============================================================
struct SensorData {
  float    temperature_c = 0.0;
  float    humidity_pct  = 0.0;
  bool     motion        = false;
  bool     valid         = false;
  // Add more sensor fields as needed
};

// ============================================================
//  FORWARD DECLARATIONS
// ============================================================
bool connectWiFi();
bool sendMessage(const char* path, JsonDocument& doc);
bool sendHello();
bool sendHeartbeat();
bool sendEvent(const char* eventType, const char* category,
               const char* priority, JsonObject& data);
bool sendStateUpdate();
bool sendError(const char* errorCode, const char* errorMsg, bool recoverable);
void pollCommands();
void handleCommand(JsonDocument& cmd);
void blinkLED(int times, int ms);
String generateEventId();
String getTimestamp();
int   getBattery();
int   getRSSI();

// ============================================================
//  USER-IMPLEMENTED: FILL THESE IN FOR YOUR SPECIFIC NODE
// ============================================================

/**
 * Called once after WiFi and registration are ready.
 * Add your sensor/actuator initialization here.
 */
void nodeSetup() {
  // Example: pinMode(SENSOR_PIN, INPUT);
  // Example: dht.begin();
  // Example: Wire.begin(SDA_PIN, SCL_PIN);
}

/**
 * Read all sensors and populate the SensorData struct.
 * Return false if the reading failed.
 */
bool readSensors(SensorData& data) {
  // REPLACE WITH REAL SENSOR CODE
  // Example using DHT22:
  //   data.temperature_c = dht.readTemperature();
  //   data.humidity_pct  = dht.readHumidity();
  //   data.valid = !isnan(data.temperature_c);

  // Stub: fake data so skeleton compiles and runs
  data.temperature_c = 22.5 + (random(-20, 20) / 10.0);
  data.humidity_pct  = 55.0 + (random(-50, 50) / 10.0);
  data.valid = true;
  return true;
}

/**
 * Called when a control command arrives.
 * Implement your actuator logic here.
 */
void handleActuator(const char* commandType, JsonObject& params) {
  // Example:
  //   if (strcmp(commandType, "set_relay") == 0) {
  //     bool state = params["state"] == "on";
  //     digitalWrite(RELAY_PIN, state ? HIGH : LOW);
  //   }

  Serial.printf("[ACTUATOR] Command: %s\n", commandType);
  // Add your implementation
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.println("\n========================================");
  Serial.printf("  %s  |  %s\n", NODE_ID, FIRMWARE_VERSION);
  Serial.println("  Codessa Node Protocol v1 booting...");
  Serial.println("========================================\n");

  if (!connectWiFi()) {
    Serial.println("[FATAL] WiFi failed. Rebooting in 10s...");
    delay(10000);
    ESP.restart();
  }

  // Announce ourselves to the gateway
  if (!sendHello()) {
    Serial.println("[WARN] Registration failed. Will retry on next hello.");
    blinkLED(5, 200);
  } else {
    blinkLED(3, 100);
  }

  // User node setup
  nodeSetup();

  Serial.println("[CNP] Node ready.\n");
}

// ============================================================
//  MAIN LOOP
// ============================================================
void loop() {
  uint32_t now = millis();

  // --- Heartbeat ---
  if (now - lastHeartbeatMs >= heartbeatIntervalMs) {
    lastHeartbeatMs = now;
    sendHeartbeat();
  }

  // --- Sensor report ---
  if (now - lastReportMs >= reportIntervalMs) {
    lastReportMs = now;

    SensorData data;
    if (readSensors(data) && data.valid) {
      // Build event data from sensor reading
      StaticJsonDocument<256> dataDoc;
      JsonObject dataObj = dataDoc.to<JsonObject>();
      dataObj["temperature_c"] = data.temperature_c;
      dataObj["humidity_pct"]  = data.humidity_pct;
      // Add more fields as needed

      sendEvent("temperature_reading", "telemetry", "normal", dataObj);
    } else {
      sendError("SENSOR_READ_FAIL", "Failed to read sensor data", true);
    }
  }

  // --- Poll for commands ---
  pollCommands();

  // --- Reconnect if WiFi dropped ---
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WIFI] Connection lost. Reconnecting...");
    connectWiFi();
  }

  delay(100);
}

// ============================================================
//  WIFI
// ============================================================
bool connectWiFi() {
  Serial.printf("[WIFI] Connecting to %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > WIFI_TIMEOUT_MS) {
      Serial.println(" TIMEOUT");
      return false;
    }
    delay(WIFI_RETRY_DELAY_MS);
    Serial.print(".");
  }

  Serial.printf("\n[WIFI] Connected: %s\n", WiFi.localIP().toString().c_str());
  return true;
}

// ============================================================
//  HTTP SEND
// ============================================================
bool sendMessage(const char* path, JsonDocument& doc) {
  if (WiFi.status() != WL_CONNECTED) return false;

  char url[128];
  snprintf(url, sizeof(url), "%s%s", GATEWAY_URL, path);

  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-CNP-Token", NODE_TOKEN);
  http.setTimeout(HTTP_TIMEOUT_MS);

  String body;
  serializeJson(doc, body);

  int code = http.POST(body);
  bool ok  = (code == 200 || code == 201);

  if (ok) {
    String resp = http.getString();
    // Parse gateway response (config updates, ack, etc.)
    StaticJsonDocument<512> respDoc;
    if (deserializeJson(respDoc, resp) == DeserializationError::Ok) {
      if (respDoc.containsKey("config")) {
        JsonObject cfg = respDoc["config"];
        if (cfg.containsKey("heartbeat_interval_sec"))
          heartbeatIntervalMs = (uint32_t)cfg["heartbeat_interval_sec"] * 1000UL;
        if (cfg.containsKey("report_interval_sec"))
          reportIntervalMs = (uint32_t)cfg["report_interval_sec"] * 1000UL;
        Serial.println("[CNP] Config updated from gateway.");
      }
    }
  } else {
    Serial.printf("[HTTP] POST %s → %d\n", path, code);
  }

  http.end();
  return ok;
}

// ============================================================
//  HELLO (registration)
// ============================================================
bool sendHello() {
  StaticJsonDocument<512> doc;
  doc["protocol"]     = PROTOCOL_VERSION;
  doc["message_type"] = "hello";
  doc["node_id"]      = NODE_ID;
  doc["timestamp"]    = getTimestamp();

  JsonObject payload = doc.createNestedObject("payload");
  payload["node_name"]        = NODE_NAME;
  payload["node_type"]        = NODE_TYPE;
  payload["zone"]             = NODE_ZONE;
  payload["firmware_version"] = FIRMWARE_VERSION;

  JsonObject caps = payload.createNestedObject("capabilities");
  // EDIT: declare your actual capabilities
  JsonArray sensors   = caps.createNestedArray("sensors");
  sensors.add("temperature");
  sensors.add("humidity");
  JsonArray actuators = caps.createNestedArray("actuators");
  // actuators.add("relay");
  JsonArray conn      = caps.createNestedArray("connectivity");
  conn.add("wifi");
  caps["power_mode"] = "usb";

  Serial.println("[CNP] Sending hello...");
  bool ok = sendMessage("/api/node/hello", doc);
  if (ok) {
    registered = true;
    Serial.println("[CNP] Registered successfully.");
  }
  return ok;
}

// ============================================================
//  HEARTBEAT
// ============================================================
bool sendHeartbeat() {
  StaticJsonDocument<256> doc;
  doc["protocol"]     = PROTOCOL_VERSION;
  doc["message_type"] = "heartbeat";
  doc["node_id"]      = NODE_ID;
  doc["timestamp"]    = getTimestamp();

  JsonObject payload = doc.createNestedObject("payload");
  payload["status"]     = "online";
  payload["uptime_sec"] = (int)(millis() / 1000);
  payload["battery"]    = getBattery();
  payload["wifi_rssi"]  = getRSSI();

  Serial.println("[CNP] Heartbeat sent.");
  return sendMessage("/api/node/heartbeat", doc);
}

// ============================================================
//  EVENT
// ============================================================
bool sendEvent(const char* eventType, const char* category,
               const char* priority, JsonObject& data) {
  eventCounter++;
  char eventId[32];
  snprintf(eventId, sizeof(eventId), "evt-%06lu", eventCounter);

  StaticJsonDocument<512> doc;
  doc["protocol"]     = PROTOCOL_VERSION;
  doc["message_type"] = "event";
  doc["node_id"]      = NODE_ID;
  doc["timestamp"]    = getTimestamp();

  JsonObject payload = doc.createNestedObject("payload");
  payload["event_id"]   = eventId;
  payload["event_type"] = eventType;
  payload["category"]   = category;
  payload["priority"]   = priority;
  payload["data"]       = data;

  Serial.printf("[CNP] Event: %s [%s]\n", eventType, priority);
  return sendMessage("/api/node/event", doc);
}

// ============================================================
//  STATE UPDATE
// ============================================================
bool sendStateUpdate() {
  StaticJsonDocument<256> doc;
  doc["protocol"]     = PROTOCOL_VERSION;
  doc["message_type"] = "state_update";
  doc["node_id"]      = NODE_ID;
  doc["timestamp"]    = getTimestamp();

  JsonObject payload = doc.createNestedObject("payload");
  payload["status"]     = "online";
  payload["battery"]    = getBattery();
  payload["wifi_rssi"]  = getRSSI();
  payload["uptime_sec"] = (int)(millis() / 1000);

  return sendMessage("/api/node/state", doc);
}

// ============================================================
//  ERROR REPORT
// ============================================================
bool sendError(const char* errorCode, const char* errorMsg, bool recoverable) {
  StaticJsonDocument<256> doc;
  doc["protocol"]     = PROTOCOL_VERSION;
  doc["message_type"] = "error";
  doc["node_id"]      = NODE_ID;
  doc["timestamp"]    = getTimestamp();

  JsonObject payload = doc.createNestedObject("payload");
  payload["error_code"]  = errorCode;
  payload["error_msg"]   = errorMsg;
  payload["recoverable"] = recoverable;

  Serial.printf("[CNP] Error: %s — %s\n", errorCode, errorMsg);
  return sendMessage("/api/node/error", doc);
}

// ============================================================
//  POLL COMMANDS
// ============================================================
void pollCommands() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (millis() % 5000 > 100) return;  // Poll every ~5s

  char url[128];
  snprintf(url, sizeof(url), "%s/api/node/commands/%s", GATEWAY_URL, NODE_ID);

  HTTPClient http;
  http.begin(url);
  http.addHeader("X-CNP-Token", NODE_TOKEN);
  http.setTimeout(HTTP_TIMEOUT_MS);

  int code = http.GET();
  if (code == 200) {
    String resp = http.getString();
    StaticJsonDocument<512> doc;
    if (deserializeJson(doc, resp) == DeserializationError::Ok) {
      if (doc.containsKey("command")) {
        handleCommand(doc);
      }
    }
  }
  http.end();
}

// ============================================================
//  COMMAND HANDLER
// ============================================================
void handleCommand(JsonDocument& doc) {
  JsonObject payload   = doc["payload"];
  const char* cmdId    = payload["command_id"];
  const char* cmdType  = payload["command_type"];
  const char* category = payload["category"];

  Serial.printf("[CMD] Received: %s (type=%s)\n", cmdId, cmdType);

  // Built-in commands
  if (strcmp(cmdType, "ping") == 0) {
    // Just ack
  } else if (strcmp(cmdType, "reboot") == 0) {
    Serial.println("[CMD] Rebooting...");
    delay(500);
    ESP.restart();
    return;
  } else if (strcmp(cmdType, "sleep") == 0) {
    int secs = payload["params"]["duration_sec"] | 60;
    Serial.printf("[CMD] Deep sleep for %d seconds\n", secs);
    esp_deep_sleep(secs * 1000000ULL);
    return;
  } else if (strcmp(category, "control") == 0) {
    JsonObject params = payload["params"];
    handleActuator(cmdType, params);
  }

  // Send acknowledgment
  StaticJsonDocument<256> ack;
  ack["protocol"]     = PROTOCOL_VERSION;
  ack["message_type"] = "command_result";
  ack["node_id"]      = NODE_ID;
  ack["timestamp"]    = getTimestamp();

  JsonObject ackPayload = ack.createNestedObject("payload");
  ackPayload["command_id"] = cmdId;
  ackPayload["status"]     = "executed";

  sendMessage("/api/node/command_result", ack);
}

// ============================================================
//  UTILITIES
// ============================================================
void blinkLED(int times, int ms) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(ms);
    digitalWrite(LED_PIN, LOW);
    delay(ms);
  }
}

String getTimestamp() {
  // Returns uptime as ISO-ish string when no NTP is configured
  // For production: use NTPClient library for real UTC timestamps
  unsigned long s = millis() / 1000;
  char buf[32];
  snprintf(buf, sizeof(buf), "2026-01-01T00:%02lu:%02luZ", (s / 60) % 60, s % 60);
  return String(buf);
  // Production replacement:
  // return timeClient.getFormattedTime();  // with NTPClient
}

String generateEventId() {
  char buf[16];
  snprintf(buf, sizeof(buf), "evt-%06lu", ++eventCounter);
  return String(buf);
}

int getBattery() {
  // If USB powered, return -1 (not applicable)
  // For battery nodes: read ADC and convert to percentage
  // Example: return map(analogRead(BATT_PIN), 2800, 4200, 0, 100);
  return -1;
}

int getRSSI() {
  return WiFi.RSSI();
}
