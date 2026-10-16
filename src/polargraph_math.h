#pragma once
#include <math.h>

// Anchor coordinates: (left, top), (right, top), Y positive upwards.
inline bool polargraphPosition(float left, float right, float top,
                               float l, float r, float &x, float &y) {
  const float width = right - left;
  if (!isfinite(width) || width <= 0 || !isfinite(top) ||
      !isfinite(l) || !isfinite(r) || l <= 0 || r <= 0) return false;
  const float dx = (l*l + width*width - r*r) / (2*width);
  const float dy2 = l*l - dx*dx;
  if (!isfinite(dy2) || dy2 < 0) return false;
  x = left + dx;
  y = top - sqrtf(dy2);
  return isfinite(x) && isfinite(y);
}

inline long polargraphSteps(float x, float y, float anchorX,
                            float anchorY, float stepsPerMm) {
  const float dx = x - anchorX, dy = y - anchorY;
  return lroundf(sqrtf(dx*dx + dy*dy) * stepsPerMm);
}

inline float polargraphArcSweep(float start, float end, bool clockwise) {
  const float turn = 6.28318530718f;
  float sweep = end - start;
  if (clockwise) { while (sweep >= 0) sweep -= turn; }
  else { while (sweep <= 0) sweep += turn; }
  return sweep;
}

inline bool polargraphAngleInArc(float angle, float start, float sweep) {
  const float turn = 6.28318530718f;
  float offset = sweep < 0 ? start - angle : angle - start;
  while (offset < 0) offset += turn;
  while (offset >= turn) offset -= turn;
  return offset <= fabsf(sweep) + 0.00001f;
}
