#pragma once
#define TARGET_ESP32
#define NUM_AXIES 3
#include <stdint.h>
#include <cstring>
#include <ctype.h>
extern uint32_t fakeMillis;
extern float motor_spu[3];
inline uint32_t millis() {return fakeMillis;}
#define strlcpy drawyHostStrlcpy
inline size_t drawyHostStrlcpy(char *out,const char *in,size_t capacity) {
  size_t n=strlen(in);if(capacity){size_t copied=n<capacity-1 ? n : capacity-1;memcpy(out,in,copied);out[copied]=0;}return n;
}
