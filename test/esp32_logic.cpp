#include "../src/homing_axis.h"
#include "../src/polargraph_math.h"
#include "../src/user_calibration_math.h"
#include "../src/wire_protocol.h"
#include <cassert>
#include <cstdio>
#include <limits>

static void testGeometry() {
  float x, y;
  const float bounds[]={200,-450,420,-170};
  assert(userCalibrationBounds(644.525f,200,-450,420,-170));
  assert(!userCalibrationBounds(644.525f,200,-450,650,-170));
  assert(!userCalibrationBounds(644.525f,200,-450,420,0));
  assert(!userCalibrationBounds(NAN,200,-450,420,-170));
  assert(userCalibrationContains(200,-450,bounds));
  assert(!userCalibrationContains(199.99f,-450,bounds));
  assert(!userCalibrationContains(200,-450.01f,bounds));
  assert(polargraphPosition(0, 644.525f, 0, 381, 406.4f, x, y));
  assert(polargraphManualTarget(x+10, y-10, x, y));
  assert(!polargraphManualTarget(x+10.1f, y, x, y));
  assert(!polargraphManualTarget(x, y-10.1f, x, y));
  assert(!polargraphManualTarget(NAN, y, x, y));
  assert(polargraphManualTarget(x+76.2f, y-76.2f, x, y, 80));
  assert(!polargraphManualTarget(x+80.1f, y, x, y, 80));
  assert(!polargraphManualTarget(x, y, x, y, 81));
  assert(!polargraphManualTarget(x, y, x, y, NAN));
  assert(polargraphPosition(-400, 400, 100, 500, 500, x, y));
  assert(fabsf(x) < 0.001f && fabsf(y + 200) < 0.001f);
  assert(!polargraphPosition(0, 0, 0, 100, 100, x, y));
  assert(!polargraphPosition(0, 800, 0, 10, 10, x, y));
  assert(!polargraphPosition(0, 800, 0, 0, 800, x, y));
  assert(!polargraphPosition(0, 800, 0, NAN, 800, x, y));
  // Sub-mm changes must survive conversion; the inherited IK rounded mm first.
  assert(polargraphSteps(0, -100.125f, 0, 0, 80) == 8010);
  const float pi = 3.14159265359f;
  assert(fabsf(polargraphArcSweep(0, pi/2, false) - pi/2) < 0.0001f);
  assert(fabsf(polargraphArcSweep(0, -pi/2, true) + pi/2) < 0.0001f);
  assert(fabsf(polargraphArcSweep(0, 0, true) + 2*pi) < 0.0001f);
  assert(polargraphAngleInArc(0, -pi/4, pi/2));
  assert(!polargraphAngleInArc(pi, -pi/4, pi/2));
  assert(polargraphAngleInArc(0, pi/4, -pi/2));
  // Check independent steps/mm on a grid, including asymmetrical cable lengths.
  for (int px = -300; px <= 300; px += 37) {
    for (int py = -800; py <= -100; py += 43) {
      long l = polargraphSteps(px, py, -400, 0, 80);
      long r = polargraphSteps(px, py, 400, 0, 100);
      assert(polargraphPosition(-400, 400, 0, l/80.0f, r/100.0f, x, y));
      assert(fabsf(x-px) < 0.025f && fabsf(y-py) < 0.025f);
    }
  }
}

static void testCycle(bool initiallyActive) {
  HomingAxis axis(initiallyActive, 0, 100, 20);
  int pos = initiallyActive ? 0 : 30;
  int seekSteps = 0, backoffSteps = 0, latchSteps = 0;
  for (uint32_t now = 0; now < 3000 && axis.phase != HomingAxis::Done; now += 3) {
    auto phase = axis.phase;
    if (axis.tick(pos <= 0, now, phase == HomingAxis::Latch ? 5000 : 2500)) {
      if (phase == HomingAxis::Backoff) { ++pos; ++backoffSteps; }
      else { --pos; phase == HomingAxis::Seek ? ++seekSteps : ++latchSteps; }
    }
    assert(axis.phase != HomingAxis::Fault);
  }
  assert(axis.phase == HomingAxis::Done);
  assert(pos == 0 && backoffSteps == 20 && latchSteps == 20);
  assert(seekSteps == (initiallyActive ? 0 : 30));
  assert(!axis.tick(true, 4000, 2500));
}

