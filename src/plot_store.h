#pragma once
#ifdef TARGET_ESP32
#include <ArduinoJson.h>
#include <FS.h>
#include "plot_format.h"
class PlotStore {
 public:
  void begin();
  void status(JsonObject out);
  const char *upload(JsonObjectConst in);
  const char *chunk(JsonObjectConst in);
  const char *commit();
  const char *start(const char *id,const char *run);
  bool next(PlotRecord &record,uint32_t &index);
  void dispatched(uint32_t index) { dispatched_=index; }
  void settle();
  void stop(const char *reason="stopped");
  bool active() const { return active_; }
  bool uploading() const { return uploading_; }
  const char *id() const { return id_; }
 private:
  bool mount_=false,ready_=false,uploading_=false,active_=false;
  File file_;
  char id_[37]={},calibration_[37]={},run_[37]={};
  char pendingId_[37]={},pendingCalibration_[37]={};
  uint32_t count_=0,crc_=0,loaded_=0,dispatched_=0,completed_=0;
  uint32_t pendingCount_=0,pendingCrc_=0,received_=0,lastOffset_=UINT32_MAX;
  int up_=90,down_=40,pendingUp_=90,pendingDown_=40;
  float spu_[2]={},pendingSpu_[2]={};
  uint8_t lastChunk_[384]={};size_t lastLength_=0;
  const char *state_="empty";
  const char *validate(const char *path,uint32_t count,uint32_t crc);
};
extern PlotStore plotStore;
#endif
