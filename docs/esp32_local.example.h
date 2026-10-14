#pragma once
// Copy to src/esp32_local.h (ignored by Git).
// Defaults already match docs/ESP32_WIRING_AND_SETUP.md.
//
// Set to 1 only after verifying directions, switches, routing, and travel.
// #define WALL_HOMING_CONFIRMED 1
// #define WALL_AUTO_HOME 1

// At 80 pulses/mm: 400 pulses = 5 mm backoff.
// Derive maximum seek from actual safe counterweight travel, not frame height.
// #define WALL_HOMING_MAX_STEPS 80000UL
// #define WALL_HOMING_BACKOFF_STEPS 400UL
// #define WALL_HOMING_INTERVAL_US 2500UL

// Calibrate linkage and pressure on the assembled gondola.
// #define PEN_UP_ANGLE 90
// #define PEN_DOWN_ANGLE 40
// #define WALL_SERVO_MIN_US 1000
// #define WALL_SERVO_MAX_US 2000
