#pragma once
#include <Arduino.h>
#include "Types.h"

class OtaManager {
 public:
  bool begin();
  Result updateFromUrl(const String& url);
};
