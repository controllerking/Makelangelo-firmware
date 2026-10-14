# Drawy PCB hardware and circuit specification

Revision A design input · 2026-10-13

## 1. Scope and release status

This is the electrical handoff for designing a **carrier PCB** for the existing
classic ESP32-WROOM development board, two BIGTREETECH TMC2209 V1.3 plug-in
modules, two bipolar steppers, two NC home switches, and one pen-lift servo.
It is not a KiCad schematic, routed PCB, approved BOM, or fabrication release.

**Do not fabricate until the open items in section 12 are resolved.** In
particular, “ESP32-WROOM” identifies the radio module, not the development
board's header layout. No exact development-board footprint can be inferred
from that name or from the detected ESP32 chip/USB serial adapter.

Status terminology:

- **Existing:** specified by the project or implemented in firmware.
- **Bench-tested:** user confirmed motor operation; both VREF settings were
  adjusted to approximately 0.80 V; square commands completed without a reported
  firmware fault. This does not establish measured accuracy or circuit compliance.
- **Proposed:** carrier circuit additions below; not built or electrically tested.
- **TBD:** must be selected, measured, or checked before manufacturing.

The servo and switches were not connected at last physical commissioning.
No actual power supply/buck part number, switch model, connector model, ESP32
development-board schematic, or as-wired photograph has been recorded.

## 2. System components and architecture

| Reference | Qty | Component | Status / implementation |
| --- | --- | --- | --- |
| U1 | 1 | Classic ESP32-WROOM development board, USB serial programming | Existing; chip detected ESP32-D0WD-V3 rev 3.1, CP2102 USB adapter; exact board/headers TBD |
| U2, U3 | 2 | BIGTREETECH TMC2209 **V1.3** modules | Existing; left and right; STEP/DIR standalone, onboard VREF adjustment |
| M1, M2 | 2 | STEPPERONLINE 17HE08-1004S | Project motor: bipolar, 1.8°, 1 A/phase, 5 mm shaft; motor operation bench-tested |
| SV1 | 1 | MG90S pen-lift servo | Project selection; verify actual vendor/variant, connector, stall current and signal acceptance |
| SWL, SWR | 2 | Mechanical normally closed home switches | Existing design requirement; select contacts suitable for low-current 3.3 V sensing |
| PSU1 | 1 | Isolated, regulated 24 V DC, approximately 3 A external supply | Project target; actual model, tolerances, connector and protection TBD |
| U4 | 1 | 24 V to regulated 5 V buck, at least 3 A usable output under actual cooling | Proposed carrier module; actual installed buck unknown |
| S1 | 1 | Accessible mechanical DC power disconnect | Proposed required hardware provision; DC-rated at supply voltage/current |
| F1 | 1 | Replaceable input fuse | Proposed 3 A starting value, DC voltage rating at least 32 V; coordinate with wiring/inrush |
| U5 | 1 | SN74AHCT1G125DBVR, 5 V servo signal buffer | Proposed; SOT-23-5; discussed in section 7 |

The motor manufacturer's [product specifications](https://www.omc-stepperonline.com/5pcs-e-series-nema-17-bipolar-1-8deg-17ncm-24-07oz-in-1a-42x42x23mm-4-wires-5-17he08-1004s)
identify the specified motor and its winding/shaft ratings. Confirm labels on
the purchased motors; do not substitute winding colors for a continuity test.

```text
External isolated 24 V PSU
  + -> J1.1 -> F1 -> D1 reverse-polarity diode -> J2.1
                                                  external S1
                                              J2.2 -> VM24
                                                        +-> U2.VM -> M1 coils
                                                        +-> U3.VM -> M2 coils
                                                        +-> U4.VIN -> +5V_SERVO -> SV1
                                                                     +-> U5
                                                                     +-> JP1 -> U1.5V [optional]
  - -> J1.2 ---------------------------------------------------------- GND

U1 USB -> U1 onboard regulator -> +3V3_LOGIC -> U2/U3 VIO and pull-ups
U1 GPIOs -> STEP/DIR/EN_N on each driver
NC switches -> protected/filtered inputs -> GPIO32 / GPIO33
GPIO21 -> U5 non-inverting 3.3 V-to-5 V buffer -> servo signal
```

