# ESP32-WROOM wiring and commissioning

For PCB design, use the [PCB hardware and circuit specification](PCB_HARDWARE_SPEC.md).
It separates the existing bench wiring from proposed carrier circuitry and
lists the module/footprint and power-protection details still needed before fabrication.

## Supported hardware and current status

Target: a classic ESP32-WROOM development board with USB-to-serial programming, two standalone BIGTREETECH TMC2209 drivers, two NC switches, and one MG90S. The firmware compiles with PlatformIO espressif32 6.10.0 / Arduino-ESP32 2.0.17. It was flashed successfully on 2026-10-12 to the connected ESP32-D0WD-V3 (revision 3.1) through /dev/cu.usbserial-0001. Flash hashes verified and the board booted into Drawy-Setup-67b4fc with drawing locked. Physical motor/servo commissioning remains.

The ESP32 build is the default. Wi-Fi provisioning, authenticated TCP control, and the computer-side browser controller are implemented; see [wireless setup](WIRELESS_CONTROL.md). TMC2209 UART remains deferred. Uncalibrated settings leave drawing locked. Once directions/travel are commissioned, automatic boot homing can be enabled.

## Signal wiring

Use the GPIO number printed on the board, not the physical header position. With the supply switched off:

| Connection | ESP32 GPIO | Other end |
| --- | --- | --- |
| Left STEP | 18 | left driver STEP |
| Left DIR | 19 | left driver DIR |
| Left enable | 23 | left driver EN/ENN |
| Left switch | 32 | left switch NC; COM to GND |
| Right STEP | 26 | right driver STEP |
| Right DIR | 27 | right driver DIR |
| Right enable | 25 | right driver EN/ENN |
| Right switch | 33 | right switch NC; COM to GND |
| Pen signal | 21 | servo signal |
| Driver logic supply | 3V3 | both drivers VIO/VDD logic pins |
| Logic ground | GND | driver grounds, switch COM, buck negative, servo ground |

Fit a **10 kΩ pull-up from each EN pin to 3.3 V**, so the drivers stay disabled through reset before firmware runs. Fit an external 4.7–10 kΩ pull-up from each switch GPIO to 3.3 V for the long switch harnesses; internal pull-ups are also enabled. An intact released NC switch reads 0; an actuated switch or broken wire reads 1. Use COM and NC, leaving NO unused.

2026-10-14 prototype correction: left/right mean facing the drawing. Motor
channels were swapped in firmware to match the actual wiring, and the physical
left motor uses `MOTOR_0_DIR_INVERT=1`; right remains non-inverted. Positive
payout therefore drives left DIR HIGH and right DIR LOW. This applies to raw
jogs, calibration, planner moves and logical homing directions. Restart any
in-progress calibration after this correction; do not reuse captures from the
old channel assignment.

These GPIO choices avoid classic ESP32 strapping and flash pins. GPIO16/17 are left available for a possible later UART connection. See the [Espressif GPIO reference](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/gpio.html).

## Driver, motor, and power connections

- Fused 24 V positive goes to both driver VM inputs and buck IN+. Supply negative goes to driver power GND and buck IN−.
- Set and measure the buck output at 5 V before connecting it. Servo power goes directly to the buck's 5 V output, with common ground.
- Power the development board through USB for initial tests. Later, use its documented 5 V/VIN input only if compatible. Avoid simultaneous USB and external 5 V unless its schematic explicitly supports that.
- Each motor coil pair goes to its driver's A1/A2 and B1/B2 outputs. Identify coil pairs by continuity; do not assume wire colours.
- Set both MS1 and MS2 to the driver's 3.3 V logic supply for 16× microstepping. The firmware uses 80 external STEP pulses/mm; interpolation does not change that number.
- Select standalone StealthChop using the module's documented SPREAD/mode connection. Do not connect DIAG to these physical homing inputs. PDN/UART is not connected to the ESP32 in this build; follow the exact module revision's standalone wiring requirements.
- Set current with the module's current/Vref adjustment procedure; begin conservatively (for example around 0.5 A RMS) and verify torque/temperature. The firmware does not set current without UART.
- Fit appropriate local VM decoupling as required by the module/carrier, keep motor wiring away from switch leads, and install the driver heatsinks.
- Never connect 24 V to logic/servo power or connect/disconnect motor windings while energized.

