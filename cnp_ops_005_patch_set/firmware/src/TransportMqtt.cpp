#include "TransportMqtt.h"

TransportMqtt::TransportMqtt(Client& netClient) : mqtt_(netClient) {}

void TransportMqtt::configure(const String& host, uint16_t port, const String& user, const String& password, const String& clientId) {
  host_ = host;
  port_ = port;
  user_ = user;
  password_ = password;
  clientId_ = clientId;
  mqtt_.setServer(host_.c_str(), port_);
}

void TransportMqtt::setCallback(MessageCallback cb) {
  mqtt_.setCallback([cb](char* topic, byte* payload, unsigned int length) { cb(topic, payload, length); });
}

bool TransportMqtt::connect() {
  bool ok = user_.isEmpty()
    ? mqtt_.connect(clientId_.c_str())
    : mqtt_.connect(clientId_.c_str(), user_.c_str(), password_.c_str());

  if (!ok) lastError_ = String("MQTT connect failed rc=") + mqtt_.state();
  return ok;
}

bool TransportMqtt::connected() const { return mqtt_.connected(); }

bool TransportMqtt::publish(const String& topic, const String& payload, bool retained) {
  bool ok = mqtt_.publish(topic.c_str(), payload.c_str(), retained);
  if (!ok) lastError_ = "MQTT publish failed";
  return ok;
}

bool TransportMqtt::subscribe(const String& topic) {
  bool ok = mqtt_.subscribe(topic.c_str());
  if (!ok) lastError_ = "MQTT subscribe failed";
  return ok;
}

void TransportMqtt::loop() { mqtt_.loop(); }
