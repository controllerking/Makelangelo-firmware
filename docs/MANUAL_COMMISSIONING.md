# Temporary manual-reference commissioning

USB only, with the wireless controller disconnected, motors stationary, and
20-tooth GT2 pulleys at 16 microsteps (80 steps/mm):

`M665 W644.525 L381 R406.4 C1`

Optional `S` selects the commissioning half-extent in mm (default 10, hard
maximum 80). Only expand after checking paper clearance; the user's 3-inch
square uses `S80` and 76.2 mm sides to the right and below the reference.

W is horizontal pulley spacing; L/R are the measured free belt spans in mm.
This is an approximate point-attachment model: separated gondola attachments,
pulley tangency, sag and measurement error affect accuracy. Verify positive
motor motion pays out both belts before attempting a drawing. Support the
gondola during any reset/flash because drivers become disabled.

The command records position without moving, engages drivers, and creates a
RAM-only reference. M114 identifies it as MANUAL, and wireless status includes
`reference: manual`. The legacy `homed` boolean means position established;
it does not imply switches were used. The reference permits only targets within
the selected extent on each side of initial XY and caps line/arc feed at 2 mm/s.
G28 is blocked until reset. G92, D0, M18, configuration reload/change, stop,
and reset invalidate the reference. Invalidation restores prior XY bounds;
M500 cannot persist a live manual reference. Switch calibration is unchanged.

With no servo, pause/stop cannot lift the physical pen. Use only tiny
continuous-line tests, supervise with the power switch accessible, and do not
use this mode for normal unattended artwork. No automatic manual reference
is established after a reboot.
