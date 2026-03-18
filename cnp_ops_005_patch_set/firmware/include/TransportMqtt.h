#pragma once
#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <functional>

class TransportMqtt {
 public:
  using MessageCallback = std::function<void(char*, uint8_t*, unsigned int)>;

  TransportMqtt(Client& netClient);
  void configure(const String& host, uint16_t port, const String& user, const String& password, const String& clientId);
  void setCallback(MessageCallback cb);
  bool connect();
  bool connected() const;
  bool publish(const String& topic, const String& payload, bool retained = false);
  bool subscribe(const String& topic);
  void loop();
  String lastError() const { return lastError_; }

 private:
  PubSubClient mqtt_;
  String host_;
  uint16_t port_ = 1883;
  String user_;
  String password_;
  String clientId_;
  String lastError_;
};
