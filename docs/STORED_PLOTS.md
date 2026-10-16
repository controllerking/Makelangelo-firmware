# Complete-plot upload and independent drawing

The computer still converts images/SVGs, fits artwork into captured paper
corners and checks bounds. On updated firmware, **Start** uploads every command
to ESP32 flash, validates the file, then explicitly starts it. No motor moves
during upload. After it starts, Wi-Fi loss, browser closure, computer sleep or
controller shutdown do not pause that stored drawing. Stay nearby and supervise
the machine; independent execution does not mean unattended operation is safe.

## Capacity and format

The existing ESP32 4 MiB partition table reserves 1,408 KiB for SPIFFS. Firmware
limits a plot to 1 MiB (65,536 commands), reserves filesystem headroom and checks
actual free space. Only one committed plot slot is kept; a replacement uploads
into a separate temporary file, so replacing a large old plot may need more
free space. Oversized jobs are rejected, never partially drawn. Use a simpler
conversion preset or split the artwork when necessary.

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
- Files survive normal board resets; physical position does not. A power loss,
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
