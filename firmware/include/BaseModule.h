#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

class BaseModule {
 public:
  virtual ~BaseModule() = default;
  virtual const char* name() const = 0;
  virtual bool begin() = 0;
  virtual void loop() = 0;
  virtual bool appendTelemetry(JsonObject obj) = 0;
  virtual bool handleCommand(const String& commandType, JsonObject arguments, JsonObject response) = 0;
};
