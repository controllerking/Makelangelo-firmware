#pragma once
#if MOTHERBOARD == BOARD_ESP32
#  include <sdkconfig.h>
#  if !defined(ESP32) || !defined(TARGET_ESP32)
#    error "Select an esp32-polargraph PlatformIO environment."
#  endif
#  if !defined(CONFIG_IDF_TARGET_ESP32)
#    error "This profile is for ESP32-WROOM (classic ESP32), not S2/S3/C3."
#  endif
#  include "esp32_config.h"
#  define MAX_MOTORS 2
#  define MAX_BOARD_SERVOS 1
#  define MOTOR_0_LETTER 'X'
#  define MOTOR_1_LETTER 'Y'
#  define LIMIT_SWITCH_PIN_LEFT MOTOR_0_LIMIT_SWITCH_PIN
#  define LIMIT_SWITCH_PIN_RIGHT MOTOR_1_LIMIT_SWITCH_PIN
// NC to GND, pull-up to 3.3 V: actuated OR broken wire reads HIGH.
#  define LIMIT_SWITCH_PRESSED_LEFT HIGH
#  define LIMIT_SWITCH_PRESSED_RIGHT HIGH
#  define MOTOR_ENABLE_OFF_0 HIGH
#  define MOTOR_ENABLE_OFF_1 HIGH
#  define START0 HIGH
#  define START1 HIGH
#  define END0 LOW
#  define END1 LOW
#  define DEFAULT_FEEDRATE 10.0f
#  define DEFAULT_ACCELERATION 50.0f
#  define UNITS_PER_STEP (PULLEY_PITCH / STEPS_PER_TURN)
#  undef HAS_WIFI
#  undef HAS_SD
#  undef HAS_LCD
#  include "HAL/ESP32/HAL.h"
#endif