Match pin labels and module revision rather than copying a header orientation. References: [BIGTREETECH driver files](https://github.com/bigtreetech/BIGTREETECH-Stepper-Motor-Driver/tree/master/TMC2209) and [TMC2209 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/tmc2209_datasheet_rev1.09.pdf).

## Build and upload

From the repository root:

```sh
pio run -e esp32-polargraph
pio run -e esp32-polargraph -t upload --upload-port /dev/cu.YOUR_USB_SERIAL_PORT
pio device monitor --port /dev/cu.YOUR_USB_SERIAL_PORT --baud 57600
```

Use the actual USB serial port reported by PlatformIO. If pio is not on PATH on this workstation, it is installed at /Users/ryderholland/.platformio/penv/bin/pio. Upload resets the board; keep the pen clear and belts unloaded for the first upload.

## First bench checks

1. Begin with belts removed and the pen mechanism unloaded. Boot should leave motors disabled and command pen-up. Use M114 to inspect UNKNOWN position and the switch states.
2. Press/release each switch and unplug each harness. Released = 0, pressed/disconnected = 1. Correct this before motion.
3. M17 energizes motors. M18 releases them and invalidates position. Check current and temperature.
4. D0 X80 jogs the left motor 80 pulses; D0 Y80 does the right. A positive jog must increase the gondola-side belt length (left DIR HIGH, right DIR LOW with the current inversion settings). D0 X-80 / Y-80 reverses it. The command is a deliberate commissioning jog available before homing, limited to 3,200 pulses per axis and does not establish position.
5. If a motor's positive jog shortens the gondola-side belt, power off and reverse one coil's leads to normalize it. Do not compensate only the homing direction: drawing and homing must agree.
6. Check servo operation with M280 P0 S90 (initial pen-up angle) and S40 (initial pen-down angle). Mechanically unload the linkage first and calibrate for 3–5 mm clearance. M280 also accepts microsecond pulses above 500, clamped to the configured safe pulse range.
7. M112 stops queued/current motion, disables drivers, commands pen-up, and latches a fault until hardware reset. It is handled as soon as a complete serial line arrives, including during homing/planner waits. Keep a physical power switch accessible: serial delivery is not a hardware emergency-stop circuit.

D0 ignores the drawing envelope for commissioning. Use it with belts removed or under direct observation. Never send a drawing job while commissioning.

## Machine geometry and homing calibration

Set the coordinate frame to motor shaft centres, X right and Y up. The default proposed convention is left anchor X=0, right anchor X=measured spacing, anchor Y=0; the drawing plane lies at negative Y. Do not use the frame width as a measured motor spacing.

Send these commands with actual numeric measurements substituted:

```text
M101 A0 B<left-anchor-X> T<right-anchor-X>
M101 A1 B<lowest-safe-Y> T<anchor-Y>
D7 L<left-reference-length-mm> R<right-reference-length-mm>
D9
M500
M503
```

D7 values are the calibrated effective gondola-side belt lengths when both counterweights have completed their slow reference latch. They are not motor step counts, counterweight travel, or total belt length. Account for the final routing, effective anchors, and gondola attachment geometry. A measured reference must form a valid triangle below/between the anchors.

The axis limits currently serve both anchor geometry and coarse travel bounds. They are not an independent 16×22 in paper rectangle; the drawing job must stay within the measured paper/clip/counterweight collision envelope. Do not reduce X anchor limits to the paper edges, because that changes the kinematics.

Create an ignored src/esp32_local.h using the tracked example at docs/esp32_local.example.h. After physically verifying belt directions, both switch cycles, collision-free travel, and maximum travel, set WALL_HOMING_CONFIRMED to 1, adjust travel bounds, and rebuild/upload. It stays 0 in the shipped configuration to prevent an unverified automatic seek.

G28 then:
- Retracts the pen, checks reference geometry, and independently controls both cable axes.
- Seeks a released switch, pauses pulses immediately at assertion, and requires 10 ms stability.
- Backs off a configured distance and requires stable release. An already-active switch starts in this backoff phase.
- Re-approaches slowly, latches each axis independently, and establishes the measured reference position.
- Leaves the pen up at the references; there is no unverified automatic move to a guessed park point.

Timeout, exceeded step bounds, failure to release, or M112 latches a fault and requires reset. Neither axis may use the previous powered-off step count. With WALL_AUTO_HOME=1 (default), confirmed and calibrated machines repeat homing on boot. Set it to 0 if you want explicit G28 instead.

## Drawing commands and limits

Use G90 for absolute position and G0/G1 X... Y... Z... F... for lines. F is **mm/second**, not conventional mm/minute. Z is a servo angle. Initial defaults: 10 mm/s feed, 50 mm/s² acceleration; caps are 30 mm/s and 100 mm/s². M280/D13 provide direct pen control.

G92 invalidates position and requires rehoming; it cannot substitute for a physical reference. Settings changes affecting geometry/scale also invalidate position. Use M18 only when willing to rehome. Wait for the serial ready response and do not flood the small command queue.

G2/G3 circular arcs are supported with clockwise/counterclockwise direction corrected for this target, radius consistency checks, and travel-extrema checks before queuing. This inherited command dialect treats I/J as absolute centre coordinates in G90 and offsets in G91.

## Verification performed in development

The WROOM firmware build and host tests pass. Host tests exercise a geometry grid with different per-axis scales, sub-mm rounding, normal and initially-active switch cycles, stuck-open/closed and missing-latch failures, debounce, timeout, and millis rollover. Logic-analyzer timing, real motor/servo behavior, repeated power-loss recovery, drawing accuracy, driver heating, and collision clearance remain physical commissioning work.

Run the host tests from the repository root:

```sh
c++ -std=c++11 -Wall -Wextra -Werror -fsanitize=address,undefined test/esp32_logic.cpp -o /tmp/drawy-esp32-test
/tmp/drawy-esp32-test
```
