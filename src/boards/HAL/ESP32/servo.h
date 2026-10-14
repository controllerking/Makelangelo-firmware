#pragma once
#include <Arduino.h>
// ISR updates an atomic target; hardware PWM updates run in the main task.
class Servo {
 public:
  void attach(int pin) {
    pin_ = pin;
    ledcSetup(0, 50, 16);
    ledcAttachPin(pin_, 0);
    update();
  }
  void write(int angle) {
    angle = constrain(angle, 0, 180);
    pulse_ = WALL_SERVO_MIN_US +
      (WALL_SERVO_MAX_US - WALL_SERVO_MIN_US) * angle / 180;
  }
  void writeMicroseconds(int pulse) {
    pulse_ = constrain(pulse, WALL_SERVO_MIN_US, WALL_SERVO_MAX_US);
  }
  int read() const {
    return (pulse_ - WALL_SERVO_MIN_US) * 180 /
      (WALL_SERVO_MAX_US - WALL_SERVO_MIN_US);
  }
  void update() {
    const int pulse = pulse_;
    if (pin_ >= 0 && pulse != applied_) {
      ledcWrite(0, uint32_t(pulse) * 65535UL / 20000UL);
      applied_ = pulse;
    }
  }
 private:
  int pin_ = -1;
  volatile int pulse_ = (WALL_SERVO_MIN_US + WALL_SERVO_MAX_US) / 2;
  int applied_ = -1;
};
