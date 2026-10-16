#include "configure.h"
#ifdef TARGET_ESP32
#include "motion_control.h"
#include <math.h>

static int requestedPercent=100;
static volatile uint32_t appliedPermille=1000;
static float servoSpeed=WALL_SERVO_SPEED_DEG_S;
static uint32_t lastUpdate=0;
static MotionDiagnostics diagnostics;
void DRAWY_ISR motionRecordIsr(uint32_t work,uint32_t latency,bool clamped) {
  ++diagnostics.pulses;
  if(work>diagnostics.maxIsrUs)diagnostics.maxIsrUs=work;
  if(latency>diagnostics.maxLatencyUs)diagnostics.maxLatencyUs=latency;
  if(clamped)++diagnostics.intervalClamps;
}
void DRAWY_ISR motionRecordDrain() { ++diagnostics.plannerDrains; }
MotionDiagnostics motionDiagnostics() {
  portENTER_CRITICAL(&stepperMux);
  const MotionDiagnostics copy=diagnostics;
  portEXIT_CRITICAL(&stepperMux);
  return copy;
}
bool motionSetSpeeds(int percent,float speed) {
  if (percent<10 || percent>100 || !isfinite(speed) || speed<5 || speed>120) return false;
  requestedPercent=percent;servoSpeed=speed;
  return true;
}
int motionStepperPercent() { return requestedPercent; }
uint32_t DRAWY_ISR motionStepperPermille() { return appliedPermille; }
float motionServoSpeed() { return servoSpeed; }
void motionUpdateSpeeds(uint32_t now) {
  uint32_t elapsed=now-lastUpdate;
  if (!elapsed) return;
  lastUpdate=now;
  if (elapsed>50) elapsed=50;
  const uint32_t target=requestedPercent*10,current=appliedPermille;
  // At most 100 percentage points per second, including during calibration.
  appliedPermille=current<target ? (target-current<elapsed ? target : current+elapsed)
                                : (current-target<elapsed ? target : current-elapsed);
}
#endif
