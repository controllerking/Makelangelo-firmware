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

from .artwork import PAPER, demo_paths, prepare, svg_paths, finite
from .transport import DeviceLink, DeviceError
from .raster import PRESETS, preset, raster_paths

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
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        config_path = self.data_dir/"connection.json"
        self.config = json.loads(config_path.read_text()) if config_path.exists() else {
            "session":str(uuid.uuid4()), "host":"drawy.local", "port":9999, "token":""}
        self.link = DeviceLink(self.config["session"], self.disconnected)
        self.jobs = {}
        if (self.data_dir/"jobs").exists():
            for path in (self.data_dir/"jobs").glob("*.json"):
                if path.name.endswith(".state.json"): continue;
                job = json.loads(path.read_text())
                journal = path.with_suffix(".state.json")
                if journal.exists(): job.update(json.loads(journal.read_text()))
                if job["state"] == "running": job["state"] = "paused"
                self.jobs[job["id"]] = job
        self.active = next((j["id"] for j in self.jobs.values() if j["state"] == "paused"), None)
        self.worker = None
        self.operation_lock = asyncio.Lock()
        self.preparation_lock = asyncio.Lock()
        self.simulation = False

    def persist(self, job):
        path = self.data_dir/"jobs"/(job["id"]+".json")
        if not path.exists():
            save_json(path, job)
        else:
            save_json(path.with_suffix(".state.json"),
                      {k:v for k,v in job.items() if k not in ("commands","paths")})

    def disconnected(self, reason):
        if self.active and self.active in self.jobs:
            job = self.jobs[self.active]
            if job["state"] == "running":
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
            if job.get("base_id") and job.get("boot") == state.get("boot"):
                job["completed"] = max(job.get("completed",0),
                    min(job["command_count"], max(0, state.get("completed",0)-job["base_id"]+1)))
        return {"connected":self.link.connected, "device":dict(state),
                "simulation":self.simulation,
                "host":self.config["host"], "port":self.config["port"], "active":self.active,
                "jobs":[self.public_job(j) for j in sorted(self.jobs.values(), key=lambda j:j["created"], reverse=True)],
                "papers":PAPER, "presets":PRESETS}

    async def connect(self, data):
        host = str(data.get("host") or self.config["host"]).strip()
        port = int(data.get("port", self.config.get("port",9999)))
        token = str(data.get("token") or self.config["token"]).strip()
        if not host or not 1 <= port <= 65535 or not token:
            raise ValueError("Enter the robot address and pairing key from its setup page")
        if self.worker and not self.worker.done():
            raise ValueError("Pause the current job before reconnecting")
        state = await self.link.connect(host, token, port)
        self.config.update(host=host, port=port, token=token)
        save_json(self.data_dir/"connection.json", self.config)
        if self.active:
            job = self.jobs[self.active]
            if job.get("boot") and job["boot"] != state["boot"]:
                job["state"] = "interrupted"
                job["message"] = "Robot rebooted. Rehome and explicitly restart; automatic resume is blocked."
                self.persist(job); self.active = None
        return self.snapshot()

    def build_artwork(self, data, device):
        if not isinstance(data, dict): raise ValueError("Expected an artwork object")
        options = data.get("options", {})
        if not isinstance(options, dict): raise ValueError("Expected artwork options")
        quality, profile = preset(options)
        options = dict(options)
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
        if device.get("reference") == "manual":
            options["feed"] = min(2., finite(options["feed"], "feed"))
            warnings.append("Temporary manual reference: speed capped at 2 mm/s; its limited travel envelope still applies.")
        prepared = prepare(paths, options, device.get("pen_up",90), device.get("pen_down",40), source_bounds)
        prepared.update(metadata, path_count=len(paths), feed=float(options["feed"]))
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
        if not self.link.connected: raise ValueError("Connect to the robot first")
        d = self.link.state
        if not d.get("homed"): raise ValueError("Home the calibrated robot first")
        if d.get("fault"): raise ValueError("Reset the robot and rehome after a fault")
        limits = d["limits"]
        for command in job["commands"]:
            if command["op"] == "move":
                x,y = command["x"],command["y"]
                if not limits[0][0] <= x <= limits[0][1] or not limits[1][0] <= y < limits[1][1]:
                    raise ValueError("Drawing lies outside the robot's calibrated limits")

    async def start(self, job_id, reviewed=False):
        if not reviewed: raise ValueError("Confirm the paper position and collision clearance first")
        if self.active: raise ValueError("Finish or stop the active job first")
        job = self.jobs[job_id]
        if job["state"] not in ("queued","completed","interrupted","cancelled","error"):
            raise ValueError("Job is not ready to start")
        self.validate_job(job)
        if self.link.state.get("holding") or self.link.state.get("paused"):
            raise ValueError("Resolve the robot's paused state before starting a new job")
        # Match the robot's configured servo angles even after recalibration.
        job.update(pen_up=self.link.state["pen_up"], accepted=0, completed=0,
                   base_id=int(self.link.state["next"]), boot=self.link.state["boot"],
                   state="running", message="Drawing", started=time.time())
        self.active = job_id; self.persist(job)
        self.worker = asyncio.create_task(self.run_job(job))
        return self.public_job(job)

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
        self.worker = asyncio.create_task(self.run_job(job))
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
            if op == "home": command = {"op":"home"}
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
        if path == "/api/connect": return await c.connect(data)
        if path == "/api/disconnect": await c.link.close(); return c.snapshot()
        if path == "/api/import": return await c.import_async(data)
        if path == "/api/start": return await c.start(data["id"], data.get("reviewed",False))
        if path == "/api/pause": return await c.pause()
        if path == "/api/resume": return await c.resume()
        if path == "/api/stop": return await c.stop()
        if path == "/api/manual": return await c.manual(data["op"])
        raise ValueError("Unknown API endpoint")

async def serve(args):
    controller = Controller(args.data)
    simulator = None
    if args.simulate:
        from .simulator import SimulatedRobot
        simulator = await SimulatedRobot(secrets.token_hex(16)).start()
        controller.simulation = True
        await controller.connect({"host":"127.0.0.1","port":simulator.port,"token":simulator.token})
    http = HttpServer(controller)
    server = await asyncio.start_server(http.handle, args.bind, args.port, limit=32768)
    address = server.sockets[0].getsockname()
    host = "127.0.0.1" if args.bind == "0.0.0.0" else args.bind
    print(f"Drawy controller: http://{host}:{address[1]}/?access={http.key}", flush=True)
    if args.bind == "0.0.0.0":
        print("For your phone, replace 127.0.0.1 with this computer's LAN IP. Keep the access link private.", flush=True)
    try:
        async with server: await server.serve_forever()
    finally:
        await controller.close()
        if simulator: await simulator.close()

def main():
    parser = argparse.ArgumentParser(description="Local Drawy robot controller")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--simulate", action="store_true", help="Use a hardware-free robot simulator")
    args = parser.parse_args()
    if args.data is None:
        args.data = Path("controller/demo-data" if args.simulate else "controller/data")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        print("Drawy controller stopped.")

if __name__ == "__main__": main()
