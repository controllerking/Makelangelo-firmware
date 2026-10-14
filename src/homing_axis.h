#pragma once
#include <stdint.h>

// Platform-independent per-axis reference cycle; step generation is external.
class HomingAxis {
 public:
  enum Phase { Seek, Backoff, Latch, Done, Fault };
  Phase phase = Seek;
  uint32_t steps = 0;
  uint32_t maxSeek;
  uint32_t backoff;
  uint32_t phaseStart;
  uint32_t stableSince;
  bool lastActive;
  bool releaseSeen = false;

  HomingAxis(bool active, uint32_t now, uint32_t maxSteps, uint32_t backoffSteps)
    : phase(active ? Backoff : Seek), maxSeek(maxSteps), backoff(backoffSteps),
      phaseStart(now), stableSince(now), lastActive(active) {}

  // Called before every potential step. Return true to request one step.
  bool tick(bool active, uint32_t now, uint32_t intervalUs) {
    if (phase == Done || phase == Fault) return false;
    if (active != lastActive) {
      stableSince = now;
      lastActive = active;
    }
    const bool stable = uint32_t(now - stableSince) >= 10;
    const uint32_t bound = phase == Seek ? maxSeek : backoff * 2;
    if (uint32_t(now - phaseStart) > bound * (intervalUs / 1000 + 1) + 2000) {
      phase = Fault;
      return false;
    }
    if (phase == Backoff) {
      if (!active && stable) releaseSeen = true;
      if (steps >= backoff) {
        if (active || !stable || !releaseSeen) { phase = Fault; return false; }
        transition(Latch, now);
        return false;
      }
    } else if (active) {
      // Stop pulses immediately; require a stable assertion before advancing.
      if (stable) transition(phase == Seek ? Backoff : Done, now);
      return false;
    }
    if (steps >= bound) { phase = Fault; return false; }
    ++steps;
    return true;
  }
 private:
  void transition(Phase next, uint32_t now) {
    phase = next;
    steps = 0;
    phaseStart = now;
  }
};
