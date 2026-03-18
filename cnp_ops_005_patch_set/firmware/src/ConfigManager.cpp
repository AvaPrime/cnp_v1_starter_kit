#include "ConfigManager.h"
#include <Preferences.h>
#include "../config/default_config.h"

bool ConfigManager::begin() {
  Preferences p;
  p.begin("cnp", true);
  cfg_.wifiSsid = p.getString("wifi_ssid", "");
  cfg_.wifiPassword = p.getString("wifi_pass", "");
  cfg_.mqttHost = p.getString("mqtt_host", "");
  cfg_.mqttPort = p.getUShort("mqtt_port", DEFAULT_MQTT_PORT);
  cfg_.mqttUser = p.getString("mqtt_user", "");
  cfg_.mqttPassword = p.getString("mqtt_pass", "");
  cfg_.otaUrl = p.getString("ota_url", "");
  cfg_.nodeName = p.getString("node_name", "node");
  cfg_.nodeType = p.getString("node_type", "sensor");
  cfg_.hardwareModel = p.getString("hw_model", "esp32-c3-supermini");
  cfg_.heartbeatIntervalSec = p.getUInt("hb_int", DEFAULT_HEARTBEAT_INTERVAL_SEC);
  cfg_.telemetryIntervalSec = p.getUInt("tm_int", DEFAULT_TELEMETRY_INTERVAL_SEC);
  cfg_.offlineAfterSec = p.getUInt("off_int", DEFAULT_OFFLINE_AFTER_SEC);
  cfg_.reportRssi = p.getBool("rssi", true);
  cfg_.supportsOta = p.getBool("ota", DEFAULT_OTA_ENABLED);
  p.end();
  return true;
}

bool ConfigManager::save() {
  Preferences p;
  p.begin("cnp", false);
  p.putString("wifi_ssid", cfg_.wifiSsid);
  p.putString("wifi_pass", cfg_.wifiPassword);
  p.putString("mqtt_host", cfg_.mqttHost);
  p.putUShort("mqtt_port", cfg_.mqttPort);
  p.putString("mqtt_user", cfg_.mqttUser);
  p.putString("mqtt_pass", cfg_.mqttPassword);
  p.putString("ota_url", cfg_.otaUrl);
  p.putString("node_name", cfg_.nodeName);
  p.putString("node_type", cfg_.nodeType);
  p.putString("hw_model", cfg_.hardwareModel);
  p.putUInt("hb_int", cfg_.heartbeatIntervalSec);
  p.putUInt("tm_int", cfg_.telemetryIntervalSec);
  p.putUInt("off_int", cfg_.offlineAfterSec);
  p.putBool("rssi", cfg_.reportRssi);
  p.putBool("ota", cfg_.supportsOta);
  p.end();
  return true;
}
