"""Authenticated JSON-lines TCP transport with duplicate-safe retries."""
from __future__ import annotations
import asyncio
import json
import uuid

class DeviceError(RuntimeError):
    pass

class DeviceLink:
    def __init__(self, session=None, on_disconnect=None):
        self.session = session or str(uuid.uuid4())
        self.on_disconnect = on_disconnect
        self.reader = self.writer = None
        self.tasks = []
        self.pending = {}
        self.state = {}
        self.connected = False
        self.send_lock = asyncio.Lock()
        self.command_lock = asyncio.Lock()

    async def connect(self, host, token, port=9999):
        await self.close()
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, limit=16384), 5)
        try:
            await self._write({"type":"hello","session":self.session,"token":token})
            raw = await asyncio.wait_for(self.reader.readline(), 5)
            reply = json.loads(raw)
            if reply.get("type") != "hello":
                raise DeviceError(reply.get("error", "Invalid device handshake"))
            self.state = reply
            self.connected = True
            self.tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._heartbeat())]
            return dict(self.state)
        except BaseException:
            self.writer.close()
            await self.writer.wait_closed()
            raise

    async def _write(self, message):
        if not self.writer: raise ConnectionError("Device disconnected")
        wire = json.dumps(message, separators=(",",":"), sort_keys=True, allow_nan=False)+"\n"
        async with self.send_lock:
            self.writer.write(wire.encode())
            await asyncio.wait_for(self.writer.drain(), 2)

    def _lost(self, reason):
        was_connected = self.connected
        self.connected = False
        for future in self.pending.values():
            if not future.done(): future.set_exception(ConnectionError(reason))
        if was_connected and self.on_disconnect: self.on_disconnect(reason)
        if self.writer: self.writer.close()

    async def _read(self):
        try:
            while True:
                raw = await asyncio.wait_for(self.reader.readline(), 5)
                if not raw: raise ConnectionError("Device connection closed")
                message = json.loads(raw)
                if message.get("boot", self.state.get("boot")) != self.state.get("boot"):
                    raise ConnectionError("Device rebooted")
                if message.get("type") in ("status", "ack", "control"):
                    self.state.update(message)
                key = message.get("request") if message.get("type") == "control" else message.get("id")
                future = self.pending.get(key)
                if future and not future.done(): future.set_result(message)
                elif message.get("type") == "error":
                    # Control errors may have no command ID; wake their waiter.
                    for k, f in self.pending.items():
                        if isinstance(k, str) and not f.done():
                            f.set_result(message)
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, asyncio.TimeoutError, ConnectionError) as exc:
            self._lost(str(exc))

    async def _heartbeat(self):
        try:
            while self.connected:
                await self._write({"type":"ping"})
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except (OSError, asyncio.TimeoutError, ConnectionError) as exc:
            self._lost(str(exc))

    async def command(self, command):
        async with self.command_lock:
            if not self.connected: raise ConnectionError("Connect to the robot first")
            number = int(self.state["next"])
            message = dict(command, type="command", id=number, boot=self.state["boot"])
            # An acknowledgement timeout resends EXACT bytes with the same ID.
            for attempt in range(5):
                if not self.connected: raise ConnectionError("Device disconnected")
                future = asyncio.get_running_loop().create_future()
                self.pending[number] = future
                try:
                    await self._write(message)
                    try: reply = await asyncio.wait_for(asyncio.shield(future), 2)
                    except asyncio.TimeoutError:
                        continue
                    if reply.get("type") == "ack": return reply
                    code = reply.get("error", "Command rejected")
                    if code == "queue_full":
                        await asyncio.sleep(.1)
                        continue
                    raise DeviceError(code)
                finally:
                    self.pending.pop(number, None)
                    if not future.done(): future.cancel()
            self._lost("No acknowledgement; reconnect to reconcile command IDs")
            raise ConnectionError("No acknowledgement; reconnect to reconcile command IDs")

    async def control(self, operation):
        if not self.connected: raise ConnectionError("Device disconnected")
        request = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[request] = future
        try:
            await self._write({"type":operation, "boot":self.state["boot"], "request":request})
            reply = await asyncio.wait_for(future, 3)
            if reply.get("type") == "error": raise DeviceError(reply.get("error"))
            return reply
        finally:
            self.pending.pop(request, None)

    async def wait_completed(self, number, timeout=300):
        deadline = asyncio.get_running_loop().time()+timeout
        while int(self.state.get("completed", 0)) < number:
            if not self.connected: raise ConnectionError("Device disconnected")
            if self.state.get("fault"): raise DeviceError("Robot fault; reset and rehome")
            if self.state.get("holding") or self.state.get("paused"): raise DeviceError("Robot paused")
            if asyncio.get_running_loop().time() > deadline: raise TimeoutError("Command completion timed out")
            await asyncio.sleep(.03)

    async def close(self):
        self._lost("Controller disconnected")
        tasks, self.tasks = self.tasks, []
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        if self.writer:
            try: await self.writer.wait_closed()
            except OSError: pass
        self.reader = self.writer = None
