#pragma once
#include "polargraph_math.h"

inline bool userCalibrationBounds(float width, float xmin, float ymin, float xmax, float ymax) {
  return isfinite(width) && width >= 100 && width <= 2000 &&
    isfinite(xmin) && isfinite(ymin) && isfinite(xmax) && isfinite(ymax) &&
    xmin >= 10 && xmax <= width-10 && xmax-xmin >= 10 &&
    ymin >= -2000 && ymax <= -40 && ymax-ymin >= 10;
}
inline bool userCalibrationContains(float x, float y, const float *bounds) {
  return isfinite(x) && isfinite(y) && x >= bounds[0] && x <= bounds[2] &&
    y >= bounds[1] && y <= bounds[3];
}
