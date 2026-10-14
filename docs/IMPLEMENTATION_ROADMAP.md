# Implementation Roadmap

Software status: ESP32-WROOM motion support and the wireless/computer controller are implemented. See [wireless control](WIRELESS_CONTROL.md) for the current protocol and verification record. Hardware acceptance gates below still require the assembled machine.

## Gates

| Phase | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 0 Mechanical survey | measured geometry and interference map | belt route, switches, travel, hard stops, drawing envelope approved |
| 1 Electrical prototype | fused 24 V/5 V distribution, selected ESP32 | voltage/current/ground/power-off tests |
| 2 ESP32 foundation | PlatformIO target, HAL, GPIO map | clean build; inactive outputs and safe inputs on bench |
| 3 Motion baseline | hardware-configured TMC2209 STEP/DIR | direction/scale/temperature/no skipped steps at conservative settings |
| 4 Safe homing | state machine | normal, already-active, disconnected, stuck, timeout, abort tests |
| 5 Calibration | geometry and limits | fiducial/grid accuracy and repeatability measured |
| 6 Pen | lift/pressure/cable path | reliable clear/contact, no measurable cable bias |
| 7 Usability | local controls/status/job flow | owner can home, draw, and stop safely |
| 8 Optional | UART/Wi-Fi/presets | core safety regression remains passing |

## Firmware order

1. Add an ESP32-specific PlatformIO environment without changing legacy AVR targets.
2. Pick an actual board and GPIO map. Avoid boot straps 0/2/4/5/12/15 unless its schematic proves safety; never use input-only/flash pins as outputs.
3. Implement deterministic step timing, critical sections, and separate servo PWM; verify pulses with a logic analyzer if possible.
4. Create a machine profile containing measured geometry and conservative rate, acceleration, pen, and physical-limit values.
5. Implement states: UNHOMED → PRECHECK → SEEK → BACKOFF → LATCH → ESTABLISH_POSITION → READY, with terminal FAULT.
6. Require debounced expected switch transitions and per-axis step/time bounds. Never drive further into a reference already active at boot.
7. Reject all drawing moves outside READY. Maintain a physical emergency-stop/power cut-off independent of firmware.
8. Plot fiducials and grids, then tune tension, feed, acceleration, current, and noise.

## Required mechanical validation

Produce a dimensioned drawing/CAD sketch covering motor centers, paper/drawing edges, pulleys/idlers, belt route, counterweight path/hard stops, gondola extremes, clips, cable, electronics depth, braces, and cleat clearance. Review running torque, wrap/tension, weight retention, and manual snag hazards.

Test drivers disconnected, drivers powered/belts off, one axis at a time, switch disconnect/stuck/bounce, active switch at boot, blocked travel, e-stop, and repeated power-off/manual-move/restart cycles. No drawing may occur until a valid home passes.

## Deferred scope

Wi-Fi/web UI, paper presets, TMC2209 UART/StealthChop tuning, sensorless homing, automatic calibration, SD/LCD, and job-management polish must not weaken local homing and stop behavior.
