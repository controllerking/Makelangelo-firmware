#pragma once
#include <stdint.h>
#ifdef TARGET_ESP32
bool wallHardwareReady();
int wallPenUpAngle();
int wallPenDownAngle();
bool wallPenCalibrated();
bool wallPenTuning();
void wallLoadPenAngles();
bool wallSavePenAngles(int up, int down);
void wallSetPenTuning(bool active);
bool wallPositionKnown();
bool wallManualReference();
bool wallUserReference();
const char *wallCalibrationId();
bool wallCalibrationActive();
int32_t wallCalibrationSteps(int axis);
float wallDrawingBound(int index);
bool wallCalibrationBegin();
void wallCalibrationAbort();
bool wallCalibrationJog(int axis, int steps);
bool wallSetUserReference(float width, float left, float right, const float *bounds, const char *id);
bool wallSetManualReference(float width, float left, float right, float extent = 10);
bool wallStopped();
bool wallIsHoming();
void wallInvalidatePosition();
void wallEmergencyStop();
void wallService();
bool wallHome();
bool wallMoveAllowed(const float *pos);
#endif
