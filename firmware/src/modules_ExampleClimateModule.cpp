#include "BaseModule.h"

class ExampleClimateModule : public BaseModule {
 public:
  const char* name() const override { return "example_climate"; }

  bool begin() override {
    pinMode(8, OUTPUT);
    return true;
  }

  void loop() override {
    // Replace with actual sensor reads.
  }

  bool appendTelemetry(JsonObject obj) override {
    obj["temperature_c"] = 24.6;
    obj["humidity_pct"] = 52.0;
    obj["relay_state"] = relayState_;
    return true;
  }

  bool handleCommand(const String& commandType, JsonObject arguments, JsonObject response) override {
    if (commandType == "set_relay") {
      relayState_ = arguments["state"] == "on";
      digitalWrite(8, relayState_ ? HIGH : LOW);
      response["relay_state"] = relayState_ ? "on" : "off";
      return true;
    }
    response["error"] = "Unsupported command";
    return false;
  }

 private:
  bool relayState_ = false;
};

ExampleClimateModule g_module;


BaseModule& getModule() {
  return g_module;
}
