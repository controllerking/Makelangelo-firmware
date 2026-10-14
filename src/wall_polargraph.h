#pragma once
#ifdef TARGET_ESP32
bool wallHardwareReady();
bool wallPositionKnown();
bool wallManualReference();
bool wallSetManualReference(float width, float left, float right, float extent = 10);
bool wallStopped();
bool wallIsHoming();
void wallInvalidatePosition();
void wallEmergencyStop();
void wallService();
bool wallHome();
bool wallMoveAllowed(const float *pos);
#endif