All grounds are electrically common. The servo and motor power returns must
not flow through a development-board ground pin or a thin logic return trace.
S1 opens the positive supply path to both drivers and the buck. USB may keep
U1 alive after S1 opens. This is **power removal, not a safety-rated E-stop**;
disabling torque can release a suspended load. Mechanical retention, captured
counterweights and physical travel stops remain required.

## 3. Rails, power entry, decoupling and USB isolation

| Net | Source | Loads / requirements |
| --- | --- | --- |
| VIN24_RAW | J1.1 | Fuse input only; polarity marked |
| VIN24_FUSED | F1 output | D1 anode |
| VIN24_PROTECTED | D1 cathode | J2.1; pre-switch protected supply |
| VM24 | J2.2 | U2.VM, U3.VM, U4.VIN; switched motor/buck supply |
| +5V_SERVO | U4.VOUT | Servo branch, U5 supply, optional JP1 feed to U1 |
| +3V3_LOGIC | U1.3V3 | Driver VIO, enable/microstep bias and switch pull-ups; never motor/servo power |
| GND | J1.2, all module grounds | One electrical net with controlled high-current return routing |

Proposed D1: series Schottky diode, at least 5 A / 60 V, selected package and
thermal copper rated for the actual current. Budget its forward drop and heat.
Do not confuse reverse-polarity protection with reverse-energy absorption.
U4's protection, if present, protects U4 only, not the driver branches.

Proposed bypass/bulk components (starting values, not validated loop design):

| Refs | Qty | Value / minimum rating | Connection / location |
| --- | --- | --- | --- |
| C1 | 1 | 470 µF, 50 V electrolytic, 105°C | VM24–GND near power distribution |
| C2, C3 | 2 | 100 µF, 50 V electrolytic, 105°C | One directly beside each driver VM socket |
| C4, C5 | 2 | 1 µF, 50 V X7R, 1210 starting footprint | One beside each driver VM socket; account for DC-bias capacitance loss |
| C6, C7 | 2 | 100 nF, 50 V X7R, 0805 | One beside each driver VM socket |
| C8 | 1 | 100 µF, 50 V electrolytic | U4 input; confirm acceptable added capacitance with chosen regulator |
| C9 | 1 | 470 µF, 10 V low-ESR electrolytic | +5V_SERVO–GND near J7; verify regulator stability/inrush |
| C10 | 1 | 10 µF, 10 V X7R, 0805 | U5 / servo branch supply |
| C11 | 1 | 100 nF, 10 V X7R, 0603 | Directly at U5 VCC/GND |
| C12 | 1 | 10 µF, 10 V X7R, 0805 | +3V3_LOGIC–GND near U1 breakout |
| C13, C14 | 2 | 100 nF, 10 V X7R, 0603 | One per driver VIO socket |

Keep module onboard capacitors and current-sense components; carrier capacitors
are additional. Long servo leads may need a further 220–470 µF / 10 V capacitor
at the gondola; qualify it with the chosen buck and servo load.

