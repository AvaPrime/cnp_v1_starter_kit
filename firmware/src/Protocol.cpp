#include "Protocol.h"
#include <ArduinoJson.h>

Protocol::Protocol(RuntimeConfig& cfg, const NodeIdentity& id, BaseModule& module, EventQueue& queue)
  : cfg_(cfg), id_(id), module_(module), queue_(queue) {}

void Protocol::fillEnvelope(JsonDocument& doc, const char* type) {
  doc["protocol_version"] = id_.protocolVersion;
  doc["message_type"] = type;
  doc["message_id"] = nextMessageId();
  doc["node_id"] = id_.nodeId;
  doc["ts_utc"] = nowUtc();
  doc["qos"] = 1;
}

String Protocol::nextMessageId() {
  char buf[25];
  uint32_t t = millis();
  uint32_t r = esp_random();
  snprintf(buf, sizeof(buf), "%08lx%08lx%08lx", (unsigned long)t, (unsigned long)r, (unsigned long)ESP.getFreeHeap());
  return String(buf);
}

String Protocol::nowUtc() {
  // Minimal placeholder until SNTP/time sync is added.
  return "1970-01-01T00:00:00Z";
}

String Protocol::buildHello() {
  DynamicJsonDocument doc(768);
  fillEnvelope(doc, "hello");
  JsonObject p = doc["payload"].to<JsonObject>();
  p["device_uid"] = id_.deviceUid;
  p["node_name"] = cfg_.nodeName;
  p["node_type"] = cfg_.nodeType;
  p["firmware_version"] = id_.firmwareVersion;
  p["hardware_model"] = cfg_.hardwareModel;
  p["supports_ota"] = cfg_.supportsOta;
  p["boot_reason"] = "power_on";
  JsonObject caps = p["capabilities"].to<JsonObject>();
  JsonArray sensors = caps["sensors"].to<JsonArray>();
  JsonArray actuators = caps["actuators"].to<JsonArray>();
  JsonArray connectivity = caps["connectivity"].to<JsonArray>();
  connectivity.add("wifi");
  serializeJson(doc, Serial); Serial.println();
  String out;
  serializeJson(doc, out);
  return out;
}

String Protocol::buildHeartbeat(uint32_t seq, int wifiRssi, size_t queueDepth, uint32_t freeHeap) {
  DynamicJsonDocument doc(512);
  fillEnvelope(doc, "heartbeat");
  JsonObject p = doc["payload"].to<JsonObject>();
  p["seq"] = seq;
  p["uptime_sec"] = millis() / 1000;
  p["free_heap_bytes"] = freeHeap;
  p["wifi_rssi"] = wifiRssi;
  p["queue_depth"] = queueDepth;
  p["status"] = "online";
  String out;
  serializeJson(doc, out);
  return out;
}

String Protocol::buildStateUpdate() {
  DynamicJsonDocument doc(768);
  fillEnvelope(doc, "state_update");
  JsonObject p = doc["payload"].to<JsonObject>();
  p["status"] = "online";
  p["mode"] = "normal";
  JsonObject fields = p["fields"].to<JsonObject>();
  module_.appendTelemetry(fields);
  JsonArray changed = p["changed"].to<JsonArray>();
  changed.add("telemetry");
  String out;
  serializeJson(doc, out);
  return out;
}

String Protocol::buildEvent(const String& eventType, const String& category, const String& priority, const JsonObjectConst& body, bool requiresAck) {
  DynamicJsonDocument doc(768);
  fillEnvelope(doc, "event");
  JsonObject p = doc["payload"].to<JsonObject>();
  p["event_type"] = eventType;
  p["category"] = category;
  p["priority"] = priority;
  p["delivery_mode"] = requiresAck ? "confirm" : "fire_and_forget";
  p["requires_ack"] = requiresAck;
  p["event_seq"] = millis();
  p["body"].set(body);
  String out;
  serializeJson(doc, out);
  return out;
}

String Protocol::buildError(Severity severity, const String& domain, const String& code, const String& message, const JsonObjectConst& diagnostics) {
  DynamicJsonDocument doc(768);
  fillEnvelope(doc, "error");
  JsonObject p = doc["payload"].to<JsonObject>();
  const char* sev = "info";
  switch (severity) {
    case Severity::Debug: sev = "debug"; break;
    case Severity::Info: sev = "info"; break;
    case Severity::Warning: sev = "warning"; break;
    case Severity::Error: sev = "error"; break;
    case Severity::Critical: sev = "critical"; break;
  }
  p["severity"] = sev;
  p["domain"] = domain;
  p["code"] = code;
  p["message"] = message;
  p["recoverable"] = true;
  p["diagnostics"].set(diagnostics);
  String out;
  serializeJson(doc, out);
  return out;
}

Result Protocol::parseCommand(const String& json, String& commandId, String& commandType, DynamicJsonDocument& arguments, bool& dryRun) {
  DynamicJsonDocument doc(1024);
  auto err = deserializeJson(doc, json);
  if (err) return Result::Fail("ERR_JSON_PARSE", err.c_str());

  if (String((const char*)doc["protocol_version"]) != "CNPv1") return Result::Fail("ERR_PROTOCOL", "Unsupported protocol version");
  if (String((const char*)doc["message_type"]) != "command") return Result::Fail("ERR_TYPE", "Not a command packet");

  JsonObject p = doc["payload"];
  commandId = String((const char*)p["command_id"]);
  commandType = String((const char*)p["command_type"]);
  dryRun = p["dry_run"] | false;
  arguments.clear();
  arguments.to<JsonObject>().set(p["arguments"]);
  if (commandId.isEmpty() || commandType.isEmpty()) return Result::Fail("ERR_CMD_INVALID", "Missing command fields");
  return Result::Ok();
}
