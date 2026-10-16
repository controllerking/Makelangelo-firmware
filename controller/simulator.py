"""A hardware-free protocol simulator for tests and UI development."""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import json
import secrets
import time
import math
import base64
import zlib
from .plot import RECORD,MAX_BYTES

class SimulatedRobot:
    def __init__(self, token="simulation-only", delay=.04, storage=False):
        self.token, self.delay = token, delay
        self.boot, self.session = secrets.token_hex(8), ""
        self.next, self.completed = 1, 0
        self.receipts, self.queue, self.executions = {}, [], []
        self.homed, self.fault, self.hold, self.paused = False, False, False, False
        self.x, self.y, self.pen = 400., -200., 90
        self.held_pen = 90
        self.pen_up,self.pen_down=90,40
        self.pen_calibrated=self.pen_tuning=False
        self.stepper_percent,self.servo_speed=100,35
        self.drop_plot_ack=None
        self.plot_starts=[]
        self.plot_upload_idle=120.;self.plot_ready_idle=600.
        self.plot_last_upload=0.;self.plot_ready_since=0.;self.plot_return_state="expired"
        self.plot_capacity=MAX_BYTES
        self.storage=storage;self.plot_meta=None;self.plot_data=bytearray();self.plot_saved=None
        self.plot_running=False;self.plot_state="empty";self.plot_run="";self.plot_completed=0;self.plot_due=0
        self.writer = None
        self.authenticated = False
        self.drop_next_ack = False
        self.suppress_next_ack = False
        self.busy_until = 0.
        self.active_command = None
        self.server = self.task = None
        self.last_seen = time.monotonic()
        self.heartbeat_timeout = 5
        self.error = ""
        self.calibrating=False
        self.jog_steps=[0,0]
        self.reference="unknown"
        self.calibration_id=""
        self.draw_bounds=None
        self.limits=[[0,1000],[-1200,0]]

    async def start(self, port=0):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", port)
        self.port = self.server.sockets[0].getsockname()[1]
        self.task = asyncio.create_task(self.tick())
        return self

    def state(self, kind="status"):
        return {"type":kind,"boot":self.boot,"session":self.session,"next":self.next,
                "accepted":self.next-1,"completed":self.completed,"queue_free":8-len(self.queue),
                "planner_free":15,"homed":self.homed,"fault":self.fault,"paused":self.paused,
                "holding":self.hold,"busy":bool(self.queue or self.active_command or self.plot_running or self.plot_state=="waiting" or self.plot_meta),
                "moving":bool(self.active_command or (self.plot_running and not self.paused)),"homing":False,"x":self.x,"y":self.y,
                "pen":self.pen,"pen_up":self.pen_up,"pen_down":self.pen_down,"limits":self.limits,
                "pen_calibration_api":1,"pen_calibrated":self.pen_calibrated,"pen_tuning":self.pen_tuning,
                "speed_control_api":1,"stepper_percent":self.stepper_percent,"stepper_percent_actual":self.stepper_percent,"servo_speed":self.servo_speed,
                "stored_plot_api":2 if self.storage else 0,"plot_capacity":self.plot_capacity,"plot_free":1408*1024-len(self.plot_data)-len((self.plot_saved or {}).get('data',b'')),
                "plot_storage_total":1408*1024,"plot_cleanup_pending":False,"plot_cleanup_error":False,
                "plot_id":(self.plot_meta or self.plot_saved or {}).get("job",""),"plot_run":self.plot_run,
                "plot_state":self.plot_state,"plot_total":(self.plot_meta or self.plot_saved or {}).get("count",0),
                "plot_parent":(self.plot_saved or {}).get("parent",""),"plot_chain":(self.plot_saved or {}).get("chain",""),
                "plot_part":(self.plot_saved or {}).get("part",0),"plot_final":(self.plot_saved or {}).get("final",True),
                "plot_received":len(self.plot_data),"plot_completed":self.plot_completed,
                "calibration_api":1,"switch_homing_enabled":True,"calibrating":self.calibrating,"jog_steps":list(self.jog_steps),
                "steps_per_mm":[80.,80.],"reference":self.reference,"calibration_id":self.calibration_id,
                "draw_bounds":self.draw_bounds,
                "position_kind":"planned" if self.active_command else "settled","error":self.error}

    async def emit(self, message, writer=None):
        w = writer or self.writer
        if w and not w.is_closing():
            try:
                w.write((json.dumps(message,separators=(",",":"))+"\n").encode())
                await w.drain()
            except (OSError, ConnectionError): pass

    def lose(self):
        if not self.plot_running and self.authenticated and (self.queue or self.active_command or self.calibrating or self.pen_tuning or self.pen != self.pen_up):
            self.hold = True
            self.calibrating=False
            self.pen_tuning=False
        self.authenticated = False
        if self.writer: self.writer.close()

    async def handle(self, reader, writer):
        if self.writer and not self.writer.is_closing():
            writer.close(); await writer.wait_closed(); return
        self.writer = writer
        self.authenticated = False
        self.last_seen = time.monotonic()
        try:
            while raw := await reader.readline():
                message = json.loads(raw)
                kind = message.get("type")
                if kind == "hello":
                    if message.get("token") != self.token:
                        await self.emit({"type":"error","error":"unauthorized"}); break
                    incoming = message["session"]
                    if self.session and incoming != self.session and (self.queue or self.hold or self.completed != self.next-1):
                        await self.emit({"type":"error","error":"session_busy"}); break
                    if incoming != self.session:
                        self.session = incoming; self.next = 1; self.completed = 0; self.receipts.clear()
                    self.authenticated = True
                    await self.emit(self.state("hello")); continue
                if not self.authenticated:
                    await self.emit({"type":"error","error":"hello_required"}); break
                self.last_seen = time.monotonic()
                if kind in ("ping","status"):
                    await self.emit(self.state()); continue
                if kind.startswith("plot_"):
                    try:failure=self.plot_control(message)
                    except (ValueError,KeyError,TypeError):failure="invalid_plot"
                    if not failure and self.drop_plot_ack==kind:
                        self.drop_plot_ack=None;self.lose();break
                    if failure:await self.emit({"type":"error","request":message.get("request"),"error":failure})
                    else:await self.emit(dict(self.state("control"),request=message.get("request"),op=kind))
                    continue
                if kind=="speeds":
                    percent,speed=message.get("stepper_percent"),message.get("servo_speed")
                    if message.get("boot")!=self.boot or self.fault or type(percent) is not int or not 10<=percent<=100 or type(speed) not in (int,float) or not math.isfinite(speed) or not 5<=speed<=120:
                        await self.emit({"type":"error","request":message.get("request"),"error":"invalid_speed_or_fault"})
                    else:
                        self.stepper_percent,self.servo_speed=percent,speed
                        await self.emit(dict(self.state("control"),request=message.get("request"),op=kind))
                    continue
                if kind in ("pause","resume","stop"):
                    if kind == "pause": self.hold = True; self.calibrating=False
                    if kind == "resume":
                        if message.get("boot") != self.boot or not self.paused or self.active_command or not self.homed or self.fault:
                            await self.emit({"type":"error","error":"resume_not_safe"}); continue
                        self.hold = self.paused = False; self.pen = self.held_pen
                    if kind == "stop":
                        if self.plot_running or self.plot_meta or self.plot_state in ("waiting","ready"):
                            self.plot_running=False;self.plot_meta=None;self.plot_state="stopped";self.release_plot_bytes()
                        self.fault = True; self.homed = False; self.hold = self.paused = True
                        self.queue.clear(); self.active_command = None; self.pen = self.pen_up;self.pen_tuning=False
                        self.calibrating=False;self.reference="unknown";self.calibration_id=""
                    await self.emit(dict(self.state("control"),request=message.get("request",""),op=kind)); continue
                number = message.get("id",0)
                fail = None
                fingerprint = raw.decode().strip()
                if message.get("boot") != self.boot: fail = "boot_changed"
                elif number < self.next:
                    fail = "stale_id" if number not in self.receipts else (
                        None if self.receipts[number] == fingerprint else "id_conflict")
                    if fail is None:
                        await self.emit(dict(self.state("ack"),id=number,duplicate=True)); continue
                elif number != self.next: fail = "out_of_order"
                elif self.fault: fail = "fault"
                elif self.plot_running or self.plot_meta or self.plot_state=="waiting":fail="stored_plot_owns_motion"
                elif self.hold and message.get("op") not in ("cal_begin","cal_apply","cal_pen","pen_config","pen_end"): fail = "paused"
                elif len(self.queue) >= 8: fail = "queue_full"
                elif self.pen_tuning and message.get("op") not in ("cal_pen","pen_config","pen_end","sync","pen"):fail="pen_calibration_active"
                elif message.get("op") == "move" and not self.homed: fail = "invalid_move_or_unhomed"
                elif message.get("op") in ("cal_pen","pen_config","pen_end"):
                    if self.queue or self.active_command or self.calibrating:fail="calibration_busy"
                    elif message.get("confirm") is not True:fail="confirmation_required"
                    elif message["op"]=="cal_pen" and (type(message.get("angle")) is not int or not 10<=message["angle"]<=170):fail="invalid_pen"
                    elif message["op"]=="pen_config" and (any(type(message.get(k)) is not int or not 10<=message[k]<=170 for k in ("up","down")) or message["up"]==message["down"]):fail="invalid_pen"
                elif message.get("op") in ("cal_begin","cal_jog","cal_apply"):
                    if self.queue or self.active_command:fail="calibration_busy"
                    elif message["op"] in ("cal_begin","cal_apply") and message.get("confirm") is not True:fail="confirmation_required"
                    elif message["op"]=="cal_jog" and (not self.calibrating or type(message.get("axis")) is not int or
                            message["axis"] not in (0,1) or type(message.get("steps")) is not int or not 1<=abs(message["steps"])<=4000):fail="invalid_jog"
                elif self.calibrating and message.get("op") not in ("sync","pen"):fail="calibration_active"
                if fail:
                    await self.emit({"type":"error","error":fail,"id":number,"next":self.next}); continue
                self.receipts[number] = fingerprint
                if number-32 in self.receipts: del self.receipts[number-32]
                self.next += 1; self.queue.append(message)
                if message.get("op") in ("cal_begin","cal_apply","cal_pen","pen_config","pen_end"):self.hold=self.paused=False
                if self.drop_next_ack:
                    self.drop_next_ack = False; self.lose(); break
                if self.suppress_next_ack:
                    self.suppress_next_ack = False; continue
                await self.emit(dict(self.state("ack"),id=number,duplicate=False))
        except (OSError, ValueError, asyncio.CancelledError): pass
        finally:
            if self.writer is writer: self.lose()
            writer.close()
            with contextlib.suppress(OSError): await writer.wait_closed()

    def release_plot_bytes(self):
        self.plot_data=bytearray()
        if self.plot_saved:self.plot_saved.pop('data',None)

    def fail_plot_upload(self,reason):
        self.plot_meta=None;self.plot_state="error";self.release_plot_bytes()
        return reason

    def service_plot_storage(self,now):
        if self.plot_running or self.active_command:return
        if self.plot_meta and now-self.plot_last_upload>=self.plot_upload_idle:
            self.plot_meta=None;self.plot_state=self.plot_return_state;self.plot_data=bytearray()
        if self.plot_state=='ready' and now-self.plot_ready_since>=self.plot_ready_idle:
            self.plot_state='expired';self.release_plot_bytes()

    def plot_control(self,m):
        if not self.storage or m.get("boot")!=self.boot or self.fault:return "plot_boot_or_fault"
        op=m["type"]
        if op=="plot_start" and m.get("run")==self.plot_run and m.get("job")== (self.plot_saved or {}).get("job"):return None
        if self.queue or self.active_command or self.plot_running or self.hold or self.paused or self.calibrating or self.pen_tuning:return "plot_busy"
        if op=="plot_begin":
            if m.get("confirm") is not True or self.reference!="user":return "plot_confirmation_or_reference_required"
            if type(m.get("count")) is not int or not 1<=m["count"]<=self.plot_capacity//16:return "invalid_plot_metadata"
            meta={k:m[k] for k in ('job','cal','count','crc','up','down','spu0','spu1','parent','chain','part','final') if k in m}
            if self.plot_meta:
                if self.plot_meta==meta:self.plot_last_upload=time.monotonic();return None
                return "plot_upload_in_progress"
            saved=self.plot_saved or {}
            multipart='parent' in meta or 'chain' in meta
            if multipart:
                try:
                    import uuid
                    uuid.UUID(meta['parent']);uuid.UUID(meta['chain'])
                except (ValueError,KeyError):return "invalid_plot_chain"
                if type(meta.get('part')) is not int or meta['part']<0 or type(meta.get('final')) is not bool:return "invalid_plot_chain"
            if self.plot_state=='waiting':
                if not multipart or any(meta.get(k)!=saved.get(k) for k in ('parent','chain')) or meta['part']!=saved.get('part',0)+1:return "plot_continuation_mismatch"
            elif multipart and meta['part']>0:
                if self.plot_state not in ('ready','expired') or any(meta.get(k)!=saved.get(k) for k in ('parent','chain','part','job')):return "plot_continuation_mismatch"
            self.plot_return_state=self.plot_state if self.plot_state in ('waiting','completed') else 'expired'
            self.release_plot_bytes()
            self.plot_meta=meta;self.plot_data=bytearray();self.plot_state="uploading";self.plot_last_upload=time.monotonic()
        elif op=="plot_chunk":
            if not self.plot_meta:return "no_plot_upload"
            part=base64.b64decode(m["data"],validate=True);offset=m["offset"]
            if not part or len(part)>384 or len(part)%16:return "invalid_plot_chunk"
            if offset<len(self.plot_data) and self.plot_data[offset:offset+len(part)]==part:
                self.plot_last_upload=time.monotonic();return None
            if offset!=len(self.plot_data) or offset+len(part)>self.plot_meta["count"]*16:return "plot_offset_mismatch"
            self.plot_data.extend(part);self.plot_last_upload=time.monotonic()
        elif op=="plot_commit":
            if not self.plot_meta:return None if self.plot_state=='ready' else "no_plot_upload"
            if len(self.plot_data)!=self.plot_meta["count"]*16:return "plot_incomplete"
            if zlib.crc32(self.plot_data)!=self.plot_meta["crc"]:
                return self.fail_plot_upload("plot_checksum_mismatch")
            last_pen=1
            for record in RECORD.iter_unpack(self.plot_data):
                code,x,y,feed=record
                if code not in (0,1,2,3) or not all(math.isfinite(v) for v in (x,y,feed)):return self.fail_plot_upload("invalid_plot_record")
                if code==0 and (not .1<=feed<=30 or not self.draw_bounds[0]<=x<=self.draw_bounds[2] or not self.draw_bounds[1]<=y<=self.draw_bounds[3]):return self.fail_plot_upload("plot_outside_calibration")
                if code!=0 and (x or y or feed):return self.fail_plot_upload("invalid_plot_record")
                if code in (1,2):last_pen=code
            if record[0]!=3 or last_pen!=1:return self.fail_plot_upload("plot_must_finish_pen_up_sync")
            self.plot_saved=dict(self.plot_meta,data=bytes(self.plot_data));self.plot_meta=None;self.plot_data=bytearray()
            self.plot_ready_since=time.monotonic()
            self.plot_state="ready";self.plot_run="";self.plot_completed=0
        elif op=="plot_start":
            s=self.plot_saved
            if not s or self.plot_state!='ready' or m.get("confirm") is not True or m.get("job")!=s["job"]:return "plot_not_ready"
            if not self.homed or self.calibration_id!=s["cal"] or (self.pen_up,self.pen_down)!=(s["up"],s["down"]):return "plot_reference_changed"
            self.plot_starts.append((s['job'],m['run']))
            self.plot_run=m["run"];self.plot_completed=0;self.plot_running=True;self.plot_state="running";self.plot_due=time.monotonic()+self.delay
        else:return "unknown_plot_operation"
        return None

    async def tick(self):
        last_status = 0.
        while True:
            now = time.monotonic()
            self.service_plot_storage(now)
            if self.writer and now-self.last_seen > self.heartbeat_timeout: self.lose()
            if self.hold and not self.paused:
                if self.active_command and self.active_command["op"] == "move":
                    # Model a partially planned line: only buffered movement finishes.
                    self.x = (self.x+self.active_command["x"])/2
                    self.y = (self.y+self.active_command["y"])/2
                self.active_command = None
                self.held_pen = self.pen; self.pen = self.pen_up; self.paused = True
            elif not self.hold and not self.fault:
                if self.plot_running and now>=self.plot_due:
                    op,x,y,feed=RECORD.unpack_from(self.plot_saved["data"],self.plot_completed*16)
                    if op==0:self.x,self.y=x,y
                    elif op in (1,2):self.pen=self.pen_up if op==1 else self.pen_down
                    self.plot_completed+=1;self.plot_due=now+self.delay
                    if self.plot_completed==self.plot_saved["count"]:
                        self.plot_running=False;self.plot_state="completed" if self.plot_saved.get('final',True) else "waiting"
                        self.release_plot_bytes()
                if self.active_command and now >= self.busy_until:
                    command = self.active_command
                    if command["op"] == "move": self.x,self.y = command["x"],command["y"]
                    elif command["op"] == "pen": self.pen = command["angle"]
                    elif command["op"] == "cal_pen":self.pen=command["angle"];self.pen_tuning=True
                    elif command["op"] == "pen_config":
                        self.pen_up,self.pen_down=command["up"],command["down"]
                        self.pen_calibrated=True;self.pen_tuning=False;self.pen=self.pen_up
                    elif command["op"] == "pen_end":self.pen_tuning=False;self.pen=self.pen_up
                    elif command["op"] == "home": self.homed = True;self.reference="switches"
                    elif command["op"] == "cal_begin":
                        self.homed=False;self.reference="unknown";self.calibration_id=""
                        self.calibrating=True;self.jog_steps=[0,0];self.pen=self.pen_up;self.error=""
                    elif command["op"] == "cal_jog":self.jog_steps[command["axis"]]+=command["steps"]
                    elif command["op"] == "cal_apply":
                        from .calibration import position
                        self.x,self.y=position(command["width"],command["l"],command["r"])
                        self.draw_bounds=[command[k] for k in ("xmin","ymin","xmax","ymax")]
                        self.limits=[[0,command["width"]],[command["ymin"],0]]
                        self.calibrating=False;self.homed=True;self.reference="user";self.calibration_id=command["cal_id"]
                        self.pen=self.pen_up;self.error=""
                    self.executions.append(command["id"])
                    self.completed = command["id"]; self.queue.pop(0); self.active_command = None
                if self.queue and not self.active_command:
                    self.active_command = self.queue[0]; self.busy_until = now+self.delay
            if self.authenticated and now-last_status > .025:
                await self.emit(self.state()); last_status = now
            await asyncio.sleep(.005)

    def reboot(self):
        self.plot_running=False;self.plot_meta=None;self.plot_data=bytearray();self.plot_run="";self.plot_completed=0
        if self.plot_saved and 'data' not in self.plot_saved:self.plot_saved=None
        if self.plot_saved:
            self.plot_saved={k:v for k,v in self.plot_saved.items() if k not in ('parent','chain','part','final')}
        self.plot_state="ready" if self.plot_saved else "empty";self.plot_ready_since=time.monotonic()
        self.stepper_percent,self.servo_speed=100,35
        self.lose(); self.boot = secrets.token_hex(8); self.session = ""
        self.next, self.completed = 1, 0
        self.receipts.clear(); self.queue.clear(); self.active_command = None
        self.homed = self.fault = self.hold = self.paused = False
        self.pen = self.pen_up;self.pen_tuning=False
        self.calibrating=False;self.reference="unknown";self.calibration_id="";self.draw_bounds=None;self.jog_steps=[0,0]

    async def close(self):
        self.lose()
        if self.task:
            self.task.cancel(); await asyncio.gather(self.task,return_exceptions=True)
        if self.server:
            self.server.close(); await self.server.wait_closed()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=9999)
    args = parser.parse_args()
    token = secrets.token_hex(16)
    robot = await SimulatedRobot(token).start(args.port)
    print(f"Simulated robot: 127.0.0.1:{robot.port}\nSimulation pairing key: {token}",flush=True)
    try: await asyncio.Future()
    finally: await robot.close()

if __name__ == "__main__": asyncio.run(main())
