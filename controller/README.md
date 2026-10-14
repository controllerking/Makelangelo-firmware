# Drawy computer controller

This service hosts a private browser interface and streams drawing coordinates to the ESP32. Artwork preparation runs on your computer. Python 3.11+ is required; there are no third-party Python dependencies.

## Start

From the repository root:

```sh
python3 -m controller.server
```

Open the private URL printed in the terminal. Keep the service/computer running during a drawing.

To operate from a phone on the same LAN:

```sh
python3 -m controller.server --bind 0.0.0.0
```

Use the computer's LAN address instead of 127.0.0.1 in that private URL, keeping its access query. The controller requires the access link/cookie and checks POST origins. It is intended for a trusted local network, not Internet exposure.

## First use

1. Upload the ESP32 firmware and commission motors/switches/geometry using [the hardware guide](../docs/ESP32_WIRING_AND_SETUP.md).
2. Configure the robot's Wi-Fi and obtain its pairing key using [wireless setup](../docs/WIRELESS_CONTROL.md).
3. In the computer UI, enter drawy.local (or the robot's numeric IP) and the pairing key. These are saved locally with owner-only file permissions; the key is never returned by the status API.
4. Home the robot. Enter measured paper left X and top Y in millimetres, choose paper size, margins, and speed.
5. Upload a PNG/JPG/WebP image or SVG, choose quality, and click **Convert & preview**. Review the pen paths, confirm paper/carriage clearance and a working pen lift, then start.
6. Pause drains planned motion, lifts the pen, and retains motors/position. Resume is explicit. Stop cancels and requires resetting/re-homing the robot.

The paper placement fields intentionally have no guessed machine coordinates. Y is positive upwards; paper below the anchors usually has negative Y. Speeds are mm/second.

## Supported artwork

PNG, JPG/JPEG and WebP files are decoded/resized in your browser, composited onto
white paper (including transparency), and sent as bounded grayscale pixels to
the local Python controller. Conversion runs off the event loop so the robot's
heartbeat stays responsive. No cloud service, image-library install, firmware
update, or original-image storage is needed. The prepared pen paths and job
metadata are saved locally as before. Original image whitespace/aspect ratio is
preserved when fitting the paper.

Choose **Shaded hatching** for photos/illustrations: monochrome horizontal strokes
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
many pen lifts. The temporary manual-reference bounds and 2 mm/s firmware cap
still apply; importing artwork does not bypass commissioning or start motion.

SVG path M/L/H/V/C/S/Q/T/A/Z, relative commands, lines, polylines, polygons, rectangles (including rounded corners), circles, ellipses, groups/transforms, and internal use references are supported. Bézier/arc paths are flattened on the computer. Geometry is aspect-fitted and centred inside the selected paper margins.

SVG draws outlines rather than filled regions. Convert SVG text and embedded
images to paths first (standalone raster files use the new image importer).
Expand clipping/masks and nested SVG viewports. CSS stylesheets must be inlined
into element attributes. Scripts are ignored; SVG is never inserted into the
browser DOM. Uploads, elements, nesting, and point counts are bounded.

Prepared drawings and history live in controller/data/ (Git-ignored). Immutable artwork is stored once; small state journals track progress. A restarted service pauses any formerly-running job and requires reconnection/explicit resume. A robot reboot invalidates resume and requires homing plus an explicitly restarted job.

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
