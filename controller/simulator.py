"""A hardware-free protocol simulator for tests and UI development."""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import json
import secrets
import time

class SimulatedRobot:
    def __init__(self, token="simulation-only", delay=.04):
        self.token, self.delay = token, delay
        self.boot, self.session = secrets.token_hex(8), ""
        self.next, self.completed = 1, 0
        self.receipts, self.queue, self.executions = {}, [], []
        self.homed, self.fault, self.hold, self.paused = False, False, False, False
        self.x, self.y, self.pen = 400., -200., 90
        self.held_pen = 90
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

    async def start(self, port=0):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", port)
        self.port = self.server.sockets[0].getsockname()[1]
        self.task = asyncio.create_task(self.tick())
        return self

    def state(self, kind="status"):
        return {"type":kind,"boot":self.boot,"session":self.session,"next":self.next,
                "accepted":self.next-1,"completed":self.completed,"queue_free":8-len(self.queue),
                "planner_free":15,"homed":self.homed,"fault":self.fault,"paused":self.paused,
                "holding":self.hold,"busy":bool(self.queue or self.active_command),
                "moving":bool(self.active_command),"homing":False,"x":self.x,"y":self.y,
                "pen":self.pen,"pen_up":90,"pen_down":40,"limits":[[0,1000],[-1200,0]],
                "position_kind":"planned" if self.active_command else "settled","error":self.error}

    async def emit(self, message, writer=None):
        w = writer or self.writer
        if w and not w.is_closing():
            try:
                w.write((json.dumps(message,separators=(",",":"))+"\n").encode())
                await w.drain()
            except (OSError, ConnectionError): pass

    def lose(self):
        if self.authenticated and (self.queue or self.active_command or self.pen != 90):
            self.hold = True
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
                if kind in ("pause","resume","stop"):
                    if kind == "pause": self.hold = True
                    if kind == "resume":
                        if message.get("boot") != self.boot or not self.paused or self.active_command or not self.homed or self.fault:
                            await self.emit({"type":"error","error":"resume_not_safe"}); continue
                        self.hold = self.paused = False; self.pen = self.held_pen
                    if kind == "stop":
                        self.fault = True; self.homed = False; self.hold = self.paused = True
                        self.queue.clear(); self.active_command = None; self.pen = 90
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
                elif self.hold: fail = "paused"
                elif len(self.queue) >= 8: fail = "queue_full"
                elif message.get("op") == "move" and not self.homed: fail = "invalid_move_or_unhomed"
                if fail:
                    await self.emit({"type":"error","error":fail,"id":number,"next":self.next}); continue
                self.receipts[number] = fingerprint
                if number-32 in self.receipts: del self.receipts[number-32]
                self.next += 1; self.queue.append(message)
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

    async def tick(self):
        last_status = 0.
        while True:
            now = time.monotonic()
            if self.writer and now-self.last_seen > self.heartbeat_timeout: self.lose()
            if self.hold and not self.paused:
                if self.active_command and self.active_command["op"] == "move":
                    # Model a partially planned line: only buffered movement finishes.
                    self.x = (self.x+self.active_command["x"])/2
                    self.y = (self.y+self.active_command["y"])/2
                self.active_command = None
                self.held_pen = self.pen; self.pen = 90; self.paused = True
            elif not self.hold and not self.fault:
                if self.active_command and now >= self.busy_until:
                    command = self.active_command
                    if command["op"] == "move": self.x,self.y = command["x"],command["y"]
                    elif command["op"] == "pen": self.pen = command["angle"]
                    elif command["op"] == "home": self.homed = True
                    self.executions.append(command["id"])
                    self.completed = command["id"]; self.queue.pop(0); self.active_command = None
                if self.queue and not self.active_command:
                    self.active_command = self.queue[0]; self.busy_until = now+self.delay
            if self.authenticated and now-last_status > .025:
                await self.emit(self.state()); last_status = now
            await asyncio.sleep(.005)

    def reboot(self):
        self.lose(); self.boot = secrets.token_hex(8); self.session = ""
        self.next, self.completed = 1, 0
        self.receipts.clear(); self.queue.clear(); self.active_command = None
        self.homed = self.fault = self.hold = self.paused = False
        self.pen = 90

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
