# Firmware Architecture and ESP32 Port Audit

This audit records the inherited baseline before the ESP32 implementation. The gaps below have since been addressed for ESP32-WROOM; current instructions and verification limits are in [ESP32 wiring and setup](ESP32_WIRING_AND_SETUP.md).

## Architecture

The repository is archived historical Makelangelo firmware. Its default PlatformIO target is AVR Rumba polargraph, not ESP32.

G-code/serial input → Parser (src/parser.*) → buffered Planner (src/planner.*) → polargraph IK (src/robots/polargraph.cpp) → Stepper ISR/Motor (src/motor.*) → STEP/DIR/ENABLE.

- Makelangelo-firmware.cpp starts parser, HAL, EEPROM, planner, motor setup, and virtual pen-up position.
- polargraph.cpp contains inverse/forward belt-length geometry, recordHome(), and robot_findHome().
- config_motors.h already derives 80 steps/mm for 200-step motors, 16× microsteps, and 40 mm pulley pitch.
- parser.cpp maps G28 to robot_findHome(); M17/M18 enable/disable; M112 emergency-stops planner/interrupts; M114 reports; M280 commands servo.
- eeprom_manager.cpp stores geometry/settings/calibration. It cannot establish physical position after manual motion.

## Reuse assessment

| Element | Assessment | Needed work |
| --- | --- | --- |
| Polargraph IK/FK | Good starting concept | Validate anchor coordinates, coordinate frame, limits, unreachable geometry |
| Planner | Potentially reusable | Real ESP32 ISR, timing, critical-section validation |
| STEP/DIR | Reusable abstraction | Safe real GPIO/pulse timing |
| Servo commands | Concept reusable | ESP32 PWM/servo implementation independent of step timer |
| EEPROM model | Concept reusable | NVS/Preferences or compatible EEPROM emulation |
| Homing | Unsafe unchanged | Bounded, debounced, fault-aware redesign |

## Critical ESP32 blockers

1. platformio.ini has no ESP32 environment.
2. boards/esp32.h includes HAL_avr.h; no ESP32 HAL exists. Available HALs are AVR, STM32F4, and partial ESP8266.
3. The ESP32 limit-switch macros are (), not GPIO numbers, but motor.cpp passes them to pinMode.
4. GPIO 0, 12, and 15 are assigned in the legacy header; they are ESP32 boot-strapping pins and not an acceptable generic map.
5. The code has TMC2130 support only (tmc2130.*), not TMC2209 UART.
6. The normal Arduino Servo path needs ESP32-compatible PWM integration.
7. Existing homing lacks maximum travel/time bounds, switch fault policy, debounce, and verified motor-direction mapping.

robot_findHome() does independently stop a motor after its switch triggers, then performs a fixed 500-step back-off and slow re-approach. It relies on stored calibration to derive XY and queues a home move. recordHome() separately measures reference distance. Neither may be enabled on this machine unmodified.

## Port boundary

First create an ESP32 target/HAL that demonstrates: enable outputs inactive by default; STEP pins low; deterministic DIR; correctly read NC inputs; servo starts pen-up; and no motion ISR runs before explicit arming. Then integrate planner motion. Do not define HAS_TMC2130 for TMC2209. Use STEP/DIR first; later UART requires dedicated TMCStepper integration and tested bus/address/current/StealthChop/DIAG behavior.