static void testFaults() {
  HomingAxis stuckOpen(true, 0, 100, 20);
  for (uint32_t t = 0; t < 200; t += 3) stuckOpen.tick(true, t, 2500);
  assert(stuckOpen.phase == HomingAxis::Fault);
  HomingAxis stuckClosed(false, 0, 100, 20);
  for (uint32_t t = 0; t < 400; t += 3) stuckClosed.tick(false, t, 2500);
  assert(stuckClosed.phase == HomingAxis::Fault && stuckClosed.steps == 100);
  HomingAxis timeout(false, 0, 100, 20);
  assert(!timeout.tick(false, 2301, 2500));
  assert(timeout.phase == HomingAxis::Fault && timeout.steps == 0);
  HomingAxis brokenOnLatch(false, 0, 100, 20);
  brokenOnLatch.tick(true, 1, 2500);
  brokenOnLatch.tick(true, 12, 2500); // Seek → Backoff
  for (uint32_t t = 15; t < 400; t += 3) brokenOnLatch.tick(false, t, 2500);
  assert(brokenOnLatch.phase == HomingAxis::Fault);
  // Persistent bouncing never qualifies and eventually times out.
  HomingAxis bounce(false, 0, 100, 20);
  for (uint32_t t = 0; t < 3000; t += 3) bounce.tick((t/3)%2, t, 2500);
  assert(bounce.phase == HomingAxis::Fault);
  // On assertion, no extra pulse is emitted during debounce.
  HomingAxis debounce(false, 0, 100, 20);
  assert(!debounce.tick(true, 1, 2500));
  assert(!debounce.tick(true, 5, 2500));
  assert(debounce.steps == 0 && debounce.phase == HomingAxis::Seek);
  assert(!debounce.tick(true, 11, 2500));
  assert(debounce.phase == HomingAxis::Backoff);
  // A single transient release is not enough to pass the backoff phase.
  HomingAxis shortRelease(true, 0, 100, 2);
  shortRelease.tick(true, 0, 2500);
  shortRelease.tick(false, 3, 2500);
  shortRelease.tick(false, 6, 2500);
  assert(shortRelease.phase == HomingAxis::Fault);
  // Unsigned timestamp arithmetic remains valid across millis rollover.
  const uint32_t start = UINT32_MAX - 5;
  HomingAxis rollover(false, start, 100, 20);
  rollover.tick(true, start, 2500);
  rollover.tick(true, start + 10, 2500);
  assert(rollover.phase == HomingAxis::Backoff);
}

int main() {
  WireLedger wire;
  const uint32_t hash = WireLedger::fingerprint("move 1");
  assert(wire.inspect(1, hash) == WireLedger::New);
  assert(wire.inspect(2, hash) == WireLedger::OutOfOrder);
  wire.accept(hash);
  assert(wire.inspect(1, hash) == WireLedger::Duplicate);
  assert(wire.inspect(1, hash + 1) == WireLedger::Conflict);
  assert(wire.inspect(0, hash) == WireLedger::OutOfOrder);
  wire.finish(1);
  assert(wire.completed == 1);
  for (int i = 0; i < 40; ++i) wire.accept(hash);
  assert(wire.inspect(1, hash) == WireLedger::Stale);
  wire.reset();
  assert(wire.next == 1 && wire.completed == 0);
  testGeometry();
  testCycle(false);
  testCycle(true);
  testFaults();
  std::puts("PASS: geometry grid, sub-mm steps, homing/release/latch, switch faults, debounce and rollover.");
}
