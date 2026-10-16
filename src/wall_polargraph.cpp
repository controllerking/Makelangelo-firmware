#include "configure.h"
#ifdef TARGET_ESP32
#include "wall_polargraph.h"
#include "homing_axis.h"
#include "wireless.h"
#include "polargraph_math.h"
#include "user_calibration_math.h"
#include <Preferences.h>
#include "motion_control.h"

static int penUpAngle=PEN_UP_ANGLE, penDownAngle=PEN_DOWN_ANGLE;
static bool penCalibrated=false, penTuning=false;
int wallPenUpAngle() { return penUpAngle; }
int wallPenDownAngle() { return penDownAngle; }
bool wallPenCalibrated() { return penCalibrated; }
bool wallPenTuning() { return penTuning; }
void wallSetPenTuning(bool active) { penTuning=active; }
void wallLoadPenAngles() {
  Preferences prefs;
  if (prefs.begin("drawy-pen",true)) {
    const uint32_t packed=prefs.getUInt("angles",0);
    const int up=packed>>16,down=packed&65535;
    if (up>=10 && up<=170 && down>=10 && down<=170 && up!=down) {
      penUpAngle=up;penDownAngle=down;penCalibrated=true;
    }
    prefs.end();
  }
  axies[2].limitMin=10;axies[2].limitMax=170;
}
bool wallSavePenAngles(int up,int down) {
  if (up<10 || up>170 || down<10 || down>170 || up==down) return false;
  Preferences prefs;
  if (!prefs.begin("drawy-pen",false)) return false;
  const size_t written=prefs.putUInt("angles",(uint32_t(up)<<16)|uint32_t(down));
  prefs.end();
  if (written!=sizeof(uint32_t)) return false;
  penUpAngle=up;penDownAngle=down;penCalibrated=true;penTuning=false;
  return true;
}

static bool positionKnown = false;
static bool stopped = false;
static bool findingHome = false;
static bool manualReference = false;
static bool manualGeometry = false;
static float manualX = 0, manualY = 0;
static float manualExtent = 10;
static float savedBounds[4];
static bool userReference = false, calibrating = false;
static int32_t calibrationSteps[2] = {0,0};
static float drawingBounds[4];
static char calibrationId[37] = {};

bool wallStopped() { return stopped; }
bool wallIsHoming() { return findingHome; }
bool wallPositionKnown() { return positionKnown; }
bool wallManualReference() { return manualReference; }
bool wallUserReference() { return userReference; }
const char *wallCalibrationId() { return userReference ? calibrationId : ""; }
bool wallCalibrationActive() { return calibrating; }
int32_t wallCalibrationSteps(int axis) { return axis >= 0 && axis < 2 ? calibrationSteps[axis] : 0; }
float wallDrawingBound(int index) { return drawingBounds[index]; }
void wallCalibrationAbort() { calibrating = false; penTuning=false; }
void wallInvalidatePosition() {
  positionKnown = false;
  calibrating = false;
  if (manualReference || userReference) {
    axies[0].limitMin = savedBounds[0]; axies[0].limitMax = savedBounds[1];
    axies[1].limitMin = savedBounds[2]; axies[1].limitMax = savedBounds[3];
  }
  manualReference = false;
  userReference = false;
}

bool wallCalibrationBegin() {
  if (stopped || penTuning || findingHome || !wallHardwareReady() || planner.movesPlanned()) return false;
  wallInvalidatePosition();
  calibrationSteps[0] = calibrationSteps[1] = 0;
  calibrating = true;
  motor.engage();
  motor.setPenAngle(wallPenUpAngle()); servos[0].update();
  const uint32_t settle=millis();
  while (uint32_t(millis()-settle)<300 || servos[0].moving()) {
    wallService();
    if (stopped || !calibrating) return false;
  }
  return true;
}

