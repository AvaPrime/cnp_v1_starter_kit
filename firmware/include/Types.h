#pragma once
#include <Arduino.h>

enum class Severity : uint8_t { Debug, Info, Warning, Error, Critical };

struct Result {
  bool ok;
  String code;
  String message;

  static Result Ok(const String& message = "OK") { return {true, "OK", message}; }
  static Result Fail(const String& code, const String& message) { return {false, code, message}; }
};
