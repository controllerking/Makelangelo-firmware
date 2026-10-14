#pragma once
#ifdef TARGET_ESP32
void wirelessBegin();
void wirelessPoll();
void wirelessAdvance();
bool wirelessOwnsMotion();
bool wirelessHoldMotion();
bool wirelessSetupRequested(const char *line);
#endif
