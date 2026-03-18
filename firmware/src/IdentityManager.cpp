#include "IdentityManager.h"
#include <Preferences.h>
#include <esp_system.h>

String IdentityManager::slugify(const String& input) {
  String out;
  for (size_t i = 0; i < input.length(); ++i) {
    char c = tolower(input[i]);
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) out += c;
    else if (c == ' ' || c == '_' || c == '-') out += '-';
  }
  while (out.indexOf("--") >= 0) out.replace("--", "-");
  return out;
}

String IdentityManager::generateDeviceUid() {
  uint64_t chipid = ESP.getEfuseMac();
  char buf[17];
  snprintf(buf, sizeof(buf), "%04x%08x", (uint16_t)(chipid >> 32), (uint32_t)chipid);
  return String(buf);
}

bool IdentityManager::begin(const String& nodeNameHint) {
  Preferences p;
  p.begin("cnp", false);

  identity_.deviceUid = p.getString("device_uid", "");
  if (identity_.deviceUid.isEmpty()) {
    identity_.deviceUid = generateDeviceUid();
    p.putString("device_uid", identity_.deviceUid);
  }

  identity_.nodeId = p.getString("node_id", "");
  if (identity_.nodeId.isEmpty()) {
    identity_.nodeId = "cnp-" + slugify(nodeNameHint) + "-" + identity_.deviceUid.substring(identity_.deviceUid.length() - 6);
    p.putString("node_id", identity_.nodeId);
  }

  p.end();
  return true;
}