bool wallCalibrationJog(int axis, int steps) {
  if (!calibrating || stopped || axis < 0 || axis > 1 || !steps || steps < -4000 || steps > 4000) return false;
  const int dirs[2] = {MOTOR_0_DIR_PIN,MOTOR_1_DIR_PIN};
  const int pins[2] = {MOTOR_0_STEP_PIN,MOTOR_1_STEP_PIN};
  digitalWrite(dirs[axis], esp32MotorDirectionLevel(axis, steps < 0));
  for (int i=0; i<abs(steps); ++i) {
    // Ramp from 2 to 20 mm/s at 40 mm/s^2, slowing again before the end.
    const float rampDistance=float(_MIN(i,abs(steps)-1-i))/motor_spu[axis];
    const float speed=_MIN(20.0f,sqrtf(4.0f+80.0f*rampDistance));
    const uint32_t interval=motionScaledInterval(uint32_t(ceilf(1000000.0f / _MIN(2000.0f,speed*motor_spu[axis]))),motionStepperPermille());
    const uint32_t start=micros();
    do {
      wallService();
      if (stopped || !calibrating || wirelessHoldMotion()) { calibrating=false; return false; }
    } while (uint32_t(micros()-start)<interval);
    if (stopped || !calibrating || wirelessHoldMotion()) { calibrating = false; return false; }
    if (labs(calibrationSteps[axis])>=160000L) { calibrating=false; return false; }
    delayMicroseconds(2);
    digitalWrite(pins[axis],HIGH); delayMicroseconds(2); digitalWrite(pins[axis],LOW);
    calibrationSteps[axis] += steps < 0 ? -1 : 1;
  }
  return true;
}

bool wallSetUserReference(float width, float left, float right, const float *bounds, const char *id) {
  float x,y;
  if (stopped || findingHome || !wallHardwareReady() || planner.movesPlanned() ||
      !userCalibrationBounds(width,bounds[0],bounds[1],bounds[2],bounds[3]) ||
      left > 4000 || right > 4000 || !polargraphPosition(0,width,0,left,right,x,y) ||
      !userCalibrationContains(x,y,bounds) || !id || strlen(id) != 36) return false;
  for (int i=0; i<36; ++i) if (!isxdigit(id[i]) && id[i]!='-') return false;
  wallInvalidatePosition();
  savedBounds[0]=axies[0].limitMin; savedBounds[1]=axies[0].limitMax;
  savedBounds[2]=axies[1].limitMin; savedBounds[3]=axies[1].limitMax;
  axies[0].limitMin=0; axies[0].limitMax=width;
  axies[1].limitMin=bounds[1]; axies[1].limitMax=0;
  for (int i=0;i<4;++i) drawingBounds[i]=bounds[i];
  memcpy(calibrationId,id,37);
  motor.engage();
  float pos[NUM_AXIES]={x,y,float(wallPenUpAngle())};
  teleport(pos);
  userReference = manualGeometry = positionKnown = true;
  desiredFeedRate=DEFAULT_FEEDRATE;
  return true;
}

bool wallSetManualReference(float width, float left, float right, float extent) {
  float x, y;
  if (stopped || findingHome || !wallHardwareReady() || planner.movesPlanned() ||
      wirelessOwnsMotion() || !isfinite(width) || width < 100 || width > 2000 ||
      left > 3000 || right > 3000 || !isfinite(extent) || extent < 1 || extent > 80 ||
      !polargraphPosition(0, width, 0, left, right, x, y) ||
      x < 20 || x > width-20 || y > -50 || y < -2000) return false;
  // RAM only. Never overwrite measured switch references or EEPROM geometry.
  wallInvalidatePosition();
  savedBounds[0] = axies[0].limitMin; savedBounds[1] = axies[0].limitMax;
  savedBounds[2] = axies[1].limitMin; savedBounds[3] = axies[1].limitMax;
  axies[0].limitMin = 0; axies[0].limitMax = width;
  axies[1].limitMin = y-extent; axies[1].limitMax = 0;
  float position[NUM_AXIES] = {x, y, axies[2].pos};
  motor.engage();
  teleport(position);
  manualX = x; manualY = y;
  manualExtent = extent;
  manualReference = manualGeometry = positionKnown = true;
  desiredFeedRate = 2;
  SERIAL_ECHOLNPGM("MANUAL reference: RAM only, bounded envelope, 2mm/s maximum. Reset before homing.");
  SERIAL_ECHOLNPAIR("Manual envelope +/- mm: ", manualExtent);
  return true;
}

