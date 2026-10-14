#pragma once
//------------------------------------------------------------------------------
// Makelangelo - firmware for various robot kinematic models
// dan@marginallycelver.com 2013-12-26
// Please see http://www.github.com/MarginallyClever/makelangeloFirmware for more information.
//------------------------------------------------------------------------------

#if MACHINE_STYLE == POLARGRAPH

#  define MACHINE_STYLE_NAME "POLARGRAPH"

// supported versions of makelangelo polargraph robot
#  define MAKELANGELO_3   3
#  define MAKELANGELO_3_3 4  // Makelangelo Huge
#  define MAKELANGELO_5   5
#  define MAKELANGELO_6   6  // for testing

#  define MACHINE_HARDWARE_VERSION MAKELANGELO_5  // Change me

#  define MACHINE_HAS_LIFTABLE_PEN

// what is the maximum length of a subdivided line?
#  define SEGMENTS_PER_SECOND (10)

// servo angles for pen control
#  ifndef PEN_UP_ANGLE
#    define PEN_UP_ANGLE   (90)
#  endif
#  ifndef PEN_DOWN_ANGLE
#    define PEN_DOWN_ANGLE (40)
#  endif

#  define NUM_AXIES  (3)
#  define NUM_MOTORS (2)
#  define NUM_SERVOS (1)
#  define NUM_TOOLS  (1)

#  ifdef TARGET_ESP32
#    define MAX_FEEDRATE (30.0f)
#  else
#    define MAX_FEEDRATE (200.0f)
#  endif
#  ifdef TARGET_ESP32
#    define MIN_FEEDRATE (0.1f)
#  else
#    define MIN_FEEDRATE (0.0f)
#  endif

#  define MAX_FEEDRATE_Z (180.0)  // linear travel speed

#  ifdef TARGET_ESP32
#    define MAX_STEP_RATE_DEFAULT (30.0)
#    define MAX_ACCELERATION (100.0)
#  else
#    define MAX_STEP_RATE_DEFAULT (200.0)
#    define MAX_ACCELERATION (1000.0)
#  endif
#  ifdef TARGET_ESP32
#    define MIN_ACCELERATION (1.0)
#  else
#    define MIN_ACCELERATION (0.0)
#  endif

#  define MAX_JERK         (50.0)
#  define MAX_JERK_DEFAULT (20.0)

#  define MAX_JERK_Z         (3.0)
#  define MAX_JERK_Z_DEFAULT (0.3)

// uncomment this line to adjust acceleration based on pen position
#  define DYNAMIC_ACCELERATION


#  if MACHINE_HARDWARE_VERSION == MAKELANGELO_3
#    ifndef MAX_SEGMENTS
#      define MAX_SEGMENTS (8)
#    endif
#  endif

#  if MACHINE_HARDWARE_VERSION == MAKELANGELO_3_3
#    ifndef MAX_SEGMENTS
#      define MAX_SEGMENTS (8)
#    endif
#    define USE_LIMIT_SWITCH
#  endif

#  if MACHINE_HARDWARE_VERSION == MAKELANGELO_5
#    ifndef MAX_SEGMENTS
#      define MAX_SEGMENTS (16)
#    endif
#    define USE_LIMIT_SWITCH
#  endif

#  if MACHINE_HARDWARE_VERSION == MAKELANGELO_6
#    ifndef MAX_SEGMENTS
#      define MAX_SEGMENTS (8)
#    endif
#    define USE_LIMIT_SWITCH
#    define HAS_TMC2130  // driver type
#    define STEALTHCHOP  // quiet operation
#  endif

#  if defined(HAS_TMC2130) || defined(USE_LIMIT_SWITCH)
#    define CAN_HOME
#  endif

//------------------------------------------------------------------------------

// extern void calibrateBelts();
extern void recordHome();

// convert belt length to cartesian position, save that as home pos.
extern void calibrationToPosition();

extern void factory_reset();
FORCE_INLINE void robotMeanwhile() {}

#endif  // #ifdef POLARGRAPH
