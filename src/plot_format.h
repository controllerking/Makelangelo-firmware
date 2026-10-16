#pragma once
#include <stdint.h>
#include <stddef.h>
#include <math.h>
// Little-endian ESP32/Python wire format: uint32 op, float x,y,feed.
struct PlotRecord { uint32_t op; float x,y,feed; };
static_assert(sizeof(PlotRecord)==16,"Plot record layout changed");
constexpr uint32_t PLOT_MAX_BYTES=1024UL*1024UL;
inline bool plotRecordValid(const PlotRecord &r) {
  return r.op<=3 && isfinite(r.x) && isfinite(r.y) && isfinite(r.feed) &&
    (r.op==0 ? r.feed>=.1f && r.feed<=30 : r.x==0 && r.y==0 && r.feed==0);
}
inline uint32_t plotCrcUpdate(uint32_t crc,const uint8_t *data,size_t length) {
  while(length--) {
    crc^=*data++;
    for(int i=0;i<8;++i) crc=(crc>>1)^(0xedb88320UL & (0UL-(crc&1)));
  }
  return crc;
}
