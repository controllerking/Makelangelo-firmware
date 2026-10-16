#include "configure.h"
#ifdef TARGET_ESP32
#include "plot_store.h"
#include "wall_polargraph.h"
#include <SPIFFS.h>
#include <mbedtls/base64.h>
PlotStore plotStore;
namespace {
bool uuid(const char *s) {
  if(!s || strlen(s)!=36)return false;
  for(int i=0;i<36;++i)if(!isxdigit(s[i]) && s[i]!='-')return false;
  return true;
}
}
void PlotStore::begin() {
  mount_=SPIFFS.begin(false); // Never erase a damaged filesystem on boot.
  if(!mount_)return;
  File meta=SPIFFS.open("/plot.json","r");
  StaticJsonDocument<512> doc;
  if(!meta || deserializeJson(doc,meta))return;
  const char *id=doc["id"]|"",*cal=doc["cal"]|"";
  if(!uuid(id)||!uuid(cal))return;
  count_=doc["count"];crc_=doc["crc"];up_=doc["up"];down_=doc["down"];
  spu_[0]=doc["spu0"];spu_[1]=doc["spu1"];
  File data=SPIFFS.open("/plot.bin","r");
  if(!count_ || count_>PLOT_MAX_BYTES/16 || !data || data.size()!=count_*16)return;
  strlcpy(id_,id,sizeof(id_));strlcpy(calibration_,cal,sizeof(calibration_));
  ready_=true;state_="ready"; // A reboot NEVER restores physical position or runs.
}
void PlotStore::status(JsonObject out) {
  out["stored_plot_api"]=1;out["plot_capacity"]=PLOT_MAX_BYTES;
  out["plot_free"]=mount_ ? SPIFFS.totalBytes()-SPIFFS.usedBytes() : 0;
  out["plot_id"]=uploading_ ? pendingId_ : id_;
  out["plot_run"]=run_;out["plot_state"]=state_;
  out["plot_total"]=uploading_ ? pendingCount_ : count_;
  out["plot_received"]=received_;out["plot_completed"]=completed_;
}
const char *PlotStore::upload(JsonObjectConst in) {
  const char *id=in["job"]|"",*cal=in["cal"]|"";
  if(!uuid(id)||!uuid(cal)||!in["count"].is<uint32_t>()||!in["crc"].is<uint32_t>()||
     !in["up"].is<int>()||!in["down"].is<int>()||!in["spu0"].is<float>()||!in["spu1"].is<float>())return "invalid_plot_metadata";
  const uint32_t count=in["count"],crc=in["crc"];
  const int up=in["up"],down=in["down"];
  if(!count || count>PLOT_MAX_BYTES/16 || up<10||up>170||down<10||down>170||up==down ||
     in["spu0"].as<float>()!=motor_spu[0] || in["spu1"].as<float>()!=motor_spu[1])return "invalid_plot_metadata";
  if(uploading_ && !strcmp(id,pendingId_) && count==pendingCount_ && crc==pendingCrc_ &&
     !strcmp(cal,pendingCalibration_) && up==pendingUp_ && down==pendingDown_)return nullptr;
  if(active_)return "plot_running";
  if(file_)file_.close();
  // Only an explicit, confirmed new upload may initialize unused storage.
  if(!mount_)mount_=SPIFFS.begin(true);
  if(!mount_)return "storage_unavailable";
  SPIFFS.remove("/plot.part");
  uploading_=false;
  if(SPIFFS.totalBytes()-SPIFFS.usedBytes()<count*16+65536)return "plot_storage_full";
  file_=SPIFFS.open("/plot.part","w");
  if(!file_)return "plot_open_failed";
  strlcpy(pendingId_,id,sizeof(pendingId_));strlcpy(pendingCalibration_,cal,sizeof(pendingCalibration_));
  pendingCount_=count;pendingCrc_=crc;pendingUp_=up;pendingDown_=down;
  pendingSpu_[0]=in["spu0"];pendingSpu_[1]=in["spu1"];
  received_=0;lastOffset_=UINT32_MAX;lastLength_=0;uploading_=true;state_="uploading";
  return nullptr;
}
const char *PlotStore::chunk(JsonObjectConst in) {
  if(!uploading_)return "no_plot_upload";
  if(!in["offset"].is<uint32_t>()||!in["data"].is<const char*>())return "invalid_plot_chunk";
  uint8_t data[384];size_t length=0;
  const char *encoded=in["data"];
  if(strlen(encoded)>512 || mbedtls_base64_decode(data,sizeof(data),&length,(const unsigned char*)encoded,strlen(encoded)) || !length || length%16)return "invalid_plot_chunk";
  const uint32_t offset=in["offset"];
  if(offset==lastOffset_ && length==lastLength_ && !memcmp(data,lastChunk_,length))return nullptr;
  if(offset!=received_ || length>pendingCount_*16-received_)return "plot_offset_mismatch";
  if(file_.write(data,length)!=length) {file_.close();uploading_=false;state_="error";return "plot_write_failed";}
  memcpy(lastChunk_,data,length);lastOffset_=offset;lastLength_=length;received_+=length;
  return nullptr;
}
const char *PlotStore::validate(const char *path,uint32_t count,uint32_t expected) {
  File data=SPIFFS.open(path,"r");
  if(!data || data.size()!=count*16)return "plot_incomplete";
  PlotRecord buffer[32];uint32_t crc=0xffffffffUL,index=0,lastPen=1;
  while(data.available()) {
    const size_t n=data.read((uint8_t*)buffer,sizeof(buffer));
    if(!n || n%16)return "plot_read_failed";
    crc=plotCrcUpdate(crc,(uint8_t*)buffer,n);
    for(size_t i=0;i<n/16;++i) {
      const PlotRecord &r=buffer[i];
      if(!plotRecordValid(r))return "invalid_plot_record";
      if(r.op==0) {
        float target[NUM_AXIES]={r.x,r.y,float(wallPenUpAngle())};
        if(!wallMoveAllowed(target) || (wallManualReference() && r.feed>2))return "plot_outside_calibration";
      } else if(r.op==1 || r.op==2)lastPen=r.op;
      if(++index==count && (r.op!=3 || lastPen!=1))return "plot_must_finish_pen_up_sync";
    }
    // No motor motion during validation. Main service keeps servo/Stop alive.
    wallService();
    if(wallStopped())return "fault";
  }
  return (crc^0xffffffffUL)==expected ? nullptr : "plot_checksum_mismatch";
}
const char *PlotStore::commit() {
  if(!uploading_)return ready_ ? nullptr : "no_plot_upload";
  if(received_!=pendingCount_*16)return "plot_incomplete";
  file_.flush();file_.close();
  const char *error=validate("/plot.part",pendingCount_,pendingCrc_);
  if(error) {uploading_=false;state_="error";return error;}
  StaticJsonDocument<512> doc;
  doc["id"]=pendingId_;doc["cal"]=pendingCalibration_;doc["count"]=pendingCount_;doc["crc"]=pendingCrc_;
  doc["up"]=pendingUp_;doc["down"]=pendingDown_;doc["spu0"]=pendingSpu_[0];doc["spu1"]=pendingSpu_[1];
  File meta=SPIFFS.open("/plot.tmp","w");
  if(!meta || serializeJson(doc,meta)==0) {uploading_=false;state_="error";return "plot_metadata_failed";}
  meta.flush();meta.close();
  ready_=false;
  SPIFFS.remove("/plot.bin");SPIFFS.remove("/plot.json");
  if(!SPIFFS.rename("/plot.part","/plot.bin") || !SPIFFS.rename("/plot.tmp","/plot.json")) {uploading_=false;state_="error";return "plot_publish_failed";}
  strlcpy(id_,pendingId_,sizeof(id_));strlcpy(calibration_,pendingCalibration_,sizeof(calibration_));
  count_=pendingCount_;crc_=pendingCrc_;up_=pendingUp_;down_=pendingDown_;
  spu_[0]=pendingSpu_[0];spu_[1]=pendingSpu_[1];
  ready_=true;uploading_=false;state_="ready";completed_=loaded_=dispatched_=0;run_[0]=0;
  return nullptr;
}
const char *PlotStore::start(const char *id,const char *run) {
  if(!uuid(run)||strcmp(id,id_))return "plot_id_mismatch";
  if(!strcmp(run,run_))return nullptr; // A lost start acknowledgement cannot duplicate a drawing.
  if(!ready_ || uploading_ || active_)return "plot_not_ready";
  if(!wallPositionKnown() || !wallUserReference() || strcmp(calibration_,wallCalibrationId()) ||
     up_!=wallPenUpAngle() || down_!=wallPenDownAngle() || spu_[0]!=motor_spu[0] || spu_[1]!=motor_spu[1])return "plot_reference_changed";
  const char *error=validate("/plot.bin",count_,crc_);
  if(error)return error;
  file_=SPIFFS.open("/plot.bin","r");
  if(!file_)return "plot_open_failed";
  strlcpy(run_,run,sizeof(run_));loaded_=dispatched_=completed_=0;active_=true;state_="running";
  return nullptr;
}
bool PlotStore::next(PlotRecord &record,uint32_t &index) {
  if(!active_ || loaded_>=count_)return false;
  if(file_.read((uint8_t*)&record,sizeof(record))!=sizeof(record) || !plotRecordValid(record)) {
    stop("error");wallEmergencyStop();return false;
  }
  index=++loaded_;return true;
}
void PlotStore::settle() {
  if(!active_)return;
  completed_=dispatched_;
  if(completed_==count_) {active_=false;state_="completed";file_.close();}
}
void PlotStore::stop(const char *reason) {
  if(!active_)return;
  active_=false;state_=reason;file_.close();
}
#endif
