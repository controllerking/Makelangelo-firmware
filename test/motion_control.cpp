#include <assert.h>
#include "../src/motion_control.h"
int main() {
  assert(motionScaledInterval(1000,1000)==1000);
  assert(motionScaledInterval(1000,500)==2000);
  assert(motionScaledInterval(1000,100)==10000);
  assert(motionScaledInterval(1000,0)==10000);
  assert(motionScaledInterval(1000,2000)==1000);
  assert(motionScaledInterval(UINT32_MAX,100)==UINT32_MAX);
  assert(motionScaledInterval(1,999)==2);
}