bool wallHardwareReady() {
  if (!HAL_storage_ready()) return false;
  const int pins[] = { MOTOR_0_STEP_PIN, MOTOR_0_DIR_PIN, MOTOR_0_ENABLE_PIN,
    MOTOR_0_LIMIT_SWITCH_PIN, MOTOR_1_STEP_PIN, MOTOR_1_DIR_PIN,
    MOTOR_1_ENABLE_PIN, MOTOR_1_LIMIT_SWITCH_PIN, SERVO0_PIN };
  for (unsigned i = 0; i < sizeof(pins)/sizeof(pins[0]); ++i) {
    const int p = pins[i];
    // WROOM: flash, straps, UART0, and input-only pins deliberately excluded.
    if (!(p == 13 || p == 14 || (p >= 16 && p <= 19) ||
        (p >= 21 && p <= 23) || (p >= 25 && p <= 27) || p == 32 || p == 33))
      return false;
    for (unsigned j = 0; j < i; ++j) if (pins[j] == p) return false;
  }
  return true;
}

void wallEmergencyStop() {
  stopped = true;
  penTuning=false;
  wallInvalidatePosition();
  HAL_timer_disable_interrupt(0);
  motor.abortMotion();
  motor.disengage();
  if (wallHardwareReady()) {
    motor.setPenAngle(wallPenUpAngle());
    servos[0].update();
  }
}

void wallService() {
  motionUpdateSpeeds(millis());
  if (wallHardwareReady()) servos[0].update();
  // Feed serial even while the planner waits or homing is in progress.
  parser.update();
  wirelessPoll();
  delay(1);
}

bool wallMoveAllowed(const float *pos) {
  if (stopped || penTuning || !wallHardwareReady() || !positionKnown) {
    SERIAL_ECHOLNPGM("Motion blocked: configure hardware and home with G28.");
    return false;
  }
  if (manualReference && !polargraphManualTarget(pos[0], pos[1], manualX, manualY, manualExtent)) {
    SERIAL_ECHOLNPGM("Motion blocked: outside manual envelope.");
    return false;
  }
  if (userReference && !userCalibrationContains(pos[0],pos[1],drawingBounds)) {
    SERIAL_ECHOLNPGM("Motion blocked: outside user-calibrated paper envelope.");
    return false;
  }
  for (int i = 0; i < NUM_AXIES; ++i) {
    if (!isfinite(pos[i]) || pos[i] < axies[i].limitMin ||
        pos[i] > axies[i].limitMax) {
      SERIAL_ECHOLNPGM("Motion blocked: outside configured limits.");
      return false;
    }
  }
  if (pos[1] >= axies[1].limitMax) {
    SERIAL_ECHOLNPGM("Motion blocked: target at/above anchors.");
    return false;
  }
  return true;
}

static bool homeFault(const char *message) {
  findingHome = false;
  wallEmergencyStop();
  SERIAL_ECHOLN(message);
  SERIAL_ECHOLNPGM("FAULT: reset required; inspect switches, routing and calibration.");
  return false;
}

