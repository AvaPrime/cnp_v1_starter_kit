#pragma once
#include <Arduino.h>

struct RuntimeConfig {
  String wifiSsid;
  String wifiPassword;
  String mqttHost;
  uint16_t mqttPort = 1883;
  String mqttUser;
  String mqttPassword;
  String otaUrl;
  String nodeName;
  String nodeType = "sensor";
  String hardwareModel = "esp32-c3-supermini";
  uint32_t heartbeatIntervalSec = 60;
  uint32_t telemetryIntervalSec = 60;
  uint32_t offlineAfterSec = 180;
  bool reportRssi = true;
  bool supportsOta = true;
};

class ConfigManager {
 public:
  bool begin();
  RuntimeConfig& config() { return cfg_; }
  bool save();
 private:
  RuntimeConfig cfg_;
};
