#include <assert.h>
#include "../src/plot_format.h"
int main() {
  const uint8_t data[]="123456789";
  assert((plotCrcUpdate(0xffffffffUL,data,9)^0xffffffffUL)==0xcbf43926UL);
  assert(plotRecordValid({0,100,-100,10}));
  assert(!plotRecordValid({0,100,-100,31}));
  assert(!plotRecordValid({0,NAN,-100,10}));
  assert(plotRecordValid({1,0,0,0}));
  assert(!plotRecordValid({4,0,0,0}));
  assert(!plotRecordValid({2,1,0,0}));
}
