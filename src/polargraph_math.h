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

// Sample straight interpolation in belt space against the requested XY chord.
inline bool polargraphLineDeviation(float left,float right,float top,
                                    const float *a,const float *b,float &deviation) {
  const float la=hypotf(a[0]-left,a[1]-top),lb=hypotf(b[0]-left,b[1]-top);
  const float ra=hypotf(a[0]-right,a[1]-top),rb=hypotf(b[0]-right,b[1]-top);
  deviation=0;
  for(int i=1;i<4;++i) {
    const float t=i*.25f;float x,y;
    if(!polargraphPosition(left,right,top,la+(lb-la)*t,ra+(rb-ra)*t,x,y))return false;
    deviation=fmaxf(deviation,hypotf(x-(a[0]+(b[0]-a[0])*t),y-(a[1]+(b[1]-a[1])*t)));
  }
  return true;
}
