#pragma once
#include <stdint.h>
// Bound idle scratch/ready files while allowing short reconnects and retries.
constexpr uint32_t PLOT_UPLOAD_IDLE_MS=120000UL;
constexpr uint32_t PLOT_READY_IDLE_MS=600000UL;
inline bool plotIdleExpired(uint32_t now,uint32_t last,uint32_t limit) {
  return uint32_t(now-last)>=limit;
}
