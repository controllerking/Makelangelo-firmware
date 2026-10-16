#include "configure.h"
#include "motion_control.h"
#ifdef TARGET_ESP32
#include "wireless.h"
#include "wall_polargraph.h"
#include "wire_protocol.h"
#include "user_calibration_math.h"
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include <ArduinoJson.h>
#include <esp_system.h>
#include <lwip/sockets.h>
#include "plot_store.h"
#include <errno.h>

namespace {
constexpr unsigned queueCapacity = 8;
constexpr uint32_t heartbeatTimeout = 5000;
Preferences prefs;
WebServer portal(80);
DNSServer dns;
WiFiServer server(9999);
WiFiClient client;
String setupName, setupPassword, pairToken, portalNonce, bootId, session;
String savedSsid[3], savedPassword[3];
bool started = false, apActive = false, authenticated = false;
bool socketAssigned = false;
bool polling = false, dispatching = false, hold = false, paused = false;
bool penSettling = false, restoring = false;
int heldPen = PEN_UP_ANGLE;
uint32_t lastSeen = 0, lastStatus = 0, joinStarted = 0, retryAt = 0, onlineSince = 0;
uint32_t settleUntil = 0, lastDispatched = 0;
bool joining = false, scanRunning = false;
int attemptedNetwork = -1;
uint32_t failedUntil[3] = {0, 0, 0};
char line[1024];
size_t lineLength = 0;
bool overflow = false;
WireLedger ledger;
struct Command {
  uint32_t id;
  uint32_t plotIndex;
  char op[12];
  float x, y, feed;
  int angle, penUp, penDown;
  int axis, steps;
  float width, left, right, bounds[4];
  char calibrationId[37];
};
Command queue[queueCapacity];
unsigned head = 0, count = 0;
String lastError;
char tx[16384];size_t txHead=0,txSize=0;uint32_t txProgress=0;

String randomHex(unsigned bytes) {
  String out;
  const char hex[] = "0123456789abcdef";
  for (unsigned i = 0; i < bytes; ++i) {
    uint8_t v = uint8_t(esp_random());
    out += hex[v >> 4]; out += hex[v & 15];
  }
  return out;
}
bool idle() { return !planner.movesPlanned() && !dispatching && !wallIsHoming(); }
void lostConnection();
void flushTx() {
  if(!txSize || !client.connected())return;
  const size_t contiguous=_MIN(txSize,sizeof(tx)-txHead);
  const int n=send(client.fd(),tx+txHead,contiguous,MSG_DONTWAIT);
  if(n>0) {txHead=(txHead+n)%sizeof(tx);txSize-=n;txProgress=millis();}
  else if(n<0 && errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR)lostConnection();
  else if(uint32_t(millis()-txProgress)>2000)lostConnection();
}
void writeJson(JsonDocument &doc) {
  if (!client.connected()) return;
  // WiFiClient::write can wait for seconds on a non-reading peer. Never let
  // telemetry block motion service: a short/failed nonblocking write loses
  // the link and enters the same drain/pen-up path as Wi-Fi loss.
  char outgoing[2048];
  if (doc.overflowed() || measureJson(doc) + 1 >= sizeof(outgoing)) {
    lostConnection(); return;
  }
  size_t n = serializeJson(doc, outgoing, sizeof(outgoing) - 1);
  outgoing[n++] = '\n';
  flushTx();
  if(!client.connected())return;
  if(txSize>4096 && String(doc["type"]|"")=="status")return; // Coalesce telemetry, never acknowledgements.
  if(n>sizeof(tx)-txSize) {lostConnection();return;}
  if(!txSize)txProgress=millis();
  for(size_t i=0;i<n;++i)tx[(txHead+txSize+i)%sizeof(tx)]=outgoing[i];
  txSize+=n;flushTx();
}
void state(JsonObject out) {
  out["boot"] = bootId;
  out["session"] = session;
  out["next"] = ledger.next;
  out["accepted"] = ledger.next - 1;
  out["completed"] = ledger.completed;
  out["queue_free"] = queueCapacity - count;
  out["planner_free"] = Planner::movesFree();
  out["homed"] = wallPositionKnown();
  out["reference"] = wallUserReference() ? "user" : (wallPositionKnown() ? "switches" : "unknown");
  out["calibration_api"] = 1;
  out["switch_homing_enabled"] = bool(WALL_HOMING_CONFIRMED);
  out["calibrating"] = wallCalibrationActive();
  out["calibration_id"] = wallCalibrationId();
  JsonArray counts = out.createNestedArray("jog_steps");
  JsonArray scale = out.createNestedArray("steps_per_mm");
  for (int i=0;i<2;++i) { counts.add(wallCalibrationSteps(i)); scale.add(motor_spu[i]); }
  if (wallUserReference()) {
    JsonArray bounds=out.createNestedArray("draw_bounds");
    for (int i=0;i<4;++i) bounds.add(wallDrawingBound(i));
  }
  out["fault"] = wallStopped();
  out["paused"] = paused;
  out["holding"] = hold;
  out["busy"] = bool(count || planner.movesPlanned() || dispatching || plotStore.active() || plotStore.uploading());
  out["moving"] = bool(planner.movesPlanned() || dispatching || restoring || wallIsHoming());
  out["homing"] = wallIsHoming();
  out["x"] = axies[0].pos; out["y"] = axies[1].pos;
  out["pen"] = servos[0].read();
  out["pen_up"] = wallPenUpAngle(); out["pen_down"] = wallPenDownAngle();
  out["pen_calibration_api"]=1;out["pen_calibrated"]=wallPenCalibrated();
  out["pen_tuning"]=wallPenTuning();
  out["speed_control_api"]=1;
  out["stepper_percent"]=motionStepperPercent();
  out["stepper_percent_actual"]=motionStepperPermille()/10.0f;
  out["servo_speed"]=motionServoSpeed();
  out["position_kind"] = planner.movesPlanned() ? "planned" : "settled";
  JsonArray limits = out.createNestedArray("limits");
  for (int i = 0; i < 2; ++i) {
    JsonArray a = limits.createNestedArray();
    a.add(axies[i].limitMin); a.add(axies[i].limitMax);
  }
  out["error"] = lastError;
  plotStore.status(out);
}
void status(const char *type = "status") {
  DynamicJsonDocument doc(4096);
  doc["type"] = type;
  state(doc.as<JsonObject>());
  writeJson(doc);
}
void error(const char *message, uint32_t id = 0) {
  StaticJsonDocument<256> doc;
  doc["type"] = "error"; doc["error"] = message; doc["id"] = id;
  doc["next"] = ledger.next;
  writeJson(doc);
}
void requestHold() {
  hold = true;
  wallCalibrationAbort();
  if (wallIsHoming()) wallEmergencyStop();
}
void lostConnection() {
  if (!plotStore.active() && authenticated && (count || planner.movesPlanned() || wallCalibrationActive() || wallPenTuning() || servos[0].read() != wallPenUpAngle()))
    requestHold();
  authenticated = false;
  socketAssigned = false;
  lineLength = 0; overflow = false;
  txHead=txSize=0;
  client.stop();
}
void acknowledge(uint32_t id, bool duplicate) {
  DynamicJsonDocument doc(4096);
  doc["type"] = "ack"; doc["id"] = id; doc["duplicate"] = duplicate;
  state(doc.as<JsonObject>()); writeJson(doc);
}
bool validSession(const String &s) {
  if (s.length() != 36) return false;
  for (unsigned i = 0; i < s.length(); ++i)
    if (!isxdigit(s[i]) && s[i] != '-') return false;
  return true;
}
void handleLine(const char *raw) {
  StaticJsonDocument<1536> doc;
  if (deserializeJson(doc, raw)) { error("invalid_json"); return; }
  const String type = doc["type"] | "";
  if (type == "hello") {
    const String candidate = doc["session"] | "";
    if (String(doc["token"] | "") != pairToken || !validSession(candidate)) {
      error("unauthorized"); client.stop(); return;
    }
    if (session.length() && session != candidate &&
        (count || planner.movesPlanned() || hold || plotStore.active() || plotStore.uploading() || ledger.completed != ledger.next - 1)) {
      error("session_busy"); client.stop(); return;
    }
    if (session != candidate) {
      session = candidate; ledger.reset(); lastDispatched = 0;
    }
    authenticated = true; lastSeen = millis(); status("hello"); return;
  }
  if (!authenticated) { error("hello_required"); client.stop(); return; }
  lastSeen = millis();
  if (type == "ping" || type == "status") { status(); return; }
  if(type.startsWith("plot_")) {
    DynamicJsonDocument reply(4096);
    reply["request"]=doc["request"]|"";
    const char *failure=nullptr;
    if(String(doc["boot"]|"")!=bootId || wallStopped())failure="plot_boot_or_fault";
    else if(type=="plot_start" && plotStore.active())failure=plotStore.start(doc["job"]|"",doc["run"]|"");
    else if(count || !idle() || hold || paused || wallCalibrationActive() || wallPenTuning() || plotStore.active())failure="plot_busy";
    else if(type=="plot_begin") {
      if(doc["confirm"]!=true || !wallUserReference())failure="plot_confirmation_or_reference_required";
      else failure=plotStore.upload(doc.as<JsonObjectConst>());
    } else if(type=="plot_chunk")failure=plotStore.chunk(doc.as<JsonObjectConst>());
    else if(type=="plot_commit")failure=plotStore.commit();
    else if(type=="plot_start") {
      if(doc["confirm"]!=true)failure="confirmation_required";
      else failure=plotStore.start(doc["job"]|"",doc["run"]|"");
    } else failure="unknown_plot_operation";
    if(failure) {reply["type"]="error";reply["error"]=failure;}
    else {reply["type"]="control";reply["op"]=type;state(reply.as<JsonObject>());}
    writeJson(reply);return;
  }
  if (type=="speeds") {
    // Out of band: never wait behind the drawing FIFO or consume command IDs.
    DynamicJsonDocument reply(4096);
    reply["request"]=doc["request"] | "";
    if (String(doc["boot"] | "")!=bootId || wallStopped() ||
        !doc["stepper_percent"].is<int>() || !doc["servo_speed"].is<float>() ||
        !motionSetSpeeds(doc["stepper_percent"],doc["servo_speed"])) {
      reply["type"]="error";reply["error"]="invalid_speed_or_fault";
    } else {
      reply["type"]="control";reply["op"]="speeds";state(reply.as<JsonObject>());
    }
    writeJson(reply);return;
  }
  if (type == "pause" || type == "resume" || type == "stop") {
    if (type == "pause") requestHold();
    if (type == "stop") {
      wallEmergencyStop(); count = 0; penSettling = restoring = false;
      plotStore.stop();
      hold = true; paused = true; lastError = "emergency_stop";
    }
    if (type == "resume") {
      if (String(doc["boot"] | "") != bootId || wallStopped() || !wallPositionKnown() ||
          !paused || !idle()) { error("resume_not_safe"); return; }
      // Restore contact at the exact retained position before continuing paths.
      motor.setPenAngle(heldPen); servos[0].update();
      restoring = true; settleUntil = millis() + 300;
      hold = false; paused = false;
    }
    DynamicJsonDocument reply(4096);
    reply["type"] = "control"; reply["request"] = doc["request"] | "";
    reply["op"] = type; state(reply.as<JsonObject>()); writeJson(reply); return;
  }
  if (type != "command") { error("unknown_type"); return; }
  if(plotStore.active() || plotStore.uploading()) {error("stored_plot_owns_motion");return;}
  if (String(doc["boot"] | "") != bootId) { error("boot_changed"); return; }
  if (!doc["id"].is<uint32_t>()) { error("invalid_id"); return; }
  const uint32_t id = doc["id"];
  const uint32_t hash = WireLedger::fingerprint(raw);
  auto decision = ledger.inspect(id, hash);
  if (decision == WireLedger::Duplicate) { acknowledge(id, true); return; }
  if (decision != WireLedger::New) {
    error(decision == WireLedger::Conflict ? "id_conflict" :
      decision == WireLedger::Stale ? "stale_id" : "out_of_order", id); return;
  }
  if (wallStopped()) { error("fault", id); return; }
  const String op = doc["op"] | "";
  const bool calibrationCommand = op == "cal_begin" || op == "cal_jog" || op == "cal_apply";
  const bool penCommand=op=="cal_pen" || op=="pen_config" || op=="pen_end";
  if ((hold || paused) && op != "cal_begin" && op != "cal_apply" && !penCommand) { error("paused", id); return; }
  if (penCommand && (!wallHardwareReady() || count || !idle() || wallCalibrationActive())) { error("calibration_busy",id); return; }
  if (wallPenTuning() && !penCommand && op!="sync" && op!="pen") { error("pen_calibration_active",id); return; }
  if (calibrationCommand && (count || !idle())) { error("calibration_busy",id); return; }
  if (wallCalibrationActive() && !calibrationCommand && op != "sync" && op != "pen") {
    error("calibration_active",id); return;
  }
  if (count == queueCapacity) { error("queue_full", id); return; }
  Command cmd = {};
  cmd.id = id;
  if (penCommand) {
    if (!doc["confirm"].is<bool>() || !doc["confirm"].as<bool>()) { error("confirmation_required",id); return; }
    if (op=="cal_pen") {
      if (!doc["angle"].is<int>() || doc["angle"].as<int>()<10 || doc["angle"].as<int>()>170) { error("invalid_pen",id); return; }
      cmd.angle=doc["angle"];
    } else if (op=="pen_config") {
      if (!doc["up"].is<int>() || !doc["down"].is<int>()) { error("invalid_pen",id); return; }
      cmd.penUp=doc["up"];cmd.penDown=doc["down"];
      if (cmd.penUp<10 || cmd.penUp>170 || cmd.penDown<10 || cmd.penDown>170 || cmd.penUp==cmd.penDown) { error("invalid_pen",id); return; }
    }
  } else if (op == "cal_begin") {
    if (!doc["confirm"].is<bool>() || !doc["confirm"].as<bool>()) { error("confirmation_required",id); return; }
  } else if (op == "cal_jog") {
    if (!wallCalibrationActive() || !doc["axis"].is<int>() || !doc["steps"].is<int>()) { error("invalid_jog",id); return; }
    cmd.axis=doc["axis"]; cmd.steps=doc["steps"];
    if (cmd.axis < 0 || cmd.axis > 1 || cmd.steps == 0 || cmd.steps < -4000 || cmd.steps > 4000) { error("invalid_jog",id); return; }
  } else if (op == "cal_apply") {
    const char *fields[]={"width","l","r","xmin","ymin","xmax","ymax"};
    for (const char *field:fields) if (!doc[field].is<float>() || !isfinite(doc[field].as<float>())) { error("invalid_calibration",id); return; }
    if (!doc["confirm"].is<bool>() || !doc["confirm"].as<bool>()) { error("confirmation_required",id); return; }
    cmd.width=doc["width"]; cmd.left=doc["l"]; cmd.right=doc["r"];
    cmd.bounds[0]=doc["xmin"]; cmd.bounds[1]=doc["ymin"]; cmd.bounds[2]=doc["xmax"]; cmd.bounds[3]=doc["ymax"];
    const String cid=doc["cal_id"] | "";
    if (cid.length()!=36 || !userCalibrationBounds(cmd.width,cmd.bounds[0],cmd.bounds[1],cmd.bounds[2],cmd.bounds[3])) { error("invalid_calibration",id); return; }
    cid.toCharArray(cmd.calibrationId,sizeof(cmd.calibrationId));
    for (int i=0;i<36;++i) if (!isxdigit(cmd.calibrationId[i]) && cmd.calibrationId[i]!='-') { error("invalid_calibration",id); return; }
  } else if (op == "move") {
    if (!doc["x"].is<float>() || !doc["y"].is<float>() || !doc["feed"].is<float>()) {
      error("invalid_move", id); return;
    }
    cmd.x = doc["x"]; cmd.y = doc["y"]; cmd.feed = doc["feed"];
    float target[NUM_AXIES] = {cmd.x, cmd.y, float(wallPenUpAngle())};
    if (!isfinite(cmd.feed) || cmd.feed < 0.1f || cmd.feed > 30 ||
        !wallMoveAllowed(target)) { error("invalid_move_or_unhomed", id); return; }
  } else if (op == "pen") {
    if (!doc["angle"].is<int>()) { error("invalid_pen", id); return; }
    cmd.angle = doc["angle"];
    if (cmd.angle < axies[2].limitMin || cmd.angle > axies[2].limitMax ||
        (cmd.angle != wallPenUpAngle() && !wallPositionKnown())) { error("invalid_pen", id); return; }
  } else if (op != "home" && op != "sync") { error("unknown_operation", id); return; }
  op.toCharArray(cmd.op, sizeof(cmd.op));
  queue[(head + count) % queueCapacity] = cmd; ++count;
  if (op=="cal_begin" || op=="cal_apply" || penCommand) { hold=paused=false; restoring=penSettling=false; }
  ledger.accept(hash); acknowledge(id, false);
}
void beginSetup() {
  if (apActive) return;
  WiFi.mode(WIFI_AP_STA);
  apActive = WiFi.softAP(setupName.c_str(), setupPassword.c_str());
  if (apActive) {
    dns.start(53, "*", WiFi.softAPIP());
    SERIAL_ECHOLNPGM("Wi-Fi setup network:");
    MYSERIAL1.println(setupName.c_str());
    SERIAL_ECHOLNPGM("Setup WPA2 password (generated on this device):");
    MYSERIAL1.println(setupPassword.c_str());
    SERIAL_ECHOLNPGM("Open http://192.168.4.1");
  }
}
bool setupClient() {
  return apActive && portal.client().localIP() == WiFi.softAPIP();
}
void portalReply(int code, const String &body, const char *mime = "application/json") {
  portal.sendHeader("Cache-Control", "no-store");
  portal.send(code, mime, body);
}
const char setupPage[] PROGMEM = R"HTML(<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Drawy Wi-Fi setup</title><style>body{font:17px system-ui;background:#f5f1e9;color:#263f35;max-width:560px;margin:40px auto;padding:24px}input,button{font:inherit;padding:12px;box-sizing:border-box;width:100%;margin:8px 0}button{background:#263f35;color:white;border:0;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}label{display:block;margin-top:18px}</style><h1>Connect your drawing robot</h1><p>Select a 2.4 GHz network or enter a hidden network name. Your password is saved on the robot.</p><form id="setup"><label>Network name<input id="ssid" list="networks" maxlength="32" required autocomplete="off"></label><datalist id="networks"></datalist><label>Network password<input id="password" type="password" maxlength="63" autocomplete="new-password"></label><button>Save and connect</button></form><pre id="result"></pre><h2>Pair your computer</h2><p>Copy this device key into the computer controller. It is separate from your Wi-Fi password.</p><pre id="key"></pre><script>let nonce='';async function info(){let d=await(await fetch('/info')).json();nonce=d.nonce;document.querySelector('#key').textContent=d.token;document.querySelector('#result').textContent=d.connected?'Connected: '+d.ip+' (drawy.local), TCP 9999':'Waiting for a known network';}async function scan(){let d=await(await fetch('/scan')).json();let list=document.querySelector('#networks');list.replaceChildren(...d.networks.map(n=>{let o=document.createElement('option');o.value=n;return o}));}document.querySelector('#setup').onsubmit=async e=>{e.preventDefault();let r=await fetch('/networks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nonce,ssid:document.querySelector('#ssid').value,password:document.querySelector('#password').value})});document.querySelector('#password').value='';document.querySelector('#result').textContent=await r.text()};info();scan();setInterval(info,3000);setInterval(scan,10000)</script></html>)HTML";
void setupRoutes() {
  portal.on("/", HTTP_GET, [] {
    if (!setupClient()) { portalReply(403, "{}"); return; }
    portalReply(200, FPSTR(setupPage), "text/html");
  });
  portal.on("/info", HTTP_GET, [] {
    if (!setupClient()) { portalReply(403, "{}"); return; }
    StaticJsonDocument<512> d;
    d["nonce"] = portalNonce; d["token"] = pairToken;
    d["connected"] = WiFi.status() == WL_CONNECTED;
    d["ip"] = WiFi.localIP().toString();
    String out; serializeJson(d, out); portalReply(200, out);
  });
  portal.on("/scan", HTTP_GET, [] {
    if (!setupClient()) { portalReply(403, "{}"); return; }
    StaticJsonDocument<1536> d;
    JsonArray networks = d.createNestedArray("networks");
    int n = WiFi.scanComplete();
    if (n >= 0) {
      for (int i = 0; i < n && i < 24; ++i) networks.add(WiFi.SSID(i));
    }
    String out; serializeJson(d, out); portalReply(200, out);
    if (n != WIFI_SCAN_RUNNING && !joining) {
      WiFi.scanDelete(); WiFi.scanNetworks(true); scanRunning = true;
    }
  });
  portal.on("/networks", HTTP_POST, [] {
    if (!setupClient()) { portalReply(403, "{}"); return; }
    StaticJsonDocument<512> d;
    if (portal.arg("plain").length() > 384 || deserializeJson(d, portal.arg("plain")) ||
        String(d["nonce"] | "") != portalNonce) { portalReply(400, "Invalid setup request"); return; }
    String ssid = d["ssid"] | "", password = d["password"] | "";
    if (!ssid.length() || ssid.length() > 32 || password.length() > 63 ||
        (password.length() && password.length() < 8)) {
      portalReply(400, "Use a network name and an 8–63 character password, or blank for an open network."); return;
    }
    // Move this network to the front, retaining up to two other known networks.
    int existing = -1;
    for (int i = 0; i < 3; ++i) if (savedSsid[i] == ssid) existing = i;
    if (existing < 0) existing = 2;
    for (int i = existing; i > 0; --i) {
      savedSsid[i] = savedSsid[i-1]; savedPassword[i] = savedPassword[i-1];
    }
    savedSsid[0] = ssid; savedPassword[0] = password;
    for (auto &deadline : failedUntil) deadline = 0;
    for (int i = 0; i < 3; ++i) {
      prefs.putString(("ssid" + String(i)).c_str(), savedSsid[i]);
      prefs.putString(("pass" + String(i)).c_str(), savedPassword[i]);
    }
    WiFi.disconnect(false, false);
    WiFi.begin(ssid.c_str(), password.c_str());
    attemptedNetwork = 0;
    joining = true; joinStarted = millis(); retryAt = millis() + 30000;
    portalReply(200, "Saved. Connecting; this page will show the address when ready.");
  });
  portal.onNotFound([] {
    if (!setupClient()) { portalReply(403, "{}"); return; }
    portal.sendHeader("Location", "http://192.168.4.1/");
    portalReply(302, "");
  });
  portal.begin();
}
void networkMaintenance() {
  const uint32_t now = millis();
  if (WiFi.status() == WL_CONNECTED) {
    joining = false;
    if (!onlineSince) {
      onlineSince = now;
      MYSERIAL1.print("Wi-Fi connected: "); MYSERIAL1.println(WiFi.localIP().toString().c_str());
      MDNS.end();
      MDNS.begin("drawy");
      MDNS.addService("drawy", "tcp", 9999);
    }
    if (apActive && uint32_t(now - onlineSince) > 60000) {
      dns.stop(); WiFi.softAPdisconnect(true); apActive = false; WiFi.mode(WIFI_STA);
    }
  } else {
    onlineSince = 0;
    if (joining && uint32_t(now - joinStarted) > 15000) {
      if (attemptedNetwork >= 0) failedUntil[attemptedNetwork] = now + 60000;
      joining = false; beginSetup();
    }
    if (!joining && int32_t(now - retryAt) >= 0) {
      int results = WiFi.scanComplete();
      if (results == WIFI_SCAN_RUNNING) { scanRunning = true; return; }
      if (!scanRunning) { WiFi.scanNetworks(true); scanRunning = true; return; }
      scanRunning = false;
      int best = -1, strength = -1000;
      for (int i = 0; i < results; ++i)
        for (int j = 0; j < 3; ++j)
          if (savedSsid[j].length() && int32_t(now - failedUntil[j]) >= 0 &&
              savedSsid[j] == WiFi.SSID(i) && WiFi.RSSI(i) > strength) {
            best = j; strength = WiFi.RSSI(i);
          }
      // Also try the first saved network (it may have a hidden SSID).
      if (best < 0)
        for (int j = 0; j < 3; ++j)
          if (savedSsid[j].length() && int32_t(now - failedUntil[j]) >= 0) { best = j; break; }
      if (best >= 0) {
        WiFi.begin(savedSsid[best].c_str(), savedPassword[best].c_str());
        attemptedNetwork = best;
        joining = true; joinStarted = now;
      }
      retryAt = now + 30000;
      beginSetup();
    }
  }
  // Provisioning HTTP may block on slow clients: serve only when motion is idle.
  if (apActive && idle() && !count && !authenticated) {
    dns.processNextRequest(); portal.handleClient();
  }
}
}
void wirelessBegin() {
  plotStore.begin();
  if (started) return;
  started = true;
  WiFi.persistent(false); WiFi.setHostname("drawy"); WiFi.mode(WIFI_STA); WiFi.setSleep(false);
  bootId = randomHex(8); portalNonce = randomHex(16);
  prefs.begin("drawy-wifi", false);
  setupPassword = prefs.getString("setup-pass", "");
  pairToken = prefs.getString("pair-key", "");
  if (!setupPassword.length()) { setupPassword = randomHex(8); prefs.putString("setup-pass", setupPassword); }
  if (!pairToken.length()) { pairToken = randomHex(16); prefs.putString("pair-key", pairToken); }
  setupName = "Drawy-Setup-" + String(uint32_t(ESP.getEfuseMac()) & 0xffffff, HEX);
  for (int i = 0; i < 3; ++i) {
    savedSsid[i] = prefs.getString(("ssid" + String(i)).c_str(), "");
    savedPassword[i] = prefs.getString(("pass" + String(i)).c_str(), "");
  }
  setupRoutes(); server.begin(); server.setNoDelay(true);
  if (savedSsid[0].length()) {
    WiFi.begin(savedSsid[0].c_str(), savedPassword[0].c_str());
    attemptedNetwork = 0;
    joining = true; joinStarted = millis(); retryAt = millis() + 30000;
  } else beginSetup();
}
bool wirelessOwnsMotion() { return authenticated || count || hold || plotStore.active() || plotStore.uploading(); }
bool wirelessHoldMotion() { return hold; }
bool wirelessSetupRequested(const char *raw) {
  if (strcmp(raw, "WIFI SETUP")) return false;
  if (!idle() || count || plotStore.active() || plotStore.uploading()) { SERIAL_ECHOLNPGM("Finish/stop the job before Wi-Fi setup."); return true; }
  beginSetup();
  // Also repeat details when setup was already advertising before USB opened.
  MYSERIAL1.println(setupName.c_str());
  MYSERIAL1.println(setupPassword.c_str());
  SERIAL_ECHOLNPGM("Open http://192.168.4.1");
  onlineSince = millis(); // Keep setup visible for a full minute if already connected.
  return true;
}
void wirelessPoll() {
  if (!started || polling) return;
  polling = true;
  flushTx();
  networkMaintenance();
  if (socketAssigned && (!client.connected() ||
      (authenticated && WiFi.status() != WL_CONNECTED && client.localIP() != WiFi.softAPIP())))
    lostConnection();
  if (!socketAssigned) {
    WiFiClient incoming = server.available();
    if (incoming) {
      client = incoming; client.setNoDelay(true);
      socketAssigned = true;
      lastSeen = millis(); authenticated = false; lineLength = 0; overflow = false;
    }
  } else {
    WiFiClient extra = server.available();
    if (extra) extra.stop();
  }
  unsigned budget = 512;
  while (client.connected() && client.available() && budget--) {
    const char c = client.read();
    if (c == '\r') continue;
    if (c == '\n') {
      line[lineLength] = 0;
      if (overflow) error("line_too_long");
      else if (lineLength) {handleLine(line);lastSeen=millis();} // Own flash work must not trigger a heartbeat timeout.
      lineLength = 0; overflow = false;
    } else if (lineLength < sizeof(line) - 1) line[lineLength++] = c;
    else overflow = true;
  }
  if (client.connected() && uint32_t(millis() - lastSeen) > heartbeatTimeout) lostConnection();
  if (authenticated && uint32_t(millis() - lastStatus) > 250) {
    lastStatus = millis(); status();
  }
  flushTx();
  polling = false;
}
void wirelessAdvance() {
  if (!started || dispatching) return;
  if (wallStopped()) {
    plotStore.stop("fault");
    count = 0; hold = paused = true; penSettling = restoring = false; return;
  }
  if (!planner.movesPlanned()) ledger.finish(lastDispatched);
  if(!planner.movesPlanned() && !penSettling)plotStore.settle();
  if (hold) {
    if (!planner.movesPlanned() && !paused) {
      heldPen = servos[0].read();
      motor.setPenAngle(wallPenUpAngle()); servos[0].update();
      paused = true; penSettling = restoring = false;
      status();
    }
    return;
  }
  if (restoring) {
    if (servos[0].moving()) { settleUntil=millis()+300; return; }
    if (int32_t(millis() - settleUntil) < 0) return;
    restoring = false;
  }
  if(!count && plotStore.active()) {
    PlotRecord record;uint32_t index;
    if(plotStore.next(record,index)) {
      Command cmd={};cmd.plotIndex=index;
      if(record.op==0) {strcpy(cmd.op,"move");cmd.x=record.x;cmd.y=record.y;cmd.feed=record.feed;}
      else if(record.op==3)strcpy(cmd.op,"sync");
      else {strcpy(cmd.op,"pen");cmd.angle=record.op==1 ? wallPenUpAngle() : wallPenDownAngle();}
      queue[head]=cmd;count=1;
    }
  }
  if (!count) return;
  Command &cmd = queue[head];
  if (!strcmp(cmd.op,"cal_begin") || !strcmp(cmd.op,"cal_jog") || !strcmp(cmd.op,"cal_apply")) {
    if (planner.movesPlanned()) return;
    dispatching=true;
    bool ok=false;
    if (!strcmp(cmd.op,"cal_begin")) {
      ok=wallCalibrationBegin();
      if (ok) { hold=paused=false; heldPen=wallPenUpAngle(); lastError=""; }
    } else if (!strcmp(cmd.op,"cal_jog")) ok=wallCalibrationJog(cmd.axis,cmd.steps);
    else {
      ok=wallSetUserReference(cmd.width,cmd.left,cmd.right,cmd.bounds,cmd.calibrationId);
      if (ok) { hold=paused=false; heldPen=wallPenUpAngle(); lastError=""; }
    }
    dispatching=false;
    if (!ok) { lastError="calibration_failed"; wallInvalidatePosition(); requestHold(); }
    if (wallStopped() || !count) return;
    lastDispatched=cmd.id; head=(head+1)%queueCapacity; --count;
    ledger.finish(lastDispatched); status(); return;
  }
  if (penSettling) {
    if (servos[0].moving()) { settleUntil=millis()+300; return; }
    if (int32_t(millis() - settleUntil) < 0) return;
    penSettling = false;
  } else if (!strcmp(cmd.op,"cal_pen") || !strcmp(cmd.op,"pen_config") || !strcmp(cmd.op,"pen_end")) {
    if (planner.movesPlanned()) return;
    if (!strcmp(cmd.op,"pen_config")) {
      if (!wallSavePenAngles(cmd.penUp,cmd.penDown)) { lastError="pen_save_failed";requestHold();return; }
    }
    wallSetPenTuning(!strcmp(cmd.op,"cal_pen"));
    motor.setPenAngle(!strcmp(cmd.op,"cal_pen") ? cmd.angle : wallPenUpAngle());servos[0].update();
    penSettling=true;settleUntil=millis()+300;return;
  } else if (!strcmp(cmd.op, "pen")) {
    if (planner.movesPlanned()) return;
    motor.setPenAngle(cmd.angle); servos[0].update();
    penSettling = true; settleUntil = millis() + 300; return;
  } else if (!strcmp(cmd.op, "sync")) {
    if (planner.movesPlanned()) return;
  } else if (!strcmp(cmd.op, "home")) {
    if (planner.movesPlanned()) return;
    dispatching = true;
    const bool ok = wallHome();
    dispatching = false;
    if (!ok) { lastError = "home_failed"; requestHold(); return; }
  } else if (!strcmp(cmd.op, "move")) {
    if (!wallPositionKnown()) { lastError = "position_unknown"; requestHold(); return; }
    float target[NUM_AXIES] = {cmd.x, cmd.y, axies[2].pos};
    dispatching = true;
    planner.bufferLine(target, cmd.feed);
    dispatching = false;
    if (wallStopped() || !count) return;
    if (hold && (fabsf(axies[0].pos - cmd.x) > 0.001f || fabsf(axies[1].pos - cmd.y) > 0.001f))
      return; // Retain the unplanned remainder for explicit same-boot resume.
  }
  if(cmd.plotIndex)plotStore.dispatched(cmd.plotIndex);
  else lastDispatched = cmd.id;
  head = (head + 1) % queueCapacity; --count;
  if (!planner.movesPlanned()) ledger.finish(lastDispatched);
}
#endif
