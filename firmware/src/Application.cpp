#include "Application.h"
#include "../config/default_config.h"

Application::Application(BaseModule& module)
  : module_(module), mqtt_(wifiClient_), queue_(DEFAULT_EVENT_QUEUE_SIZE) {}

bool Application::begin() {
  Serial.begin(115200);
  delay(500);

  if (!configManager_.begin()) return false;
  if (!identityManager_.begin(configManager_.config().nodeName)) return false;
  if (!module_.begin()) return false;

  protocol_ = new Protocol(configManager_.config(), identityManager_.get(), module_, queue_);
  mqtt_.configure(
    configManager_.config().mqttHost,
    configManager_.config().mqttPort,
    configManager_.config().mqttUser,
    configManager_.config().mqttPassword,
    identityManager_.get().nodeId
  );
  mqtt_.setCallback([this](char* topic, uint8_t* payload, unsigned int len) { this->onMqttMessage(topic, payload, len); });

  cmdInTopic_ = String("cnp/v1/nodes/") + identityManager_.get().nodeId + "/cmd/in";
  configTopic_ = String("cnp/v1/nodes/") + identityManager_.get().nodeId + "/config";

  return connectWifi() && connectMqtt();
}

bool Application::connectWifi() {
  auto& cfg = configManager_.config();
  WiFi.mode(WIFI_STA);
  WiFi.begin(cfg.wifiSsid.c_str(), cfg.wifiPassword.c_str());
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < DEFAULT_WIFI_CONNECT_TIMEOUT_MS) {
    delay(250);
  }
  return WiFi.status() == WL_CONNECTED;
}

bool Application::connectMqtt() {
  if (!mqtt_.connect()) return false;
  mqtt_.subscribe(cmdInTopic_);
  mqtt_.subscribe(configTopic_);
  publishHello();
  publishHeartbeat();
  return true;
}

void Application::publishHello() {
  char topic[96];
  snprintf(topic, sizeof(topic), TOPIC_HELLO_FMT, identityManager_.get().nodeId.c_str());
  mqtt_.publish(topic, protocol_->buildHello(), false);
}

void Application::publishHeartbeat() {
  char topic[96];
  snprintf(topic, sizeof(topic), TOPIC_HEARTBEAT_FMT, identityManager_.get().nodeId.c_str());
  mqtt_.publish(topic, protocol_->buildHeartbeat(++heartbeatSeq_, WiFi.RSSI(), queue_.size(), ESP.getFreeHeap()), false);
  lastHeartbeatMs_ = millis();
}

void Application::publishStateUpdate() {
  char topic[96];
  snprintf(topic, sizeof(topic), TOPIC_STATE_FMT, identityManager_.get().nodeId.c_str());
  mqtt_.publish(topic, protocol_->buildStateUpdate(), false);
  lastTelemetryMs_ = millis();
}

void Application::flushQueue() {
  while (queue_.hasPending()) {
    QueuedMessage msg;
    if (!queue_.peek(msg)) return;
    if (!mqtt_.publish(msg.topic, msg.payload, false)) return;
    if (!msg.requiresAck) queue_.pop();
    else return; // wait for ack before sending next confirmed message
  }
}

void Application::onMqttMessage(char* topic, uint8_t* payload, unsigned int len) {
  String body;
  for (unsigned int i = 0; i < len; ++i) body += (char)payload[i];

  String t(topic);
  if (t.endsWith("/cmd/in")) {
    String cmdId, cmdType;
    DynamicJsonDocument args(512);
    bool dryRun = false;
    auto parsed = protocol_->parseCommand(body, cmdId, cmdType, args, dryRun);

    DynamicJsonDocument resultDoc(768);
    resultDoc["protocol_version"] = "CNPv1";
    resultDoc["message_type"] = "command_result";
    resultDoc["message_id"] = Protocol::nextMessageId();
    resultDoc["node_id"] = identityManager_.get().nodeId;
    resultDoc["ts_utc"] = Protocol::nowUtc();
    resultDoc["qos"] = 1;
    JsonObject rp = resultDoc["payload"].to<JsonObject>();
    rp["command_id"] = cmdId;
    rp["duration_ms"] = 0;

    if (!parsed.ok) {
      rp["status"] = "rejected";
      rp["code"] = parsed.code;
      rp["details"]["message"] = parsed.message;
    } else if (dryRun) {
      rp["status"] = "dry_run";
      rp["code"] = "CMD_DRY_RUN";
    } else {
      DynamicJsonDocument moduleResponse(512);
      bool ok = module_.handleCommand(cmdType, args.as<JsonObject>(), moduleResponse.to<JsonObject>());
      rp["status"] = ok ? "executed" : "error";
      rp["code"] = ok ? "CMD_OK" : "CMD_FAILED";
      rp["details"].set(moduleResponse);
    }

    char outTopic[96];
    snprintf(outTopic, sizeof(outTopic), TOPIC_CMD_OUT_FMT, identityManager_.get().nodeId.c_str());
    String output;
    serializeJson(resultDoc, output);
    mqtt_.publish(outTopic, output, false);
  }
}

void Application::loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt_.connected()) connectMqtt();

  mqtt_.loop();
  module_.loop();
  flushQueue();

  auto& cfg = configManager_.config();
  if (millis() - lastHeartbeatMs_ >= cfg.heartbeatIntervalSec * 1000UL) publishHeartbeat();
  if (millis() - lastTelemetryMs_ >= cfg.telemetryIntervalSec * 1000UL) publishStateUpdate();
}
