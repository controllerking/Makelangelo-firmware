# Project Brief — ESP32 Wall Polargraph

## Goal

Create a quiet, compact, visually clean wall-mounted kinetic drawing artwork that a nontechnical owner can operate. Two independently driven belts/cables suspend a pen gondola while visible counterweights move vertically at the outer edges. It must produce detailed generative art, lift the pen electronically, eventually offer Wi-Fi control, and recover safely after manual movement while unpowered.

## Frame and paper

| Item | Current specification | Status |
| --- | --- | --- |
| Frame | 32 in W × 40 in H portrait shadow-box | Target |
| Structure | nominal 1×2 rear frame (about 0.75 × 1.5 in), 1/4 in sanded plywood backing, bevelled/chamfered select-pine trim | Proposed |
| Internal depth | about 1.5 in before backing, wall clearance, and mounting | Verify |
| Bracing | about three horizontal braces | Clear motors/electronics |
| Wall mount | French cleat + anti-lift retention | Required |
| Paper | 18 × 24 in portrait | Primary preset |
| Drawing region | 16 × 22 in | Not mechanically validated |

Use low-profile removable paper clips outside the gondola collision envelope. Motors are hidden behind the drawing face; electronics are concealed. Future presets: Letter, 11×14, 11×17, 12×18, 16×20, 18×24, A4, A3, and possibly A2.

## Motion hardware

| Part | Current choice | Important notes |
| --- | --- | --- |
| Motors | 2 × STEPPERONLINE 17HE08-1004S pancake NEMA 17 | 42×42×23 mm, 1.8°, about 1 A/phase, 5 mm shaft, about 0.17 N·m holding torque |
| Drivers | 2 × BIGTREETECH TMC2209 | Start with STEP/DIR; UART is later work |
| Drive | 20T GT2 5 mm-bore pulleys; 6 mm GT2 belt | Belt routing/idlers/tensioning unresolved |
| Gondola | 100–170 g target; use 150 g only preliminarily | Weigh built assembly |
| Counterweights | one per side | Mass, travel, retention, hard stops unresolved |

A 20T GT2 pulley moves 40 mm/revolution. With 200 full steps/rev and 16× microsteps: 3,200 microsteps/rev = **80 microsteps/mm**. That is command resolution, not drawing accuracy. Validate dynamic torque, tension, pulley runout, compliance, and cable drag; holding torque is not running torque.

## Pen lift and power

Use an MG90S 180° metal-gear micro servo with printed cam/lever, a compliant spring pressure mechanism, and a lightweight servo lead that cannot drag or foul belts. Pen-up must clear paper by 3–5 mm. Calibrate actual pulse/angle values on the assembled gondola.

Power is 24 V DC, about 3 A, to TMC2209 VM plus a 24-to-5 V, about 3 A buck for servo and ESP32 where board-compatible. Use fuse, accessible switch, rated connectors, strain relief, and common logic ground. Never power servo from 3.3 V or apply 24 V to ESP32 pins.

The owner confirmed ESP32-WROOM, with nothing wired yet. The selected pin map is in [ESP32 wiring and setup](ESP32_WIRING_AND_SETUP.md). Potential later I/O: start/pause, status LED, emergency-stop input, Wi-Fi/web control.

## Recovery and homing requirement

Two normally closed mechanical switches at the lower counterweight limits are the references. Every boot begins **position unknown**: retract pen; keep motor outputs inactive; inspect switches; independently seek references with bounded travel; back off; slow re-latch; establish belt/cable lengths and Cartesian position; only then permit drawing. Require debounce, expected state transitions, timeout/maximum-step bounds, abort, and a terminal fault state.

The supplied handoff ends mid-sentence after “That axis backs”; no unseen continuation was assumed. The safety sequence above is a proposed acceptance requirement.

## Decisions and open measurements

- Reuse the inherited polargraph planner/math only after ESP32 hardware assumptions are replaced and tested.
- ESP32-WROOM is selected; the implemented target is the classic ESP32 dev module.
- Wi-Fi setup/TCP control, computer-side paper presets, and configurable automatic homing are implemented. TMC2209 UART remains future work.
- Persisted motor steps never replace physical homing after power loss.
- Keep a physical escape/power cut-off independent of software.
- Measure final belt route/wrap, counterweight travel/mass, motor centers relative to paper, collision envelope, gondola mass, cable drag, motor temperature, switch behavior, and servo peak current before finalizing firmware or frame.
