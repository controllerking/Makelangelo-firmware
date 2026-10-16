# Complete-plot upload and independent drawing

The computer still converts images/SVGs, fits artwork into captured paper
corners and checks bounds. On updated firmware, **Start** uploads a complete
verified part to ESP32 flash before starting it. Jobs fitting one part run
independently. Larger jobs transfer sequential verified parts; Wi-Fi loss or
controller shutdown lets the current part finish, lift the pen and wait for the
next. Browser closure alone does not stop the controller service. Stay nearby and supervise
the machine; independent execution does not mean unattended operation is safe.

## Capacity and format

The existing ESP32 4 MiB partition table reserves 1,408 KiB for SPIFFS. Firmware
limits a plot to 1 MiB (65,536 commands), reserves filesystem headroom and checks
actual free space. This is a per-transfer limit: the controller automatically
splits larger jobs with pen-up/sync boundaries and retained endpoint state.
Only one committed slot is kept. Finished parts and stopped jobs release their
files after motion/pen settling; only same-boot IDs/progress/chain remain in RAM.
Abandoned partial uploads expire after two idle minutes, unstarted verified
files after ten idle minutes, and failed commits/boot-time scratch are cleaned.
Replacement uploads also remove the previous idle slot before reserving space. Firmware API 2 checks the parent chain and next part number.
See [quality and efficiency](QUALITY_AND_EFFICIENCY.md) for multipart recovery,
compatibility and verification details.

Each record is 16 bytes, little-endian `<uint32 op, float32 x, y, feed>`:
0 = move; 1 = calibrated pen in/up; 2 = calibrated pen out/down; 3 = sync.
Non-move numeric fields are zero. Files must finish pen-up followed by sync.
The 13,234-command example uses 211,744 bytes, about 207 KiB. Binary coordinates
are stored as floats, not pixels. CRC32 detects incomplete/corrupt transfers;
the authenticated connection controls who may upload/start a file.

## Safety and recovery

- Uploads are chunked, offset-checked and repeatable. Incomplete/corrupt files
  cannot start. Geometry, feed, record types and final pen state are validated
  before publishing and again before starting a retained plot.
- Uploaded metadata binds the file to paper calibration UUID, motor pulse scale
  and pen endpoints. Changed calibration/unknown position requires restoration
  and a new reviewed start. No automatic home, pen-down or movement on boot.
- A complete unfinished file can survive a board reset until its idle expiry;
  finished files have already been reclaimed. Physical position does not survive. A power loss,
  fault or Stop interrupts the run. Restore position and explicitly restart;
  there is no power-loss continuation from a saved command number.
- Same-boot reconnect reports device progress. A unique run token makes repeated
  start requests idempotent, so a lost acknowledgement cannot draw twice.
- Explicit pause/resume, Stop, USB M112 and live speed controls still work.
  If Wi-Fi is unavailable, remote controls are unavailable: keep the physical
  power switch accessible and the suspended load mechanically supported.
- Legacy streamed commands still pause on link loss. Autonomous behavior applies
  only after a verified stored plot has actually started.

## Implementation

Authenticated boot-bound controls: `plot_begin`, `plot_chunk`, `plot_commit`,
`plot_start`. Chunks contain up to 384 decoded bytes, with an absolute byte
offset. Commit validates size/CRC32 and all records, then publishes the file and
metadata. Start uses a job UUID and unique run UUID; stored execution does not
consume streaming command IDs. Status includes API/capacity, job/run IDs,
received bytes, record count and completed record count.

Stored records feed the existing planner and pen-settle state machine in small
buffers rather than loading the file into RAM. Actual motor acceleration,
emergency-stop behavior and paper bounds remain enforced. Network transmission
is now buffered/nonblocking: partial sends and brief congestion no longer cause
an immediate disconnect. A stalled streaming link still eventually pauses.

The filesystem is mounted without formatting on boot. Only an explicit
confirmed upload may initialize an unmountable filesystem; this can erase old
plot storage if damaged, but does not erase Wi-Fi or pen NVS settings. Firmware
uses the existing partition table; do not erase the full chip unnecessarily.

Software verification includes compact format/CRC checks, full upload before
execution, offline completion and reconnect, explicit pause/Stop, rejection of
partial/corrupt files, duplicate starts and reboot-without-auto-resume. Hardware
flash/storage and supervised offline motion still require device commissioning.

## Storage cleanup and Emergency stop (2026-10-16)

The UI's Emergency stop is the immediate fault-latching stop, also used by USB
M112. It disables the timer, discards buffered motion, releases motor outputs and
invalidates position. Clearing that latch requires reset and explicit physical
reference restoration. Pause instead drains planned movement and retains the
energized motors and position for explicit resume. A future graceful job cancel
would need a separate drain-and-discard implementation; Stop does not pretend
the abrupt halt retained a trustworthy reference.

File reclamation runs in the main task only after XY, homing and the pen ramp
have settled, never inside the motor ISR or immediate emergency-stop handler.
Only `/plot.part`, `/plot.tmp`, `/plot.bin` and `/plot.json` are deleted. Wi-Fi,
pen calibration and other NVS settings are untouched. Failed removals remain
pending, are retried at one-second intervals, and are exposed in status/UI.

During execution the verified file is retained. After completion (including a
non-final part/color boundary), it is closed and queued for deletion. Same-boot
completion receipts remain in RAM, so duplicate start acknowledgements cannot
replay a drawing after its file is gone. The controller keeps artwork/history
and explicitly reuploads files when starting a new run. Expired partial transfers
can be reuploaded from offset zero without losing the waiting parent chain.

`plot_storage_total`, `plot_free`, `plot_cleanup_pending` and
`plot_cleanup_error` report storage state. An initialized filesystem has some
normal metadata overhead; free space need not equal its raw partition size.

Validation includes simulator completion/Stop/expiry/repeated-job checks and
`test/run_storage_native.py`, which compiles the real `src/plot_store.cpp`
against an in-memory filesystem and the real ArduinoJson dependency. It checks
completion receipts, multipart continuation after deletion, partial/ready expiry,
failed-commit cleanup, failed-erase retry, reboot scratch cleanup and clock wrap.
The ESP32 firmware also builds. Physical flash/GC behavior remains a supervised
hardware verification step after installing this firmware.
