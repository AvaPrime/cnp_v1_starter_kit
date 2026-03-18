#pragma once
#include <Arduino.h>

struct NodeIdentity {
  String deviceUid;
  String nodeId;
  String protocolVersion = "CNPv1";
  String firmwareVersion = "0.1.0";
};

class IdentityManager {
 public:
  bool begin(const String& nodeNameHint);
  const NodeIdentity& get() const { return identity_; }
 private:
  String generateDeviceUid();
  String slugify(const String& input);
  NodeIdentity identity_;
};
