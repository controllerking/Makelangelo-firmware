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
bool PlotStore::removeFile(const char *path) {
  return !SPIFFS.exists(path) || SPIFFS.remove(path);
}
bool PlotStore::cleanFiles(bool committed,bool scratch) {
  bool ok=true;
  // Try every owned path even if an earlier removal failed. Never touch NVS.
  if(scratch) {
    if(!removeFile("/plot.part"))ok=false;
    if(!removeFile("/plot.tmp"))ok=false;
  }
  if(committed) {
    if(!removeFile("/plot.json"))ok=false;
    if(!removeFile("/plot.bin"))ok=false;
  }
  cleanupError_=!ok;
  return ok;
}
void PlotStore::failUpload() {
  file_.close();uploading_=false;state_="error";cleanupScratch_=true;
}
void PlotStore::begin() {
  mount_=SPIFFS.begin(false); // Never erase a damaged filesystem on boot.
  if(!mount_)return;
  // Boot changes invalidate upload offsets. Remove only our abandoned scratch.
  cleanupScratch_=!cleanFiles(false,true);
  bool valid=false;
  {
    File meta=SPIFFS.open("/plot.json","r");
    StaticJsonDocument<512> doc;
    if(meta && !deserializeJson(doc,meta)) {
      const char *id=doc["id"]|"",*cal=doc["cal"]|"";
      if(uuid(id) && uuid(cal)) {
        count_=doc["count"];crc_=doc["crc"];up_=doc["up"];down_=doc["down"];
        spu_[0]=doc["spu0"];spu_[1]=doc["spu1"];
        File data=SPIFFS.open("/plot.bin","r");
        valid=count_ && count_<=PLOT_MAX_BYTES/16 && data && data.size()==count_*16;
        if(valid) {
          strlcpy(id_,id,sizeof(id_));strlcpy(calibration_,cal,sizeof(calibration_));
          ready_=true;state_="ready";readySince_=millis();
        }
      }
    }
  } // Close every handle before removing orphaned files.
  if(!valid)cleanupCommitted_=!cleanFiles(true,false);
}
void PlotStore::service() {
  if(!mount_ || active_)return;
  const uint32_t now=millis();
  if(uploading_ && plotIdleExpired(now,lastUploadActivity_,PLOT_UPLOAD_IDLE_MS)) {
    file_.close();uploading_=false;received_=0;lastOffset_=UINT32_MAX;lastLength_=0;
    state_=uploadReturnState_;cleanupScratch_=true;
  }
  if(ready_ && plotIdleExpired(now,readySince_,PLOT_READY_IDLE_MS)) {
    ready_=false;state_="expired";cleanupCommitted_=true;
  }
  if(!cleanupCommitted_ && !cleanupScratch_)return;
  if(cleanupError_ && !plotIdleExpired(now,lastCleanupAttempt_,1000))return;
  lastCleanupAttempt_=now;
  // Never remove an in-progress upload while collecting other garbage.
  const bool scratch=cleanupScratch_ && !uploading_;
  const bool committed=cleanupCommitted_ && !ready_;
  if(cleanFiles(committed,scratch)) {
    if(committed)cleanupCommitted_=false;
    if(scratch)cleanupScratch_=false;
  }
}
void PlotStore::status(JsonObject out) {
  out["stored_plot_api"]=2;out["plot_capacity"]=PLOT_MAX_BYTES;
  out["plot_free"]=mount_ ? SPIFFS.totalBytes()-SPIFFS.usedBytes() : 0;
  out["plot_storage_total"]=mount_ ? SPIFFS.totalBytes() : 0;
  out["plot_cleanup_pending"]=cleanupCommitted_ || cleanupScratch_;
  out["plot_cleanup_error"]=cleanupError_;
  out["plot_id"]=uploading_ ? pendingId_ : id_;
  out["plot_parent"]=parent_;out["plot_chain"]=chain_;out["plot_part"]=part_;out["plot_final"]=final_;
  out["plot_run"]=run_;out["plot_state"]=state_;
  out["plot_total"]=uploading_ ? pendingCount_ : count_;
  out["plot_received"]=received_;out["plot_completed"]=completed_;
}
const char *PlotStore::upload(JsonObjectConst in) {
  const char *id=in["job"]|"",*cal=in["cal"]|"";
  if(!uuid(id)||!uuid(cal)||!in["count"].is<uint32_t>()||!in["crc"].is<uint32_t>()||
     !in["up"].is<int>()||!in["down"].is<int>()||!in["spu0"].is<float>()||!in["spu1"].is<float>())return "invalid_plot_metadata";
  const char *parent=in["parent"]|"",*chain=in["chain"]|"";
  const bool multipart=parent[0] || chain[0];
  const uint32_t part=in["part"]|0UL;
  const bool final=in["final"]|true;
  if(multipart && (!uuid(parent)||!uuid(chain)||!in["part"].is<uint32_t>()||!in["final"].is<bool>()))return "invalid_plot_chain";
  if(!multipart && (part || !final))return "invalid_plot_chain";
  if(uploading_ && (strcmp(parent,pendingParent_) || strcmp(chain,pendingChain_) || part!=pendingPart_ || final!=pendingFinal_))return "plot_upload_in_progress";
  if(!uploading_) {
    if(waiting()) {
      if(!multipart || strcmp(parent,parent_) || strcmp(chain,chain_) || part!=part_+1)return "plot_continuation_mismatch";
    } else if(multipart && part>0) {
      // A committed but unstarted part can be retried after an acknowledgement loss.
      if((strcmp(state_,"ready") && strcmp(state_,"expired")) || strcmp(parent,parent_) || strcmp(chain,chain_) || part!=part_ || strcmp(id,id_))return "plot_continuation_mismatch";
    }
  }
  const uint32_t count=in["count"],crc=in["crc"];
  const int up=in["up"],down=in["down"];
  if(!count || count>PLOT_MAX_BYTES/16 || up<10||up>170||down<10||down>170||up==down ||
     in["spu0"].as<float>()!=motor_spu[0] || in["spu1"].as<float>()!=motor_spu[1])return "invalid_plot_metadata";
  if(uploading_ && !strcmp(id,pendingId_) && count==pendingCount_ && crc==pendingCrc_ &&
     !strcmp(cal,pendingCalibration_) && up==pendingUp_ && down==pendingDown_) {
    lastUploadActivity_=millis();return nullptr;
  }
  if(uploading_)return "plot_upload_in_progress";
  if(active_)return "plot_running";
  if(file_)file_.close();
  // Only an explicit, confirmed new upload may initialize unused storage.
  if(!mount_)mount_=SPIFFS.begin(true);
  if(!mount_)return "storage_unavailable";
  // Replacing the finished/idle file is explicit; no second full file is needed.
  uploadReturnState_=waiting() ? "waiting" : (!strcmp(state_,"completed") ? "completed" : "expired");
  uploading_=ready_=false;cleanupCommitted_=cleanupScratch_=true;
  if(!cleanFiles(true,true))return "plot_storage_cleanup_failed";
  cleanupCommitted_=cleanupScratch_=false;
  if(SPIFFS.totalBytes()-SPIFFS.usedBytes()<count*16+65536)return "plot_storage_full";
  file_=SPIFFS.open("/plot.part","w");
  if(!file_)return "plot_open_failed";
  strlcpy(pendingId_,id,sizeof(pendingId_));strlcpy(pendingCalibration_,cal,sizeof(pendingCalibration_));
  strlcpy(pendingParent_,parent,sizeof(pendingParent_));strlcpy(pendingChain_,chain,sizeof(pendingChain_));
  pendingPart_=part;pendingFinal_=final;
  pendingCount_=count;pendingCrc_=crc;pendingUp_=up;pendingDown_=down;
  pendingSpu_[0]=in["spu0"];pendingSpu_[1]=in["spu1"];
  received_=0;lastOffset_=UINT32_MAX;lastLength_=0;uploading_=true;state_="uploading";lastUploadActivity_=millis();
  return nullptr;
}
const char *PlotStore::chunk(JsonObjectConst in) {
  if(!uploading_)return "no_plot_upload";
  if(!in["offset"].is<uint32_t>()||!in["data"].is<const char*>())return "invalid_plot_chunk";
  uint8_t data[384];size_t length=0;
  const char *encoded=in["data"];
  if(strlen(encoded)>512 || mbedtls_base64_decode(data,sizeof(data),&length,(const unsigned char*)encoded,strlen(encoded)) || !length || length%16)return "invalid_plot_chunk";
  const uint32_t offset=in["offset"];
  if(offset==lastOffset_ && length==lastLength_ && !memcmp(data,lastChunk_,length)) {lastUploadActivity_=millis();return nullptr;}
  if(offset!=received_ || length>pendingCount_*16-received_)return "plot_offset_mismatch";
  if(file_.write(data,length)!=length) {failUpload();return "plot_write_failed";}
  memcpy(lastChunk_,data,length);lastOffset_=offset;lastLength_=length;received_+=length;lastUploadActivity_=millis();
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
        if(!wallMoveAllowed(target))return "plot_outside_calibration";
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
  if(error) {failUpload();return error;}
  StaticJsonDocument<512> doc;
  doc["id"]=pendingId_;doc["cal"]=pendingCalibration_;doc["count"]=pendingCount_;doc["crc"]=pendingCrc_;
  doc["up"]=pendingUp_;doc["down"]=pendingDown_;doc["spu0"]=pendingSpu_[0];doc["spu1"]=pendingSpu_[1];
  File meta=SPIFFS.open("/plot.tmp","w");
  if(!meta || serializeJson(doc,meta)==0) {meta.close();failUpload();return "plot_metadata_failed";}
  meta.flush();meta.close();
  ready_=false;
  SPIFFS.remove("/plot.bin");SPIFFS.remove("/plot.json");
  if(!SPIFFS.rename("/plot.part","/plot.bin") || !SPIFFS.rename("/plot.tmp","/plot.json")) {
    failUpload();ready_=false;cleanupCommitted_=true;return "plot_publish_failed";
  }
  strlcpy(id_,pendingId_,sizeof(id_));strlcpy(calibration_,pendingCalibration_,sizeof(calibration_));
  strlcpy(parent_,pendingParent_,sizeof(parent_));strlcpy(chain_,pendingChain_,sizeof(chain_));
  part_=pendingPart_;final_=pendingFinal_;
  count_=pendingCount_;crc_=pendingCrc_;up_=pendingUp_;down_=pendingDown_;
  spu_[0]=pendingSpu_[0];spu_[1]=pendingSpu_[1];
  ready_=true;uploading_=false;state_="ready";completed_=loaded_=dispatched_=0;run_[0]=0;readySince_=millis();cleanupCommitted_=cleanupScratch_=false;
  return nullptr;
}
const char *PlotStore::start(const char *id,const char *run) {
  if(!uuid(run)||strcmp(id,id_))return "plot_id_mismatch";
  if(!strcmp(run,run_))return nullptr; // A lost start acknowledgement cannot duplicate a drawing.
  if(!ready_ || uploading_ || active_ || waiting())return "plot_not_ready";
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
  if(completed_==count_) {
    active_=ready_=false;state_=final_ ? "completed" : "waiting";file_.close();
    // Keep IDs/progress/chain in RAM for reconnect and duplicate-start safety.
    cleanupCommitted_=true;
  }
}
void PlotStore::stop(const char *reason) {
  if(!active_ && !waiting() && !uploading_ && !ready_)return;
  active_=uploading_=ready_=false;state_=reason;file_.close();
  cleanupCommitted_=cleanupScratch_=true;
}
#endif
