# Four-pen color drawings — 2026-10-16

Color mode uses a manual red, green, blue and black pen change workflow. It
requires the multipart ESP32 firmware (`stored_plot_api=2`) described in
[quality and efficiency](QUALITY_AND_EFFICIENCY.md). No additional firmware
change is needed beyond that build. This feature has not been deployed or
physically commissioned.

## Prepare and draw

1. Upload a PNG, JPG or WebP image and select **Red, green, blue & black** under
   Drawing pens. Monochrome remains the default. SVG and generated patterns
   currently use monochrome; rasterize colored SVG artwork before color import.
2. Choose spatial dithering for photographs or disable it for flat-color logos.
   The image is mapped to four pen colors plus unmarked white paper. Color mode
   uses hatching, or silhouette outlines if selected; the monochrome wave and
   crosshatch converters remain available in monochrome mode.
3. Review the color toolpath and stage summary. All colors share the original
   full image frame, margins, paper transform and coordinate reference, including
   whitespace. Unused pens are omitted. The stage order is red, green, blue,
   black; black is last. Time estimates exclude manual pen-change waiting.
4. Start the reviewed job. The controller first prompts for the initial pen and
   sends no drawing commands until **Confirm pen & draw stage** is pressed.
5. After a color finishes, XY motion drains and the pen lifts. The device holds
   position at the last endpoint. Swap pens without shifting the gondola or
   paper, confirm the requested color at the same tip depth, then continue.
   There is no automatic parking move, motor release, homing or calibration
   reset at a pen change.

Use matching pen bodies and a repeatable insertion stop. The tip must return to
the same XY point and depth, with the same pen-up clearance and pen-down contact.
Do not move the suspended carriage to reach the pen. If a swap displaces it or
changes the paper, Stop and restore/recalibrate before starting again. Let wet
ink dry as needed before confirming the next stage.

## Palette and fidelity

RGB pens are a limited physical palette, rather than three additive image
channels. The converter assigns each pixel to one pen or white and optionally
uses serpentine error diffusion to mix neighboring marks spatially. Neutral
source regions use black and white, avoiding a colored cast in grayscale areas. It does not
stack full red/green/blue channel passes over every pixel. Yellow, cyan, magenta
and pastel tones are approximations; exact reproduction is not promised.

Preview swatches approximate typical red/green/blue/black inks. Actual ink hue,
paper, line width and overlapping strokes affect the result. Start with a small
four-color sample and check registration before a long drawing. Conversion is
local and needs no new Python dependencies; original image files are not saved.

## Recovery and controls

Each color can span multiple verified transfers, but no transfer contains more
than one color. Transfers inside the confirmed color continue automatically.
The device's parent chain spans the entire job, so other manual/streamed motion
cannot take over while it waits for the next color.

If the network/controller disconnects, the ESP32 completes the current part,
lifts and waits. Reconnection may continue the already-confirmed color. It cannot
authorize another color: the pending pen change is saved durably and survives a
controller restart. Explicitly paused jobs also remain paused. A board reboot,
Stop, fault, changed calibration or unknown position blocks continuation.

The confirmation API is `/api/pen-change` with the active job `id`, current
`plot_run` as `run`, zero-based `stage` and `confirmed: true`. Stale run/stage
requests are rejected. Confirmation requires unchanged calibration, the same
boot, finished motion and a lifted pen. No pen-change request bypasses a fault
or resumes a paused robot.

## Verification

Tests cover RGB payload/resolution limits, palette/white separation, shared-frame
placement, safe stage endings, confirmation before every color, persistence of
unconfirmed colors across controller restarts, stale confirmations, reboot
lockout, old-firmware rejection and automatic multipart execution within one
color. Browser checks verify RGB upload, colored path rendering logic and a fresh
checkbox confirmation for each stage. Physical pen changes/registration have
not been tested on the real plotter.