bool wallHome() {
  if (stopped || !wallHardwareReady()) return false;
  if (manualGeometry) {
    SERIAL_ECHOLNPGM("G28 blocked: reset to discard temporary manual geometry first.");
    return false;
  }
  if (!WALL_HOMING_CONFIRMED) {
    SERIAL_ECHOLNPGM("G28 blocked: verify belt directions/travel, then set WALL_HOMING_CONFIRMED.");
    return false;
  }
  int32_t reference[NUM_MUSCLES] = {
    lroundf(calibrateLeft * motor_spu[0]),
    lroundf(calibrateRight * motor_spu[1]), wallPenUpAngle() };
  float atReference[NUM_AXIES];
  if (!isfinite(calibrateLeft) || !isfinite(calibrateRight) ||
      calibrateLeft <= 0 || calibrateRight <= 0 || FK(reference, atReference) ||
      atReference[0] < axies[0].limitMin || atReference[0] > axies[0].limitMax ||
      atReference[1] >= axies[1].limitMax || atReference[1] < axies[1].limitMin) {
    SERIAL_ECHOLNPGM("G28 blocked: configure geometry (M101) and reference lengths (D7; D9).");
    return false;
  }
  planner.wait_for_empty_segment_buffer();
  if (stopped) return false;
  positionKnown = false;
  findingHome = true;
  motor.setPenAngle(wallPenUpAngle());
  servos[0].update();
  const uint32_t penSettle=millis();
  while (uint32_t(millis()-penSettle)<300 || servos[0].moving()) {
    wallService();
    if (stopped || wirelessHoldMotion()) return homeFault("Homing aborted while lifting pen.");
  }
  HAL_timer_disable_interrupt(0);
  motor.engage();
  const int switches[2] = { LIMIT_SWITCH_PIN_LEFT, LIMIT_SWITCH_PIN_RIGHT };
  const int dirs[2] = { WALL_HOME_LEFT_DIR, WALL_HOME_RIGHT_DIR };
  const int dirPins[2] = { MOTOR_0_DIR_PIN, MOTOR_1_DIR_PIN };
  const int stepPins[2] = { MOTOR_0_STEP_PIN, MOTOR_1_STEP_PIN };
  HomingAxis axes[2] = {
    HomingAxis(digitalRead(switches[0]) == HIGH, millis(), WALL_HOMING_MAX_STEPS, WALL_HOMING_BACKOFF_STEPS),
    HomingAxis(digitalRead(switches[1]) == HIGH, millis(), WALL_HOMING_MAX_STEPS, WALL_HOMING_BACKOFF_STEPS) };
  uint32_t lastStep[2] = { micros(), micros() };
  SERIAL_ECHOLNPGM("Homing: pen up; independent counterweight references.");
  while (axes[0].phase != HomingAxis::Done || axes[1].phase != HomingAxis::Done) {
    wallService();
    if (stopped) return homeFault("Homing aborted.");
    for (int i = 0; i < 2; ++i) {
      const uint32_t interval = WALL_HOMING_INTERVAL_US *
        (axes[i].phase == HomingAxis::Latch ? 2 : 1);
      const uint32_t nowUs = micros();
      if (uint32_t(nowUs - lastStep[i]) < interval) continue;
      lastStep[i] = nowUs;
      // Capture direction before tick may change the phase.
      const bool backingOff = axes[i].phase == HomingAxis::Backoff;
      if (axes[i].tick(digitalRead(switches[i]) == HIGH, millis(), interval)) {
        digitalWrite(dirPins[i], esp32MotorDirectionLevel(i, backingOff ? !dirs[i] : dirs[i]));
        delayMicroseconds(2);
        digitalWrite(stepPins[i], HIGH);
        delayMicroseconds(2);
        digitalWrite(stepPins[i], LOW);
      }
      if (axes[i].phase == HomingAxis::Fault)
        return homeFault(i == 0 ? "Left homing switch/travel fault." : "Right homing switch/travel fault.");
    }
  }
  if (FK(reference, atReference)) return homeFault("Invalid reference geometry.");
  teleport(atReference);
  findingHome = false;
  positionKnown = true;
  HAL_timer_enable_interrupt(0);
  SERIAL_ECHOLNPGM("Homed at switch references; pen up.");
  parser.M114();
  return true;
}
#endif
