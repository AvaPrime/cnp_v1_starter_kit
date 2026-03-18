#include "Application.h"
#include "BaseModule.h"

BaseModule& getModule();

Application app(getModule());

void setup() {
  app.begin();
}

void loop() {
  app.loop();
  delay(10);
}
