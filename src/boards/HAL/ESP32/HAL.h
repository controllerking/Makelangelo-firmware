#pragma once
#ifdef TARGET_ESP32
#include <Arduino.h>
#include "macros.h"
#define CPU_32_BIT
#define NUM_SERIAL 1
#include "serial_hook.h"
using Esp32Serial = ForwardSerial<decltype(Serial)>;
extern Esp32Serial esp32Serial;
#define MYSERIAL1 esp32Serial
#include "serial.h"
using hal_timer_t = uint32_t;
#define HAL_TIMER_TYPE_MAX 0xFFFFFFFFUL
#define HAL_TIMER_RATE 1000000UL
#define STEPPER_TIMER_RATE HAL_TIMER_RATE
#define STEPPER_TIMER_PRESCALE 80
#define STEPPER_TIMER_TICKS_PER_US 1
#define STEP_TIMER_NUM 0
#define PGMSTR(NAM,STR) const char NAM[] = STR
extern portMUX_TYPE stepperMux;
#define CRITICAL_SECTION_START() portENTER_CRITICAL(&stepperMux)
#define CRITICAL_SECTION_END() portEXIT_CRITICAL(&stepperMux)
#define ENABLE_STEPPER_DRIVER_INTERRUPT() HAL_timer_enable_interrupt(0)
#define DISABLE_STEPPER_DRIVER_INTERRUPT() HAL_timer_disable_interrupt(0)
#define STEPPER_ISR_ENABLED() HAL_timer_interrupt_enabled(0)
#define ENABLE_ISRS() HAL_timer_enable_interrupt(0)
#define DISABLE_ISRS() HAL_timer_disable_interrupt(0)
#define HAL_STEP_TIMER_ISR() void Step_Handler()
extern void Step_Handler();
extern void HAL_init();
extern bool HAL_storage_ready();
extern void HAL_timer_start(uint8_t);
extern void HAL_timer_enable_interrupt(uint8_t);
extern void HAL_timer_disable_interrupt(uint8_t);
extern bool HAL_timer_interrupt_enabled(uint8_t);
extern bool HAL_timer_initialized(uint8_t);
extern void HAL_timer_set_compare(uint8_t, hal_timer_t);
extern hal_timer_t HAL_timer_get_count(uint8_t);
#endif
