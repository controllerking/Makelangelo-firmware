#include "host_storage/prelude.h"
#include "../src/plot_store.h"
#include <assert.h>
#include <string>
FakeSPIFFS SPIFFS;
uint32_t fakeMillis=0;
float motor_spu[3]={80,80,1};
bool wallPositionKnown(){return true;}
bool wallUserReference(){return true;}
bool wallStopped(){return false;}
const char *wallCalibrationId(){return "22222222-2222-2222-2222-222222222222";}
int wallPenUpAngle(){return 90;}
int wallPenDownAngle(){return 40;}
bool wallMoveAllowed(const float*){return true;}
void wallService(){}
void wallEmergencyStop(){assert(false);}
const char *job="11111111-1111-1111-1111-111111111111";
const char *run="33333333-3333-3333-3333-333333333333";
const char *parent="44444444-4444-4444-4444-444444444444";
const char *chain="55555555-5555-5555-5555-555555555555";
std::string base64(const uint8_t *data,size_t n) {
  const char *alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::string out;unsigned value=0,bits=0;
  for(size_t i=0;i<n;++i){value=(value<<8)|data[i];bits+=8;while(bits>=6){bits-=6;out+=alphabet[(value>>bits)&63];}}
  if(bits)out+=alphabet[(value<<(6-bits))&63];while(out.size()%4)out+='=';return out;
}
void beginUpload(PlotStore &store,int part=-1,bool final=true) {
  PlotRecord records[]={{1,0,0,0},{3,0,0,0}};
  uint32_t crc=plotCrcUpdate(0xffffffffUL,(uint8_t*)records,sizeof(records))^0xffffffffUL;
  StaticJsonDocument<768> d;
  d["job"]=job;d["cal"]=wallCalibrationId();d["count"]=2U;d["crc"]=crc;
  d["up"]=90;d["down"]=40;d["spu0"]=80.f;d["spu1"]=80.f;
  if(part>=0){d["parent"]=parent;d["chain"]=chain;d["part"]=unsigned(part);d["final"]=final;}
  const char *error=store.upload(d.as<JsonObjectConst>());assert(!error);
  d.clear();d["offset"]=0U;d["data"]=base64((uint8_t*)records,sizeof(records));
  assert(!store.chunk(d.as<JsonObjectConst>()));
}
void execute(PlotStore &store) {
  assert(!store.start(job,run));PlotRecord record;uint32_t index;
  while(store.next(record,index))store.dispatched(index);
  store.settle();
}
int main() {
  PlotStore store;store.begin();
  beginUpload(store);assert(!store.commit());assert(SPIFFS.usedBytes()>32);
  execute(store);assert(SPIFFS.usedBytes()>0); // Erases are deferred, not in the motion path.
  store.service();assert(SPIFFS.usedBytes()==0);
  StaticJsonDocument<1024> status;store.status(status.to<JsonObject>());
  assert(status["plot_completed"]==2);assert(!strcmp(status["plot_state"],"completed"));
  assert(!store.start(job,run)); // A lost ACK cannot replay erased commands.
  assert(store.start(job,chain));

  beginUpload(store,0,false);assert(!store.commit());execute(store);store.service();
  assert(store.waiting());assert(SPIFFS.usedBytes()==0);
  beginUpload(store,1,true);assert(!store.commit()); // Chain survives file reclamation.
  store.stop();store.service();assert(SPIFFS.usedBytes()==0);

  // Scratch expiry retains retry identity for the next multipart upload.
  PlotStore partial;partial.begin();beginUpload(partial,0,false);assert(!partial.commit());execute(partial);partial.service();
  beginUpload(partial,1,true);assert(partial.uploading());
  fakeMillis+=PLOT_UPLOAD_IDLE_MS;partial.service();
  assert(!partial.uploading());assert(partial.waiting());assert(SPIFFS.usedBytes()==0);
  beginUpload(partial,1,true);assert(!partial.commit());
  fakeMillis+=PLOT_READY_IDLE_MS;partial.service();assert(SPIFFS.usedBytes()==0);
  beginUpload(partial,1,true);assert(!partial.commit());partial.stop();partial.service();

  PlotStore idle;idle.begin();beginUpload(idle);assert(!idle.commit());
  fakeMillis+=PLOT_READY_IDLE_MS;idle.service();assert(SPIFFS.usedBytes()==0);
  assert(idle.start(job,run));

  // Corrupt commits reclaim scratch; failed erases are visible and retried.
  PlotStore broken;broken.begin();beginUpload(broken);
  (*SPIFFS.files["/plot.part"])[4]=1;
  assert(broken.commit());broken.service();assert(SPIFFS.usedBytes()==0);
  beginUpload(broken);SPIFFS.rejectRenameTo="/plot.json";
  assert(broken.commit());assert(SPIFFS.exists("/plot.bin"));broken.service();
  assert(SPIFFS.usedBytes()==0);SPIFFS.rejectRenameTo="";
  beginUpload(broken);assert(!broken.commit());broken.stop();
  SPIFFS.rejectRemoves=true;broken.service();
  broken.status(status.to<JsonObject>());assert(status["plot_cleanup_error"]==true);
  assert(status["plot_cleanup_pending"]==true);assert(SPIFFS.usedBytes()>0);
  SPIFFS.rejectRemoves=false;fakeMillis+=1000;broken.service();assert(SPIFFS.usedBytes()==0);

  // Reboot keeps a complete unstarted file, removes abandoned scratch/orphans.
  beginUpload(broken);assert(!broken.commit());
  SPIFFS.open("/plot.part","w").write(uint8_t(1));
  SPIFFS.open("/plot.tmp","w").write(uint8_t(1));
  PlotStore rebooted;rebooted.begin();assert(!SPIFFS.exists("/plot.part"));assert(!SPIFFS.exists("/plot.tmp"));
  assert(SPIFFS.exists("/plot.bin"));rebooted.stop();rebooted.service();
  SPIFFS.open("/plot.bin","w").write(uint8_t(1));
  PlotStore orphan;orphan.begin();assert(SPIFFS.usedBytes()==0);
  SPIFFS.open("/unrelated.bin","w").write(uint8_t(7));
  beginUpload(orphan);assert(!orphan.commit());execute(orphan);orphan.service();
  assert(SPIFFS.exists("/unrelated.bin"));assert(SPIFFS.usedBytes()==1);
  assert(plotIdleExpired(10,UINT32_MAX-10,20));
}
