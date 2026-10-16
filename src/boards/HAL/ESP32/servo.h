#pragma once
#include <Arduino.h>
#include "../../../servo_motion.h"
#include "../../../motion_control.h"
// ISR updates an atomic target; hardware PWM updates run in the main task.
class Servo {
 public:
  void attach(int pin) {
    pin_ = pin;
    ledcSetup(0, 50, 16);
    ledcAttachPin(pin_, 0);
    update();
  }
  inline __attribute__((always_inline)) void write(int angle) {
    angle = constrain(angle, 0, 180);
    pulse_ = WALL_SERVO_MIN_US +
      (WALL_SERVO_MAX_US - WALL_SERVO_MIN_US) * angle / 180;
  }
  void writeMicroseconds(int pulse) {
    pulse_ = constrain(pulse, WALL_SERVO_MIN_US, WALL_SERVO_MAX_US);
  }
  int read() const {
    return lroundf(float(pulse_ - WALL_SERVO_MIN_US) * 180 /
      (WALL_SERVO_MAX_US - WALL_SERVO_MIN_US));
  }
  void update() {
    const int pulse = pulse_;
    if (pin_ < 0) return;
    const uint32_t now=micros();
    if (applied_<0) motion_.reset(pulse);
    else {
      const float usPerDegree=float(WALL_SERVO_MAX_US-WALL_SERVO_MIN_US)/180.0f;
      motion_.advance(pulse,float(uint32_t(now-lastUpdate_))/1000000.0f,
                      motionServoSpeed()*usPerDegree,WALL_SERVO_ACCEL_DEG_S2*usPerDegree);
      motion_.position=constrain(motion_.position,float(WALL_SERVO_MIN_US),float(WALL_SERVO_MAX_US));
    }
    lastUpdate_=now;
    const int output=lroundf(motion_.position);
    if (output != applied_) {
      ledcWrite(0, uint32_t(output) * 65535UL / 20000UL);
      applied_ = output;
    }
  }
  bool moving() const { return applied_>=0 && (fabsf(motion_.position-pulse_)>.1f || fabsf(motion_.velocity)>.1f); }
 private:
  int pin_ = -1;
  volatile int pulse_ = (WALL_SERVO_MIN_US + WALL_SERVO_MAX_US) / 2;
  int applied_ = -1;
  uint32_t lastUpdate_ = 0;
  ServoMotion motion_;
};
