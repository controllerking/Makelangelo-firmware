#pragma once
#include <math.h>

// Main-task-only position ramp; callers provide a bounded target and dt.
struct ServoMotion {
  float position = 0, velocity = 0;
  void reset(float value) { position=value; velocity=0; }
  void advance(float target, float dt, float maxSpeed, float acceleration) {
    if (dt<=0) return;
    if (dt>.02f) dt=.02f; // Never catch up with a large jump after a stalled loop.
    const float distance=target-position;
    const float braking=sqrtf(2*acceleration*fabsf(distance));
    const float speed=braking<maxSpeed ? braking : maxSpeed;
    const float desired=distance<0 ? -speed : speed;
    const float change=acceleration*dt;
    if (velocity<desired) velocity=fminf(desired,velocity+change);
    else velocity=fmaxf(desired,velocity-change);
    const float move=velocity*dt;
    if ((move*distance>=0 && fabsf(move)>=fabsf(distance)) || fabsf(distance)<.01f) {
      position=target; velocity=0;
    } else position+=move;
  }
};
