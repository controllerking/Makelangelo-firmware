#include <assert.h>
#include <math.h>
#include "../src/servo_motion.h"

int main() {
  ServoMotion ramp;
  ramp.reset(90);
  for (int i=0;i<2500;++i) {
    const float before=ramp.position, velocity=ramp.velocity;
    ramp.advance(40,.001f,35,100);
    assert(ramp.position<=before && ramp.position>=40);
    assert(fabsf(ramp.position-before)<=.0351f);
    assert(fabsf(ramp.velocity)<=35.001f);
    if (ramp.position>40.01f) assert(fabsf(ramp.velocity-velocity)<=.1001f);
  }
  assert(ramp.position==40 && ramp.velocity==0);
  // Reversing a partially completed stroke must not jump the output.
  for (int i=0;i<400;++i) ramp.advance(90,.001f,35,100);
  for (int i=0;i<2500;++i) {
    const float before=ramp.position;
    ramp.advance(40,.001f,35,100);
    assert(fabsf(ramp.position-before)<=.0351f);
  }
  assert(ramp.position==40 && ramp.velocity==0);
  // A delayed main loop cannot turn elapsed time into a sudden large jump.
  ramp.reset(90);
  ramp.advance(40,5,35,100);
  assert(ramp.position>89.9f);
}
