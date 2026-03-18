#pragma once
#include <Arduino.h>
#include <WiFi.h>
#include "BaseModule.h"
#include "ConfigManager.h"
#include "IdentityManager.h"
#include "EventQueue.h"
#include "TransportMqtt.h"
#include "Protocol.h"
#include "OtaManager.h"

class Application {
 public:
  explicit Application(BaseModule& module);
  bool begin();
  void loop();

 private:
  BaseModule& module_;
  ConfigManager configManager_;
  IdentityManager identityManager_;
  WiFiClient wifiClient_;
  TransportMqtt mqtt_;
  EventQueue queue_;
  OtaManager ota_;
  Protocol* protocol_ = nullptr;
  uint32_t lastHeartbeatMs_ = 0;
  uint32_t lastTelemetryMs_ = 0;
  uint32_t heartbeatSeq_ = 0;
  String cmdInTopic_;
  String configTopic_;

  bool connectWifi();
  bool connectMqtt();
  void onMqttMessage(char* topic, uint8_t* payload, unsigned int len);
  void publishHello();
  void publishHeartbeat();
  void publishStateUpdate();
  void flushQueue();
};
