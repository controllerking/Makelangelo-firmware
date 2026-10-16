# Drawy computer controller

This service hosts a private browser interface and prepares artwork on your
computer. With updated ESP32 firmware it uploads and verifies the complete plot,
then the device draws independently; the computer is only needed for monitoring
and remote controls afterward. Older firmware uses connection-dependent
streaming. Python 3.11+ is required. The only third-party dependency is
**numpy**, and it is optional: it enables the **Wavy line** image style
(`apt install python3-numpy`, or `pip install -r controller/requirements.txt`).
Without it the Wavy line option is disabled and everything else works.

Stored plots use 16 bytes/command, with a 1 MiB per-file cap and available-space
checks. The WROOM's existing 4 MiB layout reserves 1,408 KiB for SPIFFS, so no
partition change is required. The current 13,234-command example is 211,744 bytes
(about 207 KiB). See [stored plot operation](../docs/STORED_PLOTS.md).

## Start

From the repository root:

Create a private `.env` file using [.env.example](../.env.example) as a template:

```dotenv
DRAWY_ROBOT_HOST=drawy.local
DRAWY_ROBOT_PORT=9999
DRAWY_ROBOT_PAIRING_KEY=your-device-pairing-key
```

Use the robot's fixed LAN IP or hostname, not a URL. Keep `.env` out of Git and
restrict its permissions (`chmod 600 .env` on macOS/Linux). Do not use the Wi-Fi
setup-network password as the pairing key. Then start:

```sh
python3 -m controller.server
```

Open the private URL printed in the terminal. Keep the service/computer running during a drawing.

Robot linking is configured **only on the server**, read once at startup. The
server connects automatically and retries the same configured robot when it
is unavailable. There are no browser address/key fields, connect/disconnect
buttons, or corresponding HTTP control endpoints. Linking settings are never
returned by the status API and cannot be changed while running; edit `.env`
and restart the service. Automatic reconnection does **not** home, start a job,
or resume paused motion.

If configuring a numeric IP, reserve that address in your router's DHCP settings
so it does not change. The server does not discover or switch to other devices.

The default `.env` is resolved from the repository root, independent of the
working directory. `--env-file /absolute/path/to/.env` selects another file.
Process environment variables with these names override file values at startup
(useful for managed services). Supported file syntax is literal `KEY=value`,
optional matching outer quotes, blank lines, and full-line `#` comments; no
shell commands, interpolation or inline comments. Invalid/missing required
settings fail startup with a non-secret error. Simulation ignores `.env` and
cannot accidentally connect to the real robot.

The ignored `controller/data/connection.json` now stores only the persistent
session UUID for safe job recovery. Legacy host/key entries are removed when
the controller loads it; they are never used as fallback configuration.

To operate from a phone on the same LAN:

```sh
python3 -m controller.server --bind 0.0.0.0
```

Use the computer's LAN address instead of 127.0.0.1 in that private URL, keeping its access query. The controller requires the access link/cookie and checks POST origins. It is intended for a trusted local network, not Internet exposure.

## First use

With no limit switches, use the [manual four-corner calibration workflow](../docs/USER_CALIBRATION.md)
instead of switch homing. The web UI provides bounded belt jogs, sequential
corner captures, validation and persistent paper settings. Successful calibration
enables normal preset speeds; after a reboot, explicitly restore at the saved
top-left point before drawing. Captured paper settings override the old paper
origin fields. No physical position is restored automatically.

1. Upload the ESP32 firmware and commission motors/switches/geometry using [the hardware guide](../docs/ESP32_WIRING_AND_SETUP.md).
2. Configure the robot's Wi-Fi and obtain its pairing key using [wireless setup](../docs/WIRELESS_CONTROL.md).
3. Put the fixed robot hostname/IP, TCP port and pairing key in the server's private `.env` file and start the server. Linking happens automatically; the UI only shows connection status.
4. Home the robot. Enter measured paper left X and top Y in millimetres, choose paper size, margins, and speed.
5. Upload a PNG/JPG/WebP image or SVG, choose quality, and click **Convert & preview**. Review the pen paths, confirm paper/carriage clearance and a working pen lift, then start.
6. Pause drains planned motion, lifts the pen, and retains motors/position. Resume is explicit. Emergency stop immediately aborts, disables motors and invalidates position; reset and explicitly restore/home before drawing again.

The paper placement fields intentionally have no guessed machine coordinates. Y is positive upwards; paper below the anchors usually has negative Y. Speeds are mm/second.

## Supported artwork

PNG, JPG/JPEG and WebP files are decoded/resized in your browser, composited onto
white paper (including transparency), and sent as bounded grayscale pixels to
the local Python controller. Conversion runs off the event loop so the robot's
heartbeat stays responsive. No cloud service, image-library install, firmware
update, or original-image storage is needed. The prepared pen paths and job
metadata are saved locally as before. Original image whitespace/aspect ratio is
preserved when fitting the paper.

