# Drawing quality and efficiency — 2026-10-16

The source now supports multipart stored jobs, physical-unit path preparation,
pen-aware conversion settings, measured calibration artwork and timer diagnostics.
These changes have not been deployed or physically commissioned.

## Large jobs

The 1 MiB limit is a per-transfer SPIFFS limit, not the total job size. A job
larger than the device's advertised capacity is split into verified parts. Each
part drains motion, lifts the pen and synchronizes before the next upload.
A split within a long stroke retains the exact XY endpoint, travels there with
the pen up, lowers the pen and continues the remaining segments. No connecting
ink is introduced across separate paths. Extra lifts can leave a small mark at
a split inside a continuous stroke; this needs a supervised physical check.

The controller must remain running for automatic next-part transfers. Closing
the browser alone does not stop that service. If the controller or network
fails, the ESP32 finishes its current verified part, lifts and waits. A reconnect
or controller restart continues the same reviewed job on the same device boot.
Deterministic part/run IDs, offsets and CRCs prevent repeated starts after lost
upload, commit or start acknowledgements. Explicit pause stays paused across
controller restart. Stop, a device reboot, unknown position or changed
calibration blocks continuation. No reboot restores position automatically.

Firmware advertises `stored_plot_api=2`. `plot_begin` additionally receives
`parent`, `chain`, zero-based `part` and `final`. The device accepts only the next
part of the retained chain while waiting, and rejects streamed/manual motion
until that chain finishes or is stopped. Continuation authority lives in RAM and
is discarded on reboot. The current stored file can survive a reboot, but
reviewing/restarting after reference recovery is required.

Files are verified before motion, never streamed directly into executing motor
commands. Upload and execution are sequential: no flash writes during motion.
Finished/stopped parts release their files after motion settles, retaining only
same-boot receipts/chain state in RAM. Partial uploads expire after two idle
minutes and unstarted complete files after ten. Replacement uploads reclaim the
old idle slot; two 1 MiB files need not fit simultaneously. See
[stored plots](STORED_PLOTS.md) for cleanup/retry details. There is no firmware partition-table change.

Legacy firmware still accepts jobs fitting one file. Larger jobs are refused
before movement with a request to update firmware. Controller work/memory limits
remain independent of ESP32 transfer limits (100,000 source/transformed points;
command count bounded from that limit).

## Preparation controls

- Pen width sets a floor for raster spacing and bounds outline/path simplification.
- Minimum mark length defaults to zero, preserving small marks unless explicitly filtered.
- Path tolerance defaults to 0.02 mm; endpoint and closure retention replace the
  old 0.02 mm point-dropping filter. Setting zero disables path simplification.
- SVG curves are re-flattened for their final paper size at 0.025 mm tolerance.
  Bilinear paper placement subdivides by its midpoint error, rather than adding
  points every 5 mm to straight paths.
- Pen-up travel has its own speed, initially 10 mm/s in the UI and bounded by the
  existing 30 mm/s device limit. No motor acceleration ceiling was increased.
- SVG/outline travel optimization uses bounded nearest-endpoint ordering and a
  local 2-opt pass, with stroke reversal. It accepts a route only if travel is
  shorter. It never draws connectors. Hatch/wave layer ordering is retained.
- Crosshatching defaults to no white-gap bridging. Optional bridging is in mm;
  connections between adjacent runs must remain in the inked tone mask.
- Estimates include servo ramps/settling, travel and approximate acceleration,
  with pen and travel time visible separately. Corner slowdowns, initial travel,
  live overrides and multipart uploads can still increase actual time.

## Firmware motion and diagnostics

ESP32 accepts every nonzero motor-step block instead of dropping blocks under
six steps. Distances use the last accepted Cartesian endpoint, including any
preceding targets that quantized to zero steps. The timer's minimum step rate is
1 pulse/s on ESP32, removing the inherited AVR 120 pulse/s floor for tiny/slow
moves. Requested targets finer than a physical microstep still cannot be executed
exactly; the nominal command scale is 80 microsteps/mm of belt.

Polargraph lines subdivide adaptively using quarter/mid/three-quarter belt-space
interpolation error (0.025 mm sampled tolerance), a 5 mm maximum leaf length and
a bounded recursion depth. Host tests check dense interior samples at several
heights. This controls kinematic interpolation error, not mechanical accuracy.

The timer ISR and its out-of-line application callees reside in IRAM. ESP32 uses
direct single-step timer division instead of an AVR flash lookup table; override
scaling avoids 64-bit division helpers. The linked symbol table and disassembly
were inspected. PWM updates remain outside the ISR. Wi-Fi configuration flash
writes are rejected while motion or stored-job ownership is active.

Motion diagnostics show maximum ISR duration, observed entry delay, interval
clamps and planner drains. Drains include normal pen lifts/job ends; the count
alone is not evidence of starvation. Compare counters during one uninterrupted
stroke and capture STEP/DIR with a logic analyzer before changing timer/planner
architecture or enabling different acceleration profiles.

## Physical calibration and driver commissioning

Prepare the accuracy grid in the UI, review it and start it explicitly. Nominal
spacing is 50 mm; the central circle is 50 mm in diameter. The last row/column can
be shorter. Bilinear warping follows captured corners, so compare expected
positions against the actual paper placement, not an assumed axis-aligned sheet.
Measure repeated grid intersections at the centre and edges, circle roundness,
closed-path endpoint error, and repeatability approaching from both directions.

For held-out XY measurements, save a JSON array like:

```json
[
  {"expected": [50, 50], "measured": [50.3, 50.4]},
  {"expected": [100, 50], "measured": [100.2, 50.1]},
  {"expected": [50, 100], "measured": [50.1, 100.2]}
]
```

Run `python3 -m controller.accuracy measurements.json` to report RMS, maximum
and mean axis errors. This does not silently change calibration. Four-corner
fitting still treats shaft spacing and motor scales as supplied measurements;
do not compensate mechanical faults by warping the calibration until measured
repeatability establishes which parameters are wrong.

Inspect pen spring/compliance and pressure, rocking, belt tension and routing,
pulley seating/eccentricity and servo-lead drag. Repeat the pattern at a few
speeds while measuring temperature and missed-step/repeatability behavior.
TMC2209 UART remains disabled: UART pins, module addressing, current-sense resistor,
actual motor current rating and routing must be established on the assembled
board before changing current or chopper modes. No unverified pin assignments,
current changes or automatic commissioning motions were introduced.

## Verification and deployment

Run `python3 -m unittest discover -s test -p 'test_*.py'` with NumPy installed,
`node test/test_web.mjs`, compile/run the standalone host C++ checks in `test/`, run the special storage
harness with `python3 test/run_storage_native.py --arduinojson .pio/libdeps/esp32-polargraph/ArduinoJson/src`
(`plot_store_native.cpp` is linked by that runner), then
`pio run -e esp32-polargraph`. Simulator integration checks need loopback sockets.
Firmware artifacts are built without flashing. Coordinate a supervised idle
window for firmware installation and restore the physical reference afterwards.
The live controller's open-access deployment override must be preserved; its
host record in the Mgmt workspace documents that service-specific setting.
