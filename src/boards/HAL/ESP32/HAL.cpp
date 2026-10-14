#include "configure.h"
#ifdef TARGET_ESP32
#include <EEPROM.h>
#include <driver/timer.h>
Esp32Serial esp32Serial(false, Serial);
portMUX_TYPE stepperMux = portMUX_INITIALIZER_UNLOCKED;
static hw_timer_t *stepTimer = nullptr;
static bool timerEnabled = false;
static bool storageReady = false;
void HAL_init() { storageReady = EEPROM.begin(512); }
bool HAL_storage_ready() { return storageReady; }
bool HAL_timer_initialized(uint8_t) { return stepTimer != nullptr; }
bool HAL_timer_interrupt_enabled(uint8_t) { return timerEnabled; }
void HAL_timer_start(uint8_t) {
  if (stepTimer) return;
  // Pinned Arduino-ESP32 2.0.17: 80 MHz / 80 = 1 MHz.
  stepTimer = timerBegin(0, 80, true);
  if (!stepTimer) return;
  timerAttachInterrupt(stepTimer, &Step_Handler, false);
  timerAlarmWrite(stepTimer, 1000, true);
  HAL_timer_enable_interrupt(0);
}
void HAL_timer_enable_interrupt(uint8_t) {
  if (!stepTimer || timerEnabled) return;
  timerWrite(stepTimer, 0);
  timerEnabled = true;
  timerStart(stepTimer);
  timerAlarmEnable(stepTimer);
}
void HAL_timer_disable_interrupt(uint8_t) {
  if (!stepTimer) return;
  timerEnabled = false;
  timerStop(stepTimer);
  timerAlarmDisable(stepTimer);
}
void HAL_timer_set_compare(uint8_t, hal_timer_t ticks) {
  if (stepTimer) timer_group_set_alarm_value_in_isr(TIMER_GROUP_0, TIMER_0, ticks < 20 ? 20 : ticks);
}
hal_timer_t HAL_timer_get_count(uint8_t) {
  return stepTimer ? timer_group_get_counter_value_in_isr(TIMER_GROUP_0, TIMER_0) : 0;
}
#endif
