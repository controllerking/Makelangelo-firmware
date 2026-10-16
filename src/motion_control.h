#pragma once
#include <stdint.h>

// Override only slows the planned profile; it cannot exceed commissioned limits.
inline uint32_t motionScaledInterval(uint32_t ticks,uint32_t permille) {
  if (permille<100) permille=100;
  if (permille>1000) permille=1000;
  const uint64_t scaled=(uint64_t(ticks)*1000+permille-1)/permille;
  return scaled>UINT32_MAX ? UINT32_MAX : uint32_t(scaled);
}
#ifdef TARGET_ESP32
bool motionSetSpeeds(int percent,float servoSpeed);
int motionStepperPercent();
uint32_t motionStepperPermille();
float motionServoSpeed();
void motionUpdateSpeeds(uint32_t now);
#endif