Choose **Wavy line** for photos (needs numpy): each row is one continuous line
whose swing grows with darkness, with a contrast stretch and a row pitch chosen
from the paper size so the job fits the robot's stored-plot budget (worst case
~54.6k of 65.5k commands). A photo needs tens of strokes instead of thousands,
so almost no pen lifts. The pen lifts only across near-white areas.

Choose **Crosshatch** (needs numpy) for the best shading: straight lines in up to four
directions, with more layers where the picture is darker. Short gaps are drawn
through and line ends joined, so it makes hundreds of strokes rather than
thousands, but it lays down a lot of line, so dark pictures take much longer than
Wavy line (hours at 10 mm/s on large paper); raise the feed once calibrated.

Choose **Shaded hatching** for illustrations, or if numpy is unavailable: monochrome horizontal strokes
approximate tonal shading, alternating direction to reduce travel. Choose
**Silhouette outlines** for logos/dark shapes: traces thresholded regions,
including holes. Its threshold control selects what counts as dark; this is
not a photo edge detector or AI sketch generator.

| Preset | Maximum image dimension | Nominal hatch spacing | Default speed |
| --- | --- | --- | --- |
| Fast | 256 px | 1.8 mm | 15 mm/s |
| Balanced | 512 px | 1.0 mm | 10 mm/s |
| Detailed | 768 px | 0.5 mm | 6 mm/s |

Presets also change outline simplification and shading sample size/budget.
Shading spacing adapts on large paper to keep the job below the existing
100,000-command limit, with a visible warning. Speed can be overridden after
choosing a preset. Changing artwork/settings clears the selected preview and
review confirmation; reconvert to update the paths and estimated time. Estimates
exclude the unknown first travel move and don't model acceleration precisely.

Image uploads are limited to 20 MB / 40 megapixels in the browser, and grayscale
requests to 768×768 pixels with exact validated byte counts. SVG remains limited
to 2 MB. Over-complex outlines and blank images return actionable errors.

**Connect and verify the servo before plotting images**: hatching/contours need
many pen lifts. Importing artwork does not bypass commissioning or start motion.

SVG path M/L/H/V/C/S/Q/T/A/Z, relative commands, lines, polylines, polygons, rectangles (including rounded corners), circles, ellipses, groups/transforms, and internal use references are supported. Bézier/arc paths are flattened on the computer. Geometry is aspect-fitted and centred inside the selected paper margins.

SVG draws outlines rather than filled regions. Convert SVG text and embedded
images to paths first (standalone raster files use the new image importer).
Expand clipping/masks and nested SVG viewports. CSS stylesheets must be inlined
into element attributes. Scripts are ignored; SVG is never inserted into the
browser DOM. Uploads, elements, nesting, and point counts are bounded.

Prepared drawings and history live in controller/data/ (Git-ignored). Immutable artwork is stored once; small state journals track progress. A restarted service pauses formerly-running streamed jobs. Multipart stored jobs reconcile the current part and continue automatically on the same device boot; explicitly paused jobs remain paused. A robot reboot invalidates resume and requires homing plus an explicitly restarted job.

## Hardware-free preview and tests

```sh
python3 -m controller.server --simulate
python3 -m unittest discover -s test -p 'test_*.py' -v
node test/test_web.mjs # optional browser-logic checks, if Node is installed
c++ -std=c++11 -Wall -Wextra -Werror -fsanitize=address,undefined test/esp32_logic.cpp -o /tmp/drawy-logic
/tmp/drawy-logic
```

Simulation uses its own controller/demo-data/ by default and clearly labels the UI. It does not operate real GPIO. A standalone simulator is also available with python3 -m controller.simulator.

The automated suite tests SVG and image conversion, quality density/time,
white images, holes, whitespace-preserving placement, malformed/oversized pixel
data, preparation concurrency, history, real TCP/HTTP flow against a simulated
robot, acknowledgement loss/retries, disconnect/reconnect, explicit pause/resume,
buffer saturation, stop, boot-change lockout, authentication and cross-origin
rejection. It does not replace physical Wi-Fi/motor/servo commissioning.

Quality controls, accuracy measurements and multipart transfer behavior are described in [quality and efficiency](../docs/QUALITY_AND_EFFICIENCY.md).

Four-pen image preparation, manual changes and recovery are described in [color drawings](../docs/COLOR_DRAWINGS.md).

Plot storage usage and cleanup status appear in the robot card. Finished/stopped files are reclaimed, partial uploads expire after two idle minutes, and unstarted verified files after ten. See [stored plots](../docs/STORED_PLOTS.md).
