#include "OtaManager.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <HTTPUpdate.h>

bool OtaManager::begin() { return true; }

Result OtaManager::updateFromUrl(const String& url) {
  if (url.isEmpty()) return Result::Fail("ERR_OTA_URL", "OTA URL missing");
  t_httpUpdate_return ret = httpUpdate.update(url);
  switch (ret) {
    case HTTP_UPDATE_FAILED:
      return Result::Fail("ERR_OTA_FAILED", httpUpdate.getLastErrorString());
    case HTTP_UPDATE_NO_UPDATES:
      return Result::Fail("OTA_NO_UPDATES", "No updates available");
    case HTTP_UPDATE_OK:
      return Result::Ok("OTA applied");
  }
  return Result::Fail("ERR_OTA_UNKNOWN", "Unexpected OTA return");
}
