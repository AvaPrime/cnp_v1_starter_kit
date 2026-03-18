#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include "BaseModule.h"
#include "ConfigManager.h"
#include "IdentityManager.h"
#include "EventQueue.h"
#include "Types.h"

class Protocol {
 public:
  Protocol(RuntimeConfig& cfg, const NodeIdentity& id, BaseModule& module, EventQueue& queue);
  String buildHello();
  String buildHeartbeat(uint32_t seq, int wifiRssi, size_t queueDepth, uint32_t freeHeap);
  String buildStateUpdate();
  String buildEvent(const String& eventType, const String& category, const String& priority, const JsonObjectConst& body, bool requiresAck);
  String buildError(Severity severity, const String& domain, const String& code, const String& message, const JsonObjectConst& diagnostics);
  Result parseCommand(const String& json, String& commandId, String& commandType, DynamicJsonDocument& arguments, bool& dryRun);

  static String nextMessageId();
  static String nowUtc();

 private:
  RuntimeConfig& cfg_;
  const NodeIdentity& id_;
  BaseModule& module_;
  EventQueue& queue_;
  void fillEnvelope(JsonDocument& doc, const char* type);
};
