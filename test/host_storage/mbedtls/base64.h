#pragma once
#include <stddef.h>
#include <cstring>
inline int mbedtls_base64_decode(unsigned char *out,size_t capacity,size_t *length,const unsigned char *in,size_t n) {
  const char *alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  unsigned value=0,bits=0;*length=0;
  for(size_t i=0;i<n && in[i]!='=';++i) {
    const char *p=strchr(alphabet,in[i]);if(!p)return -1;
    value=(value<<6)|unsigned(p-alphabet);bits+=6;
    if(bits>=8){bits-=8;if(*length>=capacity)return -1;out[(*length)++]=uint8_t(value>>bits);}
  }
  return 0;
}