**24 V transient margin is limited.** The TMC2209 operating supply ceiling is
29 V; use margin below this, not the absolute-maximum rating as a target.
Measure VM during deceleration, abrupt disable, supply removal and powered
manual movement. A PSU may not absorb regenerated energy. Bulk capacitance alone
does not prove protection. Do not specify a “24 V TVS” by its name: its actual
clamp voltage at the relevant current can exceed the driver's rating. An active
brake/clamp, lower supply voltage, and/or qualified protection network may be
needed; this is an unresolved release item. See the
[TMC2209 electrical ratings and protection/layout guidance](https://www.analog.com/media/en/technical-documentation/data-sheets/tmc2209_datasheet_rev1.09.pdf).

One documented U4 candidate is the [Pololu D24V50F5](https://www.pololu.com/product/2851):
fixed 5 V, 6–38 V input, typical output capability up to 5 A subject to operating
conditions. It exposes VIN, VOUT, two GND connections and EN on a 2.54 mm grid;
unused EN is left open. Use the vendor drawing for the actual footprint and
verify thermal performance inside this frame. This is a **candidate**, not an
identification of the user's buck or a commitment to its footprint.

### JP1: development-board power selection

- JP1 is a removable, current-rated two-pin jumper between +5V_SERVO and the
  **verified 5 V input** of U1. Default: **OPEN / not fitted**.
- Bench/programming assembly: U1 powered by USB; U4 powers servo; common GND.
- Autonomous assembly: JP1 may be fitted only after U1's 5 V pin, regulator,
  reverse-current paths and allowed supply range have been checked.
- Without a verified onboard/external power-mux circuit: **remove JP1 before
  connecting USB**. Never assume simultaneous USB/external power is supported.
- Do not connect an external 3.3 V regulator in parallel with U1's 3.3 V output.
- Production USB/external auto-selection requires a reviewed power-mux revision;
  this specification does not silently assume one exists.

## 4. Firmware GPIO and driver signal netlist

Source of truth: [esp32_config.h](../src/boards/esp32_config.h) and
[esp32.h](../src/boards/esp32.h). Numbers below are **GPIO numbers, not header
positions and not ESP32 module pad numbers**. All digital connections here use
3.3 V logic. Driver enable is active LOW.

| ESP32 GPIO | MCU-side net | Series resistor | Driver-side net / destination | Bias at driver side |
| --- | --- | --- | --- | --- |
| 26 | L_STEP_MCU | R1 = 33 Ω | L_STEP -> U2.STEP | R7 = 100 kΩ to GND |
| 27 | L_DIR_MCU | R2 = 33 Ω | L_DIR -> U2.DIR | R8 = 100 kΩ to GND |
| 25 | L_EN_MCU | R3 = 100 Ω | L_EN_N -> U2.EN/ENN | R9 = 10 kΩ to +3V3_LOGIC |
| 18 | R_STEP_MCU | R4 = 33 Ω | R_STEP -> U3.STEP | R10 = 100 kΩ to GND |
| 19 | R_DIR_MCU | R5 = 33 Ω | R_DIR -> U3.DIR | R11 = 100 kΩ to GND |
| 23 | R_EN_MCU | R6 = 100 Ω | R_EN_N -> U3.EN/ENN | R12 = 10 kΩ to +3V3_LOGIC |
| 32 | LIMIT_L | R17 filter path, section 6 | J5 left NC switch | R15 pull-up |
| 33 | LIMIT_R | R18 filter path, section 6 | J6 right NC switch | R16 pull-up |
| 21 | SERVO_PWM_3V3 | U5 buffer, section 7 | J7.3 servo signal | R19 = 100 kΩ to GND on U5 input |

R1–R6 are proposed edge-damping/protection provisions; use 0603 resistors and
place STEP/DIR series resistors near U1. Pull-ups/downs define reset states when
the logic rail is valid; they do not constitute a safety-rated enable circuit.
Do not insert large RC capacitors in STEP/DIR paths. Firmware generates 2 µs
minimum commissioning pulses; qualify actual planner timing at the driver pins.

Every module GND pin connects to GND. U2/U3 VM connects only to VM24. Their VIO
(sometimes labeled VDD on a module) connects only to +3V3_LOGIC. Verify aliases
on the actual V1.3 board; **VIO is not the driver's VM or internal 5VOUT**.

No carrier GPIO is assigned to DIAG, INDEX, VREF, SPREAD or PDN/UART. GPIO16,
GPIO17 and GPIO22 can have labeled unconnected test pads for future firmware;
do not connect them to drivers in this revision. Leave boot/flash/USB UART pins
alone. No new status LED, buttons or E-stop GPIO are implemented by this PCB spec.

### Driver configuration and unused signals

| Signal, on BOTH drivers | Carrier treatment |
| --- | --- |
| MS1, MS2 | Individually connect to +3V3_LOGIC through four 0 Ω links: R13/R14 for U2 MS1/MS2, R21/R22 for U3 MS1/MS2; 16× microstep setting |
| SPREAD / mode | Use documented V1.3 module selection for StealthChop. If an actual SPREAD signal is exposed, select LOW; do not invent a header pin |
| PDN_UART | Standalone hold-current selection described below; no MCU/UART link |
| DIAG, INDEX | Leave electrically unconnected; optional labeled probe pads only, no ground ties |
| VREF | Module onboard potentiometer/reference network only; carrier test point to VREF plus nearby GND, no external rail/ADC tie |
| CLK, STDBY, 5VOUT, charge-pump / sense nodes | Retain manufacturer's module circuitry; not arbitrary carrier connections |

MS1/MS2 HIGH selects 16× in standalone mode. With a 20-tooth, 2 mm-pitch GT2
pulley and a 200-step/revolution motor, this project uses 80 STEP pulses/mm.
Do not change these links without changing the firmware scale.

**PDN/standstill is a deliberate design choice, not an unused-pin assumption.**
For the suspended machine, the proposed carrier selects PDN_UART HIGH to retain
run-current while stationary. The IC's standalone LOW setting enables automatic
standstill reduction. Provide independent 10 kΩ pull-up footprints R23/R24 to
VIO; fit only after checking the module's routing, existing pulls and solder
selectors. A hard LOW strap cannot be overridden with a resistor. The actual
module high level and hold torque/temperature must be measured. Do not enable
UART or program OTP as part of commissioning. IC behavior is specified in
[TMC2209 section 3.4](https://www.analog.com/media/en/technical-documentation/data-sheets/tmc2209_datasheet_rev1.09.pdf);
physical connections must be reconciled with the
[BTT V1.3 schematic](https://github.com/bigtreetech/BIGTREETECH-Stepper-Motor-Driver/blob/master/TMC2209/V1.3/Schematic/TMC2209%20V1.3-SCH.pdf)
and [module configuration guide](https://neo.bttwiki.com/en/docs/accessories-docs/tmc-driver/tmc-2209/).

**Module footprint gate:** use two keyed/orientation-marked driver sockets,
not a guessed “StepStick compatible” footprint. Confirm row spacing, pitch,
pin count, extra DIAG/INDEX/VREF pins, component/heatsink clearance, and the
top-view VM/VIO/EN orientation against the purchased V1.3 units. Record the CAD
symbol-to-socket pad map in the schematic before release. This document defines
electrical signal names; it deliberately does not invent physical pad numbers.

## 5. Motor connectors and current setting

Define J3 (LEFT MOTOR) and J4 (RIGHT MOTOR) as identical keyed four-pin
connectors, viewed/numbered according to the chosen manufacturer drawing:

| Connector pin | J3 net / U2 output | J4 net / U3 output | Motor marking |
| --- | --- | --- | --- |
| 1 | L_A1 | R_A1 | A+ |
| 2 | L_A2 | R_A2 | A− |
| 3 | L_B1 | R_B1 | B+ |
| 4 | L_B2 | R_B2 | B− |

Pin order is a **new carrier harness contract**, not a claim about an existing
motor cable plug. Verify each winding by continuity and crimp the harness to
match. If direction is wrong, power off and swap one complete coil's ends.
Positive D0 jog / DIR LOW must pay out the gondola-side belt. Never hot-plug a
motor or disconnect a coil with VM energized; let stored energy discharge.

Use contacts rated at least 2 A per circuit and 30 V DC under the selected
wire/temperature conditions, with locking and strain relief. Proposed 22 AWG
stranded motor leads; confirm voltage drop and connector compatibility. Twist
each winding pair, and keep motor cables away from switch and antenna wiring.

For genuine BTT V1.3 0.11 Ω-sense modules, the manufacturer's relationship is
I_RMS ≈ VREF/√2 and I_peak ≈ VREF in amperes/volts. The bench starting point
**VREF = 0.80 V per driver** therefore corresponds to about 0.57 A RMS / 0.80 A
peak; it is not firmware-set current and is not a finalized thermal setting.
See [BTT's current calculation](https://neo.bttwiki.com/en/docs/accessories-docs/tmc-driver/tmc-2209/).
Do not replace the module's sense resistors or potentiometer on the carrier.
Leave VREF probe access clear of heatsinks. Measure VREF-to-GND with supplies
on, no movement; power off between mechanical adjustments. Qualify idle and
motion temperatures at final current inside the enclosure.

## 6. Two NC limit-switch input circuits

J5 LEFT HOME and J6 RIGHT HOME: keyed two-pin low-current connectors.
Pin 1 = SWITCH_RAW; pin 2 = GND. At the switch, NC -> pin 1 and COM -> pin 2;
NO is unused. No 5 V or 24 V is present on these connectors.

Duplicate this proposed circuit, once per axis:

```text
+3V3_LOGIC -- 4.7k pull-up --+-- J5.1/J6.1 SWITCH_RAW -- switch NC
                           |                           switch COM -- GND
                           +-- 1k series --+-- GPIO32/GPIO33 (LIMIT_L/R)
                                          |
                                        100nF
                                          |
                                         GND
J5.2/J6.2 -------------------------------- GND
```

- R15/R16 = 4.7 kΩ pull-ups; R17/R18 = 1 kΩ series; C15/C16 = 100 nF,
  10 V X7R; 0603 footprints. Put filter components near the MCU.
- Released intact NC loop = LOW. Actuated/open wire/unplugged = HIGH.
  A short to GND is **not** detected as a disconnected switch; homing transition
  and travel checks are still required. These are references, not safety limits.
- Current through a closed contact is approximately 0.7 mA. Choose switch
  contact material/minimum wetting current accordingly; model is TBD.
- Approximate RC rise time constant is (4.7k + 1k) × 100nF = 0.57 ms;
  electrical filtering supplements the firmware's 10 ms stability requirement.
- Add D2/D3 optional connector-side ESD shunt footprints (to GND, short return).
  Exact device/footprint and clamp coordination with the MCU/series resistor are
  TBD, not a verified surge rating. External field wiring needs an ESD review;
  RC alone is not ESD protection or tolerance of accidental 24 V connection.
- Use a twisted signal/GND pair for each harness. Determine maximum cable
  length and noise immunity by testing with both motors and servo operating.

## 7. Servo signal and power circuit

J7 SERVO: pin 1 GND, pin 2 +5V_SERVO, pin 3 SERVO_SIGNAL_5V. This matches the
common GND/power/signal ordering, but verify the actual servo wire/plug and
view direction. Use a shrouded/keyed adapter or a clearly marked three-pin
2.54 mm header; do not assume an ordinary servo plug prevents reverse insertion.
Contacts and wires must carry the measured peak/stall current, not just idle.

Proposed buffer U5 = SN74AHCT1G125DBVR, SOT-23-5:

| U5 pin | Name | Net / connection |
| --- | --- | --- |
| 1 | /OE | GND (enabled) |
| 2 | A | GPIO21 / SERVO_PWM_3V3, with R19 100 kΩ to GND |
| 3 | GND | GND |
| 4 | Y | R20 100 Ω series -> J7.3 SERVO_SIGNAL_5V |
| 5 | VCC | +5V_SERVO; C11 100 nF directly to pin 3 |

This non-inverting AHCT buffer is proposed to avoid relying on an unspecified
MG90S variant accepting a 3.3 V signal. Its specified supply is 4.5–5.5 V and
HIGH input threshold is 2 V; see the [TI datasheet](https://www.ti.com/lit/ds/symlink/sn74ahct1g125.pdf).
Qualify power sequencing and input/output leakage with USB-only, buck-only and
servo-unplugged cases. Do not substitute a 5 V HC buffer without checking its
input threshold. Optional JP2 bypass is **DNP/open** if U5 is fitted; never
parallel GPIO21 directly with U5's output. A direct 3.3 V bypass assembly is
allowed only after actual servo acceptance is demonstrated, with U5 omitted.

Firmware: 50 Hz PWM, nominal 1000–2000 µs allowed pulse range; initial pen-up
90°, pen-down 40°. Mechanism clearance and actual angles require calibration.
No servo position feedback exists. Firmware reports the commanded angle, not
proof the pen moved. Set buck voltage before attaching the servo. Add an
optional servo-branch fuse F2 footprint; its rating/time curve must follow the
measured stall/inrush current, wire gauge and supply protection (TBD).

## 8. Remaining connector and test-point definitions

| Ref | Pins / assignment | Requirements |
| --- | --- | --- |
| J1 | 1 VIN24_RAW, 2 GND | Keyed or polarity-marked input, at least 3 A continuous / 30 V DC; proposed 5.08 mm terminal family, exact part TBD |
| J2 | 1 VIN24_PROTECTED, 2 VM24 | Series disconnect harness to S1; same DC current rating as J1; **not an MCU input**; no bypass link in normal assembly |
| J3/J4 | A+, A−, B+, B− per section 5 | Keyed four-pin motor connectors, exact family/mating contacts TBD |
| J5/J6 | 1 NC signal, 2 GND | Keyed two-pin switch connectors, exact family/mates TBD |
| J7 | 1 GND, 2 +5V_SERVO, 3 signal | Servo connector per section 7 |
| J8/J9 | U1 development-board socket rows | Actual pad numbers/count/row spacing TBD; connect by GPIO/supply labels, never a generic pin-count assumption |
| U2/U3 sockets | Named signals per section 4 | Vendor-reconciled pad map, orientation keys and clearance mandatory |
| U4 pads/socket | VIN=VM24, VOUT=+5V_SERVO, all GND=GND | Module pin order and mounting drawing TBD after selection |

Provide labeled, probe-accessible test points: VM24, +5V_SERVO, +3V3_LOGIC, at
least three GND points, L/R STEP, DIR, EN_N, LIMIT_L/R, SERVO_PWM_3V3,
SERVO_SIGNAL_5V, and L/R VREF. Put a GND point beside each VREF point. Do not
expose power test points where a sliding probe easily bridges them to GPIO.
DIAG/INDEX optional pads remain NC. Test pads are not user-accessory connectors.

Every connector BOM entry must eventually include manufacturer part number,
mating housing/contact, wire gauge, tool/crimp requirements, rated current,
CAD symbol/footprint revision and pin-1 view. “JST” or “2.54 mm” alone is not a
complete purchasing/footprint specification. Print pin names on the carrier and
document both mating views; use square pads/pin-1 markings consistently.

## 9. PCB/layout and assembly rules

- Proposed starting stackup: 2-layer FR-4, 1.6 mm, 2 oz outer copper with a
  substantially uninterrupted ground plane. Four layers are an option if RF,
  return routing or thermal constraints cannot be met. Final dimensions TBD.
- Keep high-current copper branches short/wide; start with pours or >=1.5 mm
  external traces for 3 A trunks and >=1 mm for motor phases, then calculate
  temperature rise/voltage drop for actual stackup, lengths and enclosure.
  These are placement targets, not guaranteed ampacity. Avoid single-via necks.
- Place input protection/power connectors together; driver capacitors close to
  VM/GND socket pads; keep driver-to-motor loops compact. Route servo return
  directly to its bulk/buck ground region, not through U1/switch return paths.
- Route STEP/DIR over continuous ground, away from phase outputs and buck
  switching nodes. Keep filtered switch nodes short and away from antennas.
- Target >=0.5 mm copper clearance between 24 V and low-voltage nets where
  practical; use selected fabricator rules elsewhere. This is a low-voltage DC
  carrier, **not** a mains-isolation layout. Mains PSU remains external.
- Place the ESP32 antenna at/outside a carrier edge, with the module vendor's
  required all-layer keepout; no copper, traces, vias, drivers, heatsinks or
  mounting metal in that region. Also account for the frame, backing and wires.
  Use the exact module's [Espressif hardware guidance](https://documentation.espressif.com/esp-hardware-design-guidelines/en/latest/esp32/index.html),
  not an ESP32-S2/S3/C3 footprint or antenna rule substituted blindly.
- Leave USB, BOOT/EN buttons, current pots, heatsinks and module-removal access
  unobstructed. Ensure driver heat cannot soften nearby printed parts or heat
  paper/wood. Check connector extraction and harness bend radii in the frame.
- Electrically clear mounting holes and spacers; no screw can touch power
  copper or a module underside. Board size/hole coordinates/standoff height TBD.
- Mark module orientation, voltage rails, polarity, connector pins, board
  revision, and “DISCONNECT POWER BEFORE MOTOR CONNECTIONS” on silkscreen.

## 10. BOM completion checklist

U1–U5, PSU1, M1/M2, SV1, SWL/SWR and S1 are listed in section 2.
Capacitors C1–C16 and control/filter resistors are defined above. Complete the
following assembly list without quietly populating optional alternatives:

| Group | Proposed values / assembly |
| --- | --- |
| R1/R2/R4/R5 | 33 Ω, 0603, 1%, 0.1 W or better |
| R3/R6/R20 | 100 Ω, same class |
| R7/R8/R10/R11/R19 | 100 kΩ, same class |
| R9/R12 | 10 kΩ enable pull-ups, same class |
| R13/R14/R21/R22 | 0 Ω microstep links, 0603 |
| R15/R16 | 4.7 kΩ switch pull-ups, 0603 |
| R17/R18 | 1 kΩ switch series resistors, 0603 |
| R23/R24 | 10 kΩ PDN pull-ups, **conditional** on verified module configuration |
| D1 | >=5 A / 60 V Schottky, exact MPN/footprint/thermal rating TBD |
| D2/D3 | Switch ESD parts, exact type/footprint TBD; do not claim qualified protection while DNP |
| F1 | Input fuse + holder; provisional 3 A, >=32 V DC; exact part/curve TBD |
| F2 | Optional servo branch fuse; rating/footprint TBD from measured load |
| JP1 | U1 external-5 V link, open by default; current-rated jumper/header |
| JP2 | Servo-buffer bypass pads, open/DNP by default |
| Sockets / J1–J9 | Complete per section 8 including mating hardware |

Reserve unused reference numbers rather than renumbering schematics/assembly
notes casually. Passive footprints are proposals; select exact capacitor cases,
voltage derating, ESR/ripple ratings and approved manufacturers in the CAD BOM.
For F2 omission, use an explicit rated assembly link instead of leaving the
servo supply accidentally open; document which assembly variant was built.

## 11. Electrical and functional acceptance before release

1. ERC/DRC: verify every named net, socket pad map, connector view, power flag,
   NC annotation, pin-1 orientation and assembly option. Print a 1:1 footprint
   check and fit actual modules/connectors before ordering.
2. Unpowered: inspect polarity, diode direction, continuity, fuse/switch path,
   and absence of shorts between VM24, 5 V, 3.3 V and GND.
3. Current-limited supply, modules/motors/servo initially removed: verify reverse
   polarity protection and 5 V rail; check JP1 open isolates external 5 V from
   U1's 5 V pad. Do not use a destructive reversal test on installed modules.
4. Fit U1 with no motors: scope STEP low and EN_N high through power-up, reset,
   flashing, bootloader, USB removal and brownout. Test USB-only, 24 V-only and
   permitted supply transitions for backfeed. If VIO vanishes while VM remains,
   verify driver behavior; the pull-ups alone cannot prove safety in that case.
5. Switch tests: both NC states, press/release, harness removal, chatter and
   cable noise while motor/servo loads switch. Open wire must read HIGH. Record
   filtered waveforms and repeatability, not just digital status.
6. Fit drivers with outputs disabled; verify VIO, MS1/MS2, PDN selection, VREF
   and VM transient levels. Confirm heatsink isolation and current adjustment.
7. Fit unloaded motors and verify small jogs, payout direction, pulse timing,
   no reset steps and idle torque. Check coils/driver temperatures over sustained
   worst-case operation inside the closed frame.
8. Fit servo unloaded: test pulse range, brownout/peak current, 5 V at the
   far-end connector and calibrated pen clearance. An electronic pen-up command
   without a connected/working servo is not physical pen lift.
9. On assembled mechanics, verify homing transitions/travel bounds before
   enabling WALL_HOMING_CONFIRMED. Test disconnect/pause/reset/power loss,
   captured counterweights and manual recovery. No unattended operation yet.
10. Record scope captures, rail extrema, thermal results, measured currents,
    actual BOM/board revision and release sign-off with the CAD project.

## 12. Open items that block fabrication or production release

| Item | Required resolution |
| --- | --- |
| U1 identity | Photos/markings, vendor schematic, full header pin map, row spacing, pin count, USB/5 V isolation and regulator current capability |
| U2/U3 physical mapping | Reconcile actual BTT V1.3 header/extra pins, selectors, pulls and socket drawing; no inferred pad numbering |
| Power design | Select PSU/buck, D1/fuses/connectors; measure inrush/stall/load; resolve VM regeneration and USB coexistence |
| PDN current mode | Verify actual module circuit, intended HIGH level, hold torque and final idle temperature |
| Servo | Actual variant, peak current, connector polarity, buffered signal operation and pen-up clearance |
| Switches | Exact low-current-compatible models, cable length, ESD parts and noise test results |
| Mechanics | PCB outline/hole locations, standoffs, antenna/heatsink clearance, cable exits and enclosure thermal constraints |
| Safety | Independent accessible DC disconnect, retained loads/counterweights, collision stops; assess whether stronger safety circuitry is required |
| Manufacturing outputs | Native schematic/PCB, reviewed netlist, full MPN BOM/mating BOM, assembly variants, Gerbers/drill, fabrication/assembly drawings and ERC/DRC reports |

For a later board using **bare ESP32-WROOM and TMC2209 ICs**, this carrier design
is not sufficient: add the exact radio module power/reset/boot/programming
reference design, USB implementation/power mux, TMC charge-pump/5VOUT/sense
network, exposed-pad thermal layout and a new compliance/thermal review. Do not
copy this module-level pin table as an IC pad-level schematic.

Related operational documents: [wiring and setup](ESP32_WIRING_AND_SETUP.md),
[manual commissioning](MANUAL_COMMISSIONING.md), and
[wireless protocol](WIRELESS_CONTROL.md).
