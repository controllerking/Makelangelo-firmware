"""Run: python3 -m controller.server. Uses only the Python standard library."""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlsplit
import uuid
import base64
from .plot import encode_plot

from .artwork import PAPER, demo_paths, prepare, svg_paths, finite
from .transport import DeviceLink, DeviceError
from .raster import PRESETS, preset, raster_paths, np as _numpy
from .config import ENV_FILE, RobotConfig, load_robot_config
from .calibration import CORNERS, fit, reference_command

ROOT = Path(__file__).parent
MAX_BODY = 2_500_000

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    os.chmod(path, 0o600)

class Controller:
    def __init__(self, data_dir, robot=None):
        self.data_dir = Path(data_dir)
        config_path = self.data_dir/"connection.json"
        saved = json.loads(config_path.read_text()) if config_path.exists() else {}
        self.config = {"session":saved.get("session", str(uuid.uuid4()))}
        self.robot = robot or RobotConfig()
        # Retain session identity for safe recovery, but remove legacy credentials.
        # Host/port/key are never loaded from or written to this runtime journal.
        if saved and set(saved) != {"session"}: save_json(config_path, self.config)
        self.connection_message = "Connecting automatically"
        self.link = DeviceLink(self.config["session"], self.disconnected)
        self.jobs = {}
        if (self.data_dir/"jobs").exists():
            for path in (self.data_dir/"jobs").glob("*.json"):
                if path.name.endswith(".state.json"): continue;
                job = json.loads(path.read_text())
                journal = path.with_suffix(".state.json")
                if journal.exists(): job.update(json.loads(journal.read_text()))
                if job["state"] == "running": job["state"] = "paused"
                if job.get("execution")=="stored" and job["state"]=="uploading":job["state"]="uncertain"
                self.jobs[job["id"]] = job
        self.active = next((j["id"] for j in self.jobs.values() if j["state"] in ("paused","uncertain")), None)
        self.worker = None
        self.operation_lock = asyncio.Lock()
        self.speed_lock = asyncio.Lock()
        self.preparation_lock = asyncio.Lock()
        self.simulation = False
        path=self.data_dir/"paper_calibration.json"
        self.calibration=json.loads(path.read_text()) if path.exists() else None
        self.calibration_draft=None
        self.pen_draft=None
        path=self.data_dir/"pen_calibration.json"
        self.pen_calibration=json.loads(path.read_text()) if path.exists() else None

    def persist(self, job):
        path = self.data_dir/"jobs"/(job["id"]+".json")
        if not path.exists():
            save_json(path, job)
        else:
            save_json(path.with_suffix(".state.json"),
                      {k:v for k,v in job.items() if k not in ("commands","paths")})

    def disconnected(self, reason):
        self.connection_message = "Reconnecting automatically"
        self.pen_draft=None # A hold may have lifted the servo; discard stale previews.
        if self.active and self.active in self.jobs:
            job = self.jobs[self.active]
            if job["state"] == "running":
                if job.get("execution")=="stored":
                    job["message"]="Controller offline; verified plot continues on the device"
                    self.persist(job)
                    return
                job["state"] = "paused"; job["message"] = reason
                self.persist(job)

    def public_job(self, job, detail=False):
        result = {k:v for k,v in job.items() if k not in ("commands","paths")}
        if detail: result["paths"] = job["paths"]
        return result

    def snapshot(self):
        state = self.link.state
        if self.active and self.active in self.jobs:
            job = self.jobs[self.active]
            if job.get("execution")=="stored" and self.link.connected:
                self.reconcile_stored(job)
            if job.get("execution")!="stored" and job.get("base_id") and job.get("boot") == state.get("boot"):
                job["completed"] = max(job.get("completed",0),
                    min(job["command_count"], max(0, state.get("completed",0)-job["base_id"]+1)))
        return {"connected":self.link.connected, "device":dict(state),
                "simulation":self.simulation,
                "connection_message":self.connection_message, "active":self.active,
                "jobs":[self.public_job(j) for j in sorted(self.jobs.values(), key=lambda j:j["created"], reverse=True)],
                "papers":PAPER, "presets":PRESETS, "wave_available":_numpy is not None,
                "calibration":self.calibration,"calibration_draft":self.calibration_draft,
                "pen_calibration":self.pen_calibration,"pen_draft":self.pen_draft}

    async def connect(self):
        if not self.robot.host or not self.robot.token:
            raise ValueError("Robot connection must be configured in the server .env file")
        if self.worker and not self.worker.done():
            raise ValueError("Pause the current job before reconnecting")
        state = await self.link.connect(self.robot.host, self.robot.token, self.robot.port)
        self.connection_message = "Linked by server configuration"
        save_json(self.data_dir/"connection.json", self.config)
        if self.active:
            job = self.jobs[self.active]
            if job.get("boot") and job["boot"] != state["boot"]:
                job["state"] = "interrupted"
                job["message"] = "Robot rebooted. Rehome and explicitly restart; automatic resume is blocked."
                self.persist(job); self.active = None
        return self.snapshot()

    async def maintain_connection(self, retry_seconds=3):
        # Reconnect only to the immutable startup configuration. Never home,
        # start or resume motion here, including after a device reboot.
        while True:
            if not self.link.connected:
                try: await self.connect()
                except (OSError, ValueError, DeviceError, ConnectionError, asyncio.TimeoutError):
                    self.connection_message = "Robot unavailable; retrying automatically"
            await asyncio.sleep(retry_seconds)

    async def calibration_action(self, data):
        if not isinstance(data,dict): raise ValueError("Expected calibration settings")
        if self.operation_lock.locked(): raise ValueError("Wait for the current manual action; jogs are not queued")
        async with self.operation_lock:
            if self.pen_draft: raise ValueError("Save or cancel pen calibration before calibrating paper")
            d=self.link.state
            if not self.link.connected or d.get("calibration_api") != 1:
                raise ValueError("Connect the updated calibration-capable ESP32 firmware first")
            if self.active or d.get("fault") or d.get("busy") or d.get("moving"):
                raise ValueError("Calibration requires an idle robot with no active job or fault")
            action=data.get("action")
            async def send(command, timeout=40):
                reply=await self.link.command(command)
                await self.link.wait_completed(reply["id"],timeout=timeout)
                if self.link.state.get("error"): raise DeviceError(self.link.state["error"])
            if action=="begin":
                if data.get("confirmed") is not True: raise ValueError("Confirm pen clearance, motor direction and supervised jogging")
                paper=data.get("paper")
                if not isinstance(paper,str) or paper not in PAPER: raise ValueError("Choose a known paper size")
                width=finite(data.get("width"),"motor spacing")
                if not 100<=width<=2000: raise ValueError("Motor spacing must be 100–2000 mm")
                spu=d.get("steps_per_mm",[])
                if len(spu)!=2 or not all(1<=finite(v)<=10000 for v in spu): raise ValueError("Invalid motor scale")
                await send({"op":"cal_begin","confirm":True})
                if not self.link.state.get("calibrating"): raise DeviceError("Calibration did not start")
                self.calibration_draft={"paper":paper,"width":width,"spu":list(spu),
                                        "boot":d["boot"],"corners":{}}
            elif action=="restore":
                if not self.calibration: raise ValueError("No saved paper calibration")
                name=data.get("corner","top_left")
                if name not in CORNERS: raise ValueError("Choose one of the four saved corners")
                if data.get("at_corner",data.get("at_top_left")) is not True:
                    raise ValueError("Place the pen at the saved %s point and confirm" % name.replace("_"," "))
                if list(d.get("steps_per_mm",[]))!=self.calibration["spu"]:
                    raise ValueError("Motor scale changed; recalibrate all corners")
                await send(reference_command(self.calibration,self.calibration["corners"][name]["belts"]))
                if self.link.state.get("calibration_id")!=self.calibration["id"]: raise DeviceError("Reference restore failed")
                self.calibration_draft=None
            else:
                draft=self.calibration_draft
                if not draft or draft["boot"]!=d.get("boot") or not d.get("calibrating"):
                    raise ValueError("Calibration position was lost; begin again (or restore from one saved corner)")
                if action=="jog":
                    axis=data.get("axis")
                    if type(axis) is not int or axis not in (0,1): raise ValueError("Choose the left or right motor")
                    mm=finite(data.get("mm"),"jog distance")
                    if not .05<=abs(mm)<=50: raise ValueError("Jog distance must be 0.05–50 mm")
                    steps=round(mm*draft["spu"][axis])
                    if not 1<=abs(steps)<=4000: raise ValueError("Jog must be 1–4000 pulses")
                    await send({"op":"cal_jog","axis":axis,"steps":steps},
                               timeout=max(15,10*(abs(steps)/2000+abs(mm)/10)+5))
                    if not self.link.state.get("calibrating"): raise DeviceError("Jog interrupted; begin calibration again")
                elif action=="capture":
                    name=data.get("corner")
                    expected=CORNERS[len(draft["corners"])] if len(draft["corners"])<4 else None
                    if name!=expected: raise ValueError("Capture corners in order: top-left, top-right, bottom-right, bottom-left")
                    await send({"op":"sync"})
                    draft["corners"][name]=list(self.link.state["jog_steps"])
                elif action=="finish":
                    calibration=fit(draft)
                    counts=self.link.state["jog_steps"]
                    lengths=[z+c/s for z,c,s in zip(calibration["zero_belts"],counts,calibration["spu"])]
                    await send(reference_command(calibration,lengths))
                    if self.link.state.get("calibration_id")!=calibration["id"] or not self.link.state.get("homed"):
                        raise DeviceError("Robot did not accept the calibrated reference")
                    save_json(self.data_dir/"paper_calibration.json",calibration)
                    self.calibration=calibration; self.calibration_draft=None
                else: raise ValueError("Unknown calibration action")
            return self.snapshot()

    async def pen_calibration_action(self,data):
        if not isinstance(data,dict): raise ValueError("Expected pen calibration settings")
        if self.operation_lock.locked(): raise ValueError("Wait for the current manual action")
        async with self.operation_lock:
            d=self.link.state
            if not self.link.connected or d.get("pen_calibration_api")!=1:
                raise ValueError("Flash the pen-calibration firmware first")
            if self.active or self.calibration_draft or d.get("calibrating") or d.get("fault") or d.get("busy") or d.get("moving"):
                raise ValueError("Pen calibration needs an idle robot; finish paper calibration first")
            action=data.get("action")
            async def send(command):
                reply=await self.link.command(dict(command,confirm=True))
                await self.link.wait_completed(reply["id"],timeout=40)
                if self.link.state.get("error"): raise DeviceError(self.link.state["error"])
            if action=="begin":
                if data.get("confirmed") is not True: raise ValueError("Confirm servo clearance and supervised pen adjustment")
                self.pen_draft={"boot":d["boot"],"angle":d["pen"],"up":None,"down":None}
            else:
                draft=self.pen_draft
                if not draft or draft["boot"]!=d.get("boot"):
                    raise ValueError("Begin pen calibration again after a reboot")
                if action in ("adjust","set"):
                    if action=="adjust":
                        delta=data.get("delta")
                        if type(delta) is not int or delta not in (-30,-10,-5,-1,1,5,10,30): raise ValueError("Adjust by 1°, 5°, 10° or 30°")
                        angle=draft["angle"]+delta
                    else:
                        angle=data.get("angle")
                        if type(angle) is not int: raise ValueError("Enter a whole-number servo angle")
                    if not 10<=angle<=170: raise ValueError("Servo adjustment range is 10–170°; do not force mechanical stops")
                    await send({"op":"cal_pen","angle":angle})
                    draft["angle"]=angle
                elif action=="capture":
                    role=data.get("role")
                    if role not in ("up","down"): raise ValueError("Choose pen in or pen out")
                    draft[role]=draft["angle"]
                elif action=="test":
                    role=data.get("role")
                    if role not in ("up","down") or draft.get(role) is None: raise ValueError("Capture that pen position first")
                    await send({"op":"cal_pen","angle":draft[role]})
                    draft["angle"]=draft[role]
                elif action=="save":
                    up,down=draft["up"],draft["down"]
                    if up is None or down is None or up==down: raise ValueError("Capture distinct pen-in and pen-out positions")
                    await send({"op":"pen_config","up":up,"down":down})
                    if self.link.state.get("pen_up")!=up or self.link.state.get("pen_down")!=down or not self.link.state.get("pen_calibrated"):
                        raise DeviceError("Device did not save pen positions")
                    self.pen_calibration={"up":up,"down":down,"created":time.time()}
                    save_json(self.data_dir/"pen_calibration.json",self.pen_calibration)
                    self.pen_draft=None
                elif action=="cancel":
                    await send({"op":"pen_end"})
                    self.pen_draft=None
                else: raise ValueError("Unknown pen calibration action")
            return self.snapshot()

    async def set_speeds(self,data):
        if not isinstance(data,dict): raise ValueError("Expected speed settings")
        percent=data.get("stepper_percent")
        servo=finite(data.get("servo_speed"),"pen speed")
        if type(percent) is not int or not 10<=percent<=100: raise ValueError("Stepper override must be 10–100%")
        if not 5<=servo<=120: raise ValueError("Pen speed must be 5–120 degrees/second")
        async with self.speed_lock:
            if not self.link.connected or self.link.state.get("speed_control_api")!=1:
                raise ValueError("Flash the live-speed firmware first")
            if self.link.state.get("fault"): raise ValueError("Reset the robot after a fault")
            await self.link.control("speeds",stepper_percent=percent,servo_speed=servo)
            return self.snapshot()

    def build_artwork(self, data, device):
        if not isinstance(data, dict): raise ValueError("Expected an artwork object")
        options = data.get("options", {})
        if not isinstance(options, dict): raise ValueError("Expected artwork options")
        quality, profile = preset(options)
        options = dict(options)
        if self.calibration:
            options.update(paper=self.calibration["paper"],left=self.calibration["left"],top=self.calibration["top"])
            if self.calibration.get("version",1)>=2:
                options["paper_corners"]=[self.calibration["corners"][key]["xy"] for key in CORNERS]
        options.setdefault("feed", profile["feed"])
        metadata, source_bounds = {"source_type":"svg", "quality":quality}, None
        if data.get("demo"):
            paths, warnings = demo_paths(), []
            title = "Harmonic study"
            metadata["source_type"] = "demo"
        elif "image" in data:
            paths, warnings, metadata, source_bounds = raster_paths(data["image"], options)
            title = str(data.get("name", "Image drawing"))[:120]
        else:
            paths, warnings = svg_paths(str(data.get("svg", "")))
            title = str(data.get("name", "Untitled drawing"))[:120]
        prepared = prepare(paths, options, device.get("pen_up",90), device.get("pen_down",40), source_bounds)
        prepared.update(metadata, path_count=len(paths), feed=float(options["feed"]))
        prepared["calibration_id"]=self.calibration["id"] if self.calibration else None
        if self.calibration and self.calibration.get("max_error_mm",0)>3:
            warnings.append("Captured corners accepted as provided. Paper-size mismatch is %.1f mm; verify the preview and use generous margins." % self.calibration["max_error_mm"])
        job = dict(prepared, id=str(uuid.uuid4()), title=title, warnings=warnings,
                   state="queued", created=time.time(), accepted=0, completed=0,
                   base_id=None, boot=None, message="Ready for review")
        return job

    def import_artwork(self, data):
        job = self.build_artwork(data, dict(self.link.state))
        self.jobs[job["id"]] = job; self.persist(job)
        return self.public_job(job, True)

    async def import_async(self, data):
        # Conversion never starves heartbeat; don't accumulate unbounded workers.
        if self.preparation_lock.locked(): raise ValueError("Another drawing is being prepared; try again shortly")
        async with self.preparation_lock:
            job = await asyncio.to_thread(self.build_artwork, data, dict(self.link.state))
            self.jobs[job["id"]] = job; self.persist(job)
            return self.public_job(job, True)

    def validate_job(self, job):
        if not self.link.connected: raise ValueError("Robot is offline; check the server configuration and network")
        d = self.link.state
        if self.calibration_draft: raise ValueError("Finish calibration or restore the saved reference before drawing")
        if self.pen_draft or d.get("pen_tuning"): raise ValueError("Save or cancel pen calibration before drawing")
        if job.get("pen_up")!=d.get("pen_up",90) or job.get("pen_down")!=d.get("pen_down",40):
            raise ValueError("Pen positions changed; prepare this drawing again")
        if d.get("reference")=="user" or self.calibration:
            if not self.calibration or d.get("calibration_id")!=self.calibration["id"]:
                raise ValueError("Restore the saved top-left reference or recalibrate before drawing")
            if job.get("calibration_id")!=self.calibration["id"]:
                raise ValueError("Paper calibration changed; prepare this drawing again")
        if not d.get("homed"): raise ValueError("Home the calibrated robot first")
        if d.get("fault"): raise ValueError("Reset the robot and rehome after a fault")
        limits = d["limits"]
        for command in job["commands"]:
            if command["op"] == "move":
                x,y = command["x"],command["y"]
                if not limits[0][0] <= x <= limits[0][1] or not limits[1][0] <= y < limits[1][1]:
                    raise ValueError("Drawing lies outside the robot's calibrated limits")
                if d.get("draw_bounds"):
                    xmin,ymin,xmax,ymax=d["draw_bounds"]
                    if not xmin<=x<=xmax or not ymin<=y<=ymax: raise ValueError("Drawing lies outside the captured paper envelope")

    async def start(self, job_id, reviewed=False):
        if self.operation_lock.locked(): raise ValueError("Wait for the current manual action")
        if not reviewed: raise ValueError("Confirm the paper position and collision clearance first")
        if self.active: raise ValueError("Finish or stop the active job first")
        job = self.jobs[job_id]
        if job["state"] not in ("queued","completed","interrupted","cancelled","error"):
            raise ValueError("Job is not ready to start")
        self.validate_job(job)
        if self.link.state.get("holding") or self.link.state.get("paused"):
            raise ValueError("Resolve the robot's paused state before starting a new job")
        if self.link.state.get("stored_plot_api")==1:
            if not self.calibration:raise ValueError("Complete paper calibration before uploading a stored plot")
            payload,crc=encode_plot(job)
            if len(payload)>self.link.state.get("plot_capacity",0):raise ValueError("Plot exceeds device storage capacity")
            self.active=job_id
            job.update(state="uploading",execution="stored",accepted=0,completed=0,boot=self.link.state["boot"],
                       plot_run=str(uuid.uuid4()),message="Uploading complete plot before any movement")
            self.persist(job)
            try:
                async with self.operation_lock:
                    reply=await self.link.control("plot_begin",job=job_id,cal=self.calibration["id"],count=len(payload)//16,
                        crc=crc,up=self.link.state["pen_up"],down=self.link.state["pen_down"],
                        spu0=self.calibration["spu"][0],spu1=self.calibration["spu"][1],confirm=True,timeout=30)
                    offset=int(reply.get("plot_received",0))
                    if not 0<=offset<=len(payload) or offset%16:raise DeviceError("Invalid device upload offset")
                    while offset<len(payload):
                        if job["state"]!="uploading":raise ValueError("Upload cancelled; no plot started")
                        part=payload[offset:offset+384]
                        await self.link.control("plot_chunk",offset=offset,data=base64.b64encode(part).decode(),timeout=15)
                        offset+=len(part);job["accepted"]=offset//16
                    await self.link.control("plot_commit",timeout=30)
                    await self.link.control("plot_start",job=job_id,run=job["plot_run"],confirm=True,timeout=30)
                job.update(state="running",message="Drawing from device storage",started=time.time())
                self.persist(job)
                return self.public_job(job)
            except Exception:
                # Start acknowledgement can be lost after the device started.
                if job["state"]!="cancelled":job.update(state="uncertain",message="Upload/start interrupted; reconnect to verify device state—do not restart blindly")
                self.persist(job)
                raise
        # Match the robot's configured servo angles even after recalibration.
        job.update(execution="streamed",pen_up=self.link.state["pen_up"], accepted=0, completed=0,
                   base_id=int(self.link.state["next"]), boot=self.link.state["boot"],
                   state="running", message="Drawing", started=time.time())
        self.active = job_id; self.persist(job)
        self.worker = asyncio.create_task(self.run_job(job))
        return self.public_job(job)

    def reconcile_stored(self,job):
        if job["state"]=="uploading":return
        d=self.link.state
        if job.get("boot")!=d.get("boot"):
            job.update(state="interrupted",message="Device rebooted; restore position and explicitly restart")
            self.active=None;self.persist(job);return
        if d.get("plot_id")!=job["id"] or d.get("plot_run")!=job.get("plot_run"):
            if job["state"] in ("uploading","uncertain"):
                job.update(state="interrupted",message="Stored plot did not start; review and upload again")
                self.active=None
                self.persist(job)
            return
        job["accepted"]=job["command_count"]
        job["completed"]=d.get("plot_completed",0)
        if d.get("fault") or d.get("plot_state") in ("fault","error","stopped"):
            job.update(state="error",message="Device stopped; restore position before restarting");self.active=None
        elif d.get("plot_state")=="completed":
            job.update(state="completed",message="Drawing finished on device");self.active=None
        elif d.get("paused") or d.get("holding"):
            job.update(state="paused",message="Device paused; explicit resume required")
        else:job.update(state="running",message="Drawing from device storage; computer may disconnect")
        self.persist(job)

    async def run_job(self, job):
        try:
            while job["state"] == "running":
                if not self.link.connected: raise ConnectionError("Device disconnected")
                d = self.link.state
                if d.get("boot") != job["boot"]: raise DeviceError("Robot rebooted")
                if d.get("fault"): raise DeviceError("Robot fault; reset and rehome")
                if d.get("holding") or d.get("paused"):
                    raise ConnectionError("Robot paused; wait for buffered movement and explicitly resume")
                accepted = min(job["command_count"], max(0, int(d.get("accepted",0))-job["base_id"]+1))
                completed = min(job["command_count"], max(0, int(d.get("completed",0))-job["base_id"]+1))
                job["accepted"], job["completed"] = accepted, completed
                if completed >= job["command_count"]:
                    job.update(state="completed", message="Drawing finished", finished=time.time())
                    self.active = None; self.persist(job); return
                if accepted >= job["command_count"] or d.get("queue_free",0) <= 1:
                    await asyncio.sleep(.04); continue
                expected = job["base_id"]+accepted
                if int(d["next"]) != expected: raise DeviceError("Command sequence no longer matches this job")
                command = dict(job["commands"][accepted])
                if command["op"] == "pen":
                    command["angle"] = d["pen_up"] if command.pop("role") == "up" else d["pen_down"]
                await self.link.command(command)
                job["accepted"] = accepted+1; self.persist(job)
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            job.update(state="paused", message=str(exc)); self.persist(job)
            if self.link.connected:
                try: await self.link.control("pause")
                except Exception: await self.link.close()
        except (DeviceError, ValueError) as exc:
            job.update(state="error", message=str(exc)); self.persist(job)
            # Request a drain/pen-up if the link is still usable.
            if self.link.connected:
                with contextlib.suppress(Exception): await self.link.control("pause")

    async def pause(self):
        if self.active:
            self.jobs[self.active]["state"] = "paused"
        reply = await self.link.control("pause")
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        if self.active:
            self.jobs[self.active]["message"] = "Pausing after buffered movement"
            self.persist(self.jobs[self.active])
        return reply

    async def resume(self):
        if not self.active:
            d = self.link.state
            if not self.link.connected or not d.get("homed") or d.get("fault") or not d.get("paused") or d.get("moving"):
                raise ValueError("No safe retained position to resume; rehome after a reboot")
            if self.link.state.get("busy"):
                raise ValueError("Untracked retained commands; stop/reset before a new job")
            return await self.link.control("resume")
        job = self.jobs[self.active]
        if job["state"] != "paused": raise ValueError("Only a paused job can resume")
        if job["boot"] != self.link.state.get("boot"):
            raise ValueError("Robot rebooted; rehome and restart explicitly")
        self.validate_job(job)
        if not self.link.state.get("paused") or self.link.state.get("moving"):
            raise ValueError("Wait until buffered motion stops and the pen is up")
        await self.link.control("resume")
        job.update(state="running", message="Drawing"); self.persist(job)
        if job.get("execution")!="stored":self.worker = asyncio.create_task(self.run_job(job))
        return self.public_job(job)

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        try:
            await self.link.control("stop")
        finally:
            if self.active:
                job = self.jobs[self.active]
                job.update(state="cancelled", message="Stopped; reset and rehome before drawing")
                self.persist(job); self.active = None
        return self.snapshot()

    async def manual(self, op):
        async with self.operation_lock:
            if self.active: raise ValueError("Pause/stop the active job before manual controls")
            if self.pen_draft: raise ValueError("Use the pen calibration controls until saved or cancelled")
            if self.calibration_draft and op != "pen_up": raise ValueError("Finish calibration before using other manual controls")
            if op == "home":
                if not self.link.state.get("switch_homing_enabled"):
                    raise ValueError("Switch homing is not commissioned; use manual paper calibration")
                command = {"op":"home"}
            elif op in ("pen_up","pen_down"):
                command = {"op":"pen", "angle":self.link.state.get(op,90 if op=="pen_up" else 40)}
            else: raise ValueError("Unknown manual operation")
            reply = await self.link.command(command)
            await self.link.wait_completed(reply["id"])
            if op == "home" and not self.link.state.get("homed"):
                raise DeviceError("Homing failed; check USB diagnostics and calibration")
            return self.snapshot()

    async def close(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        await self.link.close()


class HttpServer:
    def __init__(self, controller, access_key=None):
        self.controller = controller
        self.key = access_key or secrets.token_urlsafe(24)

    def authorized(self, target, headers):
        supplied = parse_qs(urlsplit(target).query).get("access",[""])[0]
        supplied = supplied or headers.get("authorization","").removeprefix("Bearer ")
        if not supplied:
            for cookie in headers.get("cookie","").split(";"):
                if cookie.strip().startswith("drawy_access="): supplied = cookie.strip().split("=",1)[1]
        return hmac.compare_digest(supplied, self.key)

    async def handle(self, reader, writer):
        code, payload, mime, extra = 200, b"", "application/json", []
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            if len(header) > 16384: raise ValueError("Headers too large")
            lines = header.decode("latin1").split("\r\n")
            method, target, _ = lines[0].split(" ")
            headers = {k.lower().strip():v.strip() for k,v in
                       (line.split(":",1) for line in lines[1:] if ":" in line)}
            path = urlsplit(target).path
            if not self.authorized(target, headers):
                code, payload, mime = 403, b"Open the private controller URL printed in your terminal.", "text/plain"
            else:
                extra.append(("Set-Cookie",f"drawy_access={self.key}; HttpOnly; SameSite=Strict; Path=/"))
                if method == "GET" and path == "/":
                    payload, mime = (ROOT/"web"/"index.html").read_bytes(), "text/html; charset=utf-8"
                elif method == "GET" and path in ("/app.js", "/style.css"):
                    payload = (ROOT/"web"/path[1:]).read_bytes()
                    mime = "text/javascript" if path.endswith(".js") else "text/css"
                elif method == "GET" and path == "/api/status":
                    payload = json.dumps(self.controller.snapshot()).encode()
                elif method == "GET" and path.startswith("/api/jobs/"):
                    job = self.controller.jobs[path.rsplit("/",1)[-1]]
                    payload = json.dumps(self.controller.public_job(job, True)).encode()
                elif method == "POST" and path.startswith("/api/"):
                    origin = headers.get("origin")
                    if origin and urlsplit(origin).netloc != headers.get("host"):
                        raise ValueError("Cross-origin control is not allowed")
                    if "application/json" not in headers.get("content-type",""):
                        raise ValueError("Expected application/json")
                    if "transfer-encoding" in headers: raise ValueError("Chunked requests are not supported")
                    size = int(headers.get("content-length","0"))
                    if not 0 <= size <= MAX_BODY: raise ValueError("Upload limit exceeded")
                    body = await asyncio.wait_for(reader.readexactly(size), 20)
                    data = json.loads(body or b"{}")
                    result = await self.api(path, data)
                    payload = json.dumps(result, allow_nan=False).encode()
                else: code, payload = 404, b'{"error":"Not found"}'
        except KeyError:
            code, payload = 404, b'{"error":"Job not found"}'
        except (ValueError, DeviceError, ConnectionError, OSError, asyncio.TimeoutError) as exc:
            code, payload = 400, json.dumps({"error":str(exc)}).encode()
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            code, payload = 400, b'{"error":"Invalid HTTP request"}'
        except Exception:
            code, payload = 500, b'{"error":"Internal controller error"}'
        reasons = {200:"OK",400:"Bad Request",403:"Forbidden",404:"Not Found",500:"Internal Server Error"}
        response = [f"HTTP/1.1 {code} {reasons[code]}",f"Content-Type: {mime}",
                    f"Content-Length: {len(payload)}","Connection: close","Cache-Control: no-store",
                    "X-Content-Type-Options: nosniff","Referrer-Policy: no-referrer",
                    "Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"]
        response += [f"{k}: {v}" for k,v in extra]
        writer.write(("\r\n".join(response)+"\r\n\r\n").encode()+payload)
        with contextlib.suppress(OSError): await writer.drain()
        writer.close()
        with contextlib.suppress(OSError): await writer.wait_closed()

    async def api(self, path, data):
        c = self.controller
        if path == "/api/calibration": return await c.calibration_action(data)
        if path == "/api/pen-calibration": return await c.pen_calibration_action(data)
        if path == "/api/speeds": return await c.set_speeds(data)
        if path == "/api/import": return await c.import_async(data)
        if path == "/api/start": return await c.start(data["id"], data.get("reviewed",False))
        if path == "/api/pause": return await c.pause()
        if path == "/api/resume": return await c.resume()
        if path == "/api/stop": return await c.stop()
        if path == "/api/manual": return await c.manual(data["op"])
        raise ValueError("Unknown API endpoint")

async def serve(args):
    simulator = None
    if args.simulate:
        from .simulator import SimulatedRobot
        simulator = await SimulatedRobot(secrets.token_hex(16)).start()
        robot = RobotConfig("127.0.0.1", simulator.port, simulator.token)
    else:
        robot = load_robot_config(args.env_file)
    controller = Controller(args.data, robot)
    controller.simulation = bool(simulator)
    http = HttpServer(controller)
    server = await asyncio.start_server(http.handle, args.bind, args.port, limit=32768)
    address = server.sockets[0].getsockname()
    host = "127.0.0.1" if args.bind == "0.0.0.0" else args.bind
    print(f"Drawy controller: http://{host}:{address[1]}/?access={http.key}", flush=True)
    if args.bind == "0.0.0.0":
        print("For your phone, replace 127.0.0.1 with this computer's LAN IP. Keep the access link private.", flush=True)
    connection_task = asyncio.create_task(controller.maintain_connection())
    try:
        async with server: await server.serve_forever()
    finally:
        connection_task.cancel()
        await asyncio.gather(connection_task, return_exceptions=True)
        await controller.close()
        if simulator: await simulator.close()

def main():
    parser = argparse.ArgumentParser(description="Local Drawy robot controller")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--simulate", action="store_true", help="Use a hardware-free robot simulator")
    parser.add_argument("--env-file", type=Path, default=ENV_FILE, help="Fixed robot connection configuration; read only at startup")
    args = parser.parse_args()
    if args.data is None:
        args.data = Path("controller/demo-data" if args.simulate else "controller/data")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        print("Drawy controller stopped.")
    except ValueError as exc:
        parser.error(str(exc))

if __name__ == "__main__": main()
