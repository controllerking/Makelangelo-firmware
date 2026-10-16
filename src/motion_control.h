#pragma once
#include <stdint.h>
#ifdef TARGET_ESP32
#include <esp_attr.h>
#define DRAWY_ISR IRAM_ATTR
#else
#define DRAWY_ISR
#endif

// Override only slows the planned profile; it cannot exceed commissioned limits.
inline __attribute__((always_inline)) uint32_t motionScaledInterval(uint32_t ticks,uint32_t permille) {
  if (permille<100) permille=100;
  if (permille>1000) permille=1000;
  // Avoid 64-bit division helpers in the timer ISR.
  const uint32_t whole=ticks/permille,remainder=ticks%permille;
  if(whole>UINT32_MAX/1000)return UINT32_MAX;
  const uint32_t base=whole*1000,extra=(remainder*1000+permille-1)/permille;
  return extra>UINT32_MAX-base ? UINT32_MAX : base+extra;
}
#ifdef TARGET_ESP32
bool motionSetSpeeds(int percent,float servoSpeed);
int motionStepperPercent();
uint32_t DRAWY_ISR motionStepperPermille();
struct MotionDiagnostics { uint32_t pulses=0,maxIsrUs=0,maxLatencyUs=0,intervalClamps=0,plannerDrains=0; };
void DRAWY_ISR motionRecordIsr(uint32_t work,uint32_t latency,bool clamped);
void DRAWY_ISR motionRecordDrain();
MotionDiagnostics motionDiagnostics();
float motionServoSpeed();
void motionUpdateSpeeds(uint32_t now);
#endif
