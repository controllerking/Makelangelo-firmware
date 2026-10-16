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
  for(uint32_t p=100;p<=1000;++p) {
    const uint32_t values[]={0,1,19,1000,1234567,UINT32_MAX/10,UINT32_MAX};
    for(uint32_t ticks:values) {
      const uint64_t expected=(uint64_t(ticks)*1000+p-1)/p;
      assert(motionScaledInterval(ticks,p)==(expected>UINT32_MAX ? UINT32_MAX : expected));
    }
  }
}
