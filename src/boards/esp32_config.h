#pragma once
#include <esp_attr.h>
#if __has_include("esp32_local.h")
#  include "esp32_local.h"
#endif
// ESP32-WROOM GPIO numbers. Left/right are viewed from the drawing face.
// Prototype channels are crossed; its physical left motor also needs DIR inversion.
#ifndef MOTOR_0_DIR_INVERT
#  define MOTOR_0_DIR_INVERT 1
#endif
#ifndef MOTOR_1_DIR_INVERT
#  define MOTOR_1_DIR_INVERT 0
#endif
inline __attribute__((always_inline)) bool esp32MotorDirectionLevel(int axis, bool logicalHigh) {
  return logicalHigh != (axis == 0 ? bool(MOTOR_0_DIR_INVERT) : bool(MOTOR_1_DIR_INVERT));
}
#ifndef MOTOR_0_STEP_PIN
#  define MOTOR_0_STEP_PIN 18
#endif
#ifndef MOTOR_0_DIR_PIN
#  define MOTOR_0_DIR_PIN 19
#endif
#ifndef MOTOR_0_ENABLE_PIN
#  define MOTOR_0_ENABLE_PIN 23
#endif
#ifndef MOTOR_0_LIMIT_SWITCH_PIN
#  define MOTOR_0_LIMIT_SWITCH_PIN 32
#endif
#ifndef MOTOR_1_STEP_PIN
#  define MOTOR_1_STEP_PIN 26
#endif
#ifndef MOTOR_1_DIR_PIN
#  define MOTOR_1_DIR_PIN 27
#endif
#ifndef MOTOR_1_ENABLE_PIN
#  define MOTOR_1_ENABLE_PIN 25
#endif
#ifndef MOTOR_1_LIMIT_SWITCH_PIN
#  define MOTOR_1_LIMIT_SWITCH_PIN 33
#endif
#ifndef SERVO0_PIN
#  define SERVO0_PIN 21
#endif
#ifndef WALL_HOME_LEFT_DIR
#  define WALL_HOME_LEFT_DIR HIGH
#endif
#ifndef WALL_HOME_RIGHT_DIR
#  define WALL_HOME_RIGHT_DIR HIGH
#endif
#ifndef WALL_HOMING_MAX_STEPS
#  define WALL_HOMING_MAX_STEPS 80000UL
#endif
#ifndef WALL_HOMING_CONFIRMED
#  define WALL_HOMING_CONFIRMED 0
#endif
#ifndef WALL_AUTO_HOME
#  define WALL_AUTO_HOME 1
#endif
#ifndef WALL_HOMING_BACKOFF_STEPS
#  define WALL_HOMING_BACKOFF_STEPS 400UL
#endif
#ifndef WALL_HOMING_INTERVAL_US
#  define WALL_HOMING_INTERVAL_US 2500UL
#endif
#ifndef WALL_SERVO_MIN_US
#  define WALL_SERVO_MIN_US 1000
#endif
#ifndef WALL_SERVO_MAX_US
#  define WALL_SERVO_MAX_US 2000
#endif
#ifndef WALL_SERVO_SPEED_DEG_S
#  define WALL_SERVO_SPEED_DEG_S 35.0f
#endif
#ifndef WALL_SERVO_ACCEL_DEG_S2
#  define WALL_SERVO_ACCEL_DEG_S2 100.0f
#endif
static_assert(WALL_SERVO_SPEED_DEG_S>0 && WALL_SERVO_ACCEL_DEG_S2>0,
              "Servo ramp limits must be positive");

static_assert(WALL_HOMING_MAX_STEPS > 0 && WALL_HOMING_MAX_STEPS <= 1000000UL,
              "Homing seek bound must be 1..1000000 pulses");
static_assert(WALL_HOMING_BACKOFF_STEPS > 0 && WALL_HOMING_BACKOFF_STEPS <= 10000UL,
              "Homing backoff bound must be 1..10000 pulses");
static_assert(WALL_HOMING_INTERVAL_US >= 1000 && WALL_HOMING_INTERVAL_US <= 10000,
              "Homing interval must be 1000..10000 microseconds");
static_assert(WALL_SERVO_MIN_US >= 500 && WALL_SERVO_MAX_US <= 2500 &&
              WALL_SERVO_MIN_US < WALL_SERVO_MAX_US, "Invalid servo pulse limits");
