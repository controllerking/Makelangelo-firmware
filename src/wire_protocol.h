#pragma once
#include <stdint.h>
#include <stddef.h>

// Pure protocol logic, shared with host-side C++ fault tests.
class WireLedger {
 public:
  enum Result { New, Duplicate, Conflict, Stale, OutOfOrder };
  uint32_t next = 1, completed = 0;
  Result inspect(uint32_t id, uint32_t hash) const {
    if (next == UINT32_MAX) return OutOfOrder; // Renew a drained session before wrap.
    if (id == next) return New;
    if (id > next || id == 0) return OutOfOrder;
    const Entry &e = entries[id % capacity];
    if (e.id != id) return Stale;
    return e.hash == hash ? Duplicate : Conflict;
  }
  void accept(uint32_t hash) {
    entries[next % capacity] = { next, hash };
    ++next;
  }
  void finish(uint32_t id) { if (id > completed && id < next) completed = id; }
  void reset() { next = 1; completed = 0; for (auto &e : entries) e = {0, 0}; }
  static uint32_t fingerprint(const char *s) {
    uint32_t h = 2166136261UL;
    while (*s) { h ^= uint8_t(*s++); h *= 16777619UL; }
    return h;
  }
 private:
  static constexpr size_t capacity = 32;
  struct Entry {
    uint32_t id, hash;
    Entry(uint32_t i = 0, uint32_t h = 0) : id(i), hash(h) {}
  };
  Entry entries[capacity];
};
