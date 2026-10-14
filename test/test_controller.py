from __future__ import annotations
import asyncio
import base64
import json
import math
from pathlib import Path
import tempfile
import unittest

from controller.artwork import path_data, prepare, svg_paths, transform, point
from controller.server import Controller, HttpServer
from controller.simulator import SimulatedRobot
from controller.transport import DeviceLink, DeviceError

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M0 0 L100 0 L100 100 L0 100 Z"/></svg>'
OPTIONS = {"paper":"A4","left":100,"top":-100,"margin":20,"feed":10}

async def until(predicate, timeout=5):
    end = asyncio.get_running_loop().time()+timeout
    while not predicate():
        if asyncio.get_running_loop().time()>end: raise TimeoutError("Test condition timed out")
        await asyncio.sleep(.01)

class ArtworkTests(unittest.TestCase):
    def test_curves_arcs_transforms_and_units(self):
        paths = path_data("M0 0 c0 100 100 100 100 0 s100 -100 100 0 q50 100 100 0 t100 0 a50 50 0 0 1 100 0 z")
        self.assertGreater(len(paths[0]),30)
        self.assertEqual(paths[0][-1],(0,0))
        m = transform("translate(10,20) scale(2)")
        self.assertEqual(point(m,(3,4)),(16,28))
        paths,warnings = svg_paths('<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(10 20)"><line x1="1mm" y1="0" x2="10mm" y2="10"/></g></svg>')
        self.assertAlmostEqual(paths[0][0][0],10+96/25.4)
        self.assertFalse(warnings)

    def test_viewbox_and_paper_placement(self):
        paths,_ = svg_paths(SVG)
        job = prepare(paths,OPTIONS)
        self.assertEqual(job["paper_rect"],[100.,-100.,210.,297.])
        self.assertEqual(job["bounds"],[120.,-333.5,290.,-163.5])
        self.assertEqual(job["commands"][0]["role"],"up")
        self.assertEqual(job["commands"][2]["role"],"down")
        self.assertEqual(job["commands"][-1]["op"],"sync")
        self.assertGreater(job["estimated_seconds"],0)

    def test_unsafe_and_unsupported_svg_rejected(self):
        for svg in ('<!DOCTYPE svg [<!ENTITY x "x">]><svg/>',
                    '<svg><image href="https://example.com/a.png"/></svg>',
                    '<svg><path d="M 1"/></svg>',
                    '<svg><text>hello</text></svg>',
                    '<svg><g clip-path="url(#x)"><path d="M0 0L1 1"/></g></svg>'):
            with self.subTest(svg=svg), self.assertRaises(ValueError): svg_paths(svg)

    def test_relative_subpaths_and_reflection(self):
        p = path_data("m10 10 10 0 0 10 z m20 0 l5 5")
        self.assertEqual(p[0],[(10,10),(20,10),(20,20),(10,10)])
        self.assertEqual(p[1],[(30,10),(35,15)])
        p,_ = svg_paths('<svg><defs><path id="p" d="M0 0L10 10"/></defs><use href="#p" x="20"/></svg>')
        self.assertEqual(p[0],[(20,0),(30,10)])

class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.robot = await SimulatedRobot(delay=.03).start()
        self.controller = Controller(Path(self.temp.name))
        await self.controller.connect({"host":"127.0.0.1","port":self.robot.port,"token":self.robot.token})

    async def asyncTearDown(self):
        await self.controller.close()
        await self.robot.close()
        self.temp.cleanup()

    async def ready(self):
        await self.controller.manual("home")

    def job(self):
        return self.controller.import_artwork({"svg":SVG,"name":"test.svg","options":OPTIONS})

    async def test_full_job_and_persistent_history(self):
        await self.ready()
        job = self.job()
        await self.controller.start(job["id"],True)
        await until(lambda:self.controller.jobs[job["id"]]["state"]=="completed")
        self.assertEqual(self.robot.pen,90)
        self.assertEqual(len(self.robot.executions),len(set(self.robot.executions)))
        restored = Controller(Path(self.temp.name))
        self.assertEqual(restored.jobs[job["id"]]["state"],"completed")
        self.assertEqual(len(restored.jobs[job["id"]]["commands"]),job["command_count"])
        await restored.close()

    async def test_dropped_ack_retry_does_not_repeat_motion(self):
        await self.ready()
        self.robot.suppress_next_ack = True
        ack = await self.controller.link.command({"op":"move","x":300.,"y":-300.,"feed":10.})
        self.assertTrue(ack["duplicate"])
        await self.controller.link.wait_completed(ack["id"])
        self.assertEqual(self.robot.executions.count(ack["id"]),1)

    async def test_disconnect_reconcile_and_explicit_resume(self):
        await self.ready()
        self.robot.delay = .15
        job = self.job()
        self.robot.drop_next_ack = True
        await self.controller.start(job["id"],True)
        await until(lambda:self.controller.jobs[job["id"]]["state"]=="paused")
        await until(lambda:self.robot.paused)
        self.assertEqual(self.robot.pen,90)
        await self.controller.connect({})
        self.assertEqual(self.controller.jobs[job["id"]]["state"],"paused")
        await self.controller.resume()
        await until(lambda:self.controller.jobs[job["id"]]["state"]=="completed",8)
        self.assertEqual(len(self.robot.executions),len(set(self.robot.executions)))

    async def test_pause_retains_queue_and_pen_restore(self):
        await self.ready()
        self.robot.delay = .15
        job = self.job()
        await self.controller.start(job["id"],True)
        await until(lambda:len(self.robot.queue)>=3)
        await self.controller.pause()
        await until(lambda:self.controller.link.state.get("paused"))
        self.assertEqual(self.robot.pen,90)
        self.assertTrue(self.robot.queue)
        await self.controller.resume()
        await until(lambda:self.controller.jobs[job["id"]]["state"]=="completed",8)

    async def test_reboot_blocks_resume_and_requires_home(self):
        await self.ready()
        self.robot.delay = .3
        job = self.job()
        await self.controller.start(job["id"],True)
        await until(lambda:bool(self.robot.queue))
        self.robot.reboot()
        await until(lambda:not self.controller.link.connected)
        await asyncio.sleep(.05)
        await self.controller.connect({})
        self.assertEqual(self.controller.jobs[job["id"]]["state"],"interrupted")
        with self.assertRaises(ValueError): await self.controller.resume()
        with self.assertRaises(ValueError): await self.controller.start(job["id"],True)

    async def test_emergency_stop_discards_queue_and_blocks_motion(self):
        await self.ready()
        self.robot.delay = .2
        job = self.job()
        await self.controller.start(job["id"],True)
        await until(lambda:bool(self.robot.queue))
        await self.controller.stop()
        self.assertTrue(self.robot.fault)
        self.assertFalse(self.robot.homed)
        self.assertFalse(self.robot.queue)
        self.assertEqual(self.robot.pen,90)
        with self.assertRaises(DeviceError): await self.controller.manual("home")

    async def test_queue_full_not_accepted_and_id_conflict(self):
        await self.ready()
        self.robot.delay = 10
        link = self.controller.link
        commands=[]
        for i in range(8):
            command={"op":"move","x":300.+i,"y":-300.,"feed":10.}
            commands.append(command); await link.command(command)
        self.assertEqual(len(self.robot.queue),8)
        reader,writer = await asyncio.open_connection("127.0.0.1",self.robot.port)
        # A second connection cannot seize the robot.
        self.assertEqual(await asyncio.wait_for(reader.read(),1),b"")
        writer.close();await writer.wait_closed()
        next_before=self.robot.next
        with self.assertRaises(ConnectionError):
            await link.command({"op":"move","x":400.,"y":-300.,"feed":10.})
        self.assertEqual(self.robot.next,next_before)

    async def test_unhomed_and_out_of_bounds_jobs(self):
        job=self.job()
        with self.assertRaises(ValueError): await self.controller.start(job["id"],True)
        await self.ready()
        outside=self.controller.import_artwork({"svg":SVG,"options":dict(OPTIONS,left=2000)})
        with self.assertRaises(ValueError): await self.controller.start(outside["id"],True)

    async def test_pairing_rejects_wrong_key(self):
        await self.controller.link.close()
        other=DeviceLink()
        try:
            with self.assertRaises(DeviceError):
                await other.connect("127.0.0.1","wrong-key",self.robot.port)
        finally: await other.close()

    async def test_service_restart_reconciles_retained_job(self):
        await self.ready()
        self.robot.delay=.12
        job=self.job()
        await self.controller.start(job["id"],True)
        await until(lambda:len(self.robot.queue)>=3)
        await self.controller.close()
        await until(lambda:self.robot.paused)
        restored=Controller(Path(self.temp.name))
        self.controller=restored
        await restored.connect({})
        self.assertEqual(restored.active,job["id"])
        await restored.resume()
        await until(lambda:restored.jobs[job["id"]]["state"]=="completed",8)
        self.assertEqual(len(self.robot.executions),len(set(self.robot.executions)))

    async def test_idle_pen_disconnect_can_resume_without_job(self):
        await self.ready()
        await self.controller.manual("pen_down")
        await self.controller.link.close()
        await until(lambda:self.robot.paused)
        await self.controller.connect({})
        await self.controller.resume()
        self.assertFalse(self.robot.hold)

    async def test_http_auth_import_preview_and_job(self):
        http=HttpServer(self.controller,"private-test-key")
        server=await asyncio.start_server(http.handle,"127.0.0.1",0)
        port=server.sockets[0].getsockname()[1]
        async def request(path,method="GET",body=None,authorized=True,origin=None):
            reader,writer=await asyncio.open_connection("127.0.0.1",port)
            payload=json.dumps(body or {}).encode()
            headers=[f"{method} {path} HTTP/1.1",f"Host: 127.0.0.1:{port}","Content-Type: application/json",f"Content-Length: {len(payload)}"]
            if authorized: headers.append("Authorization: Bearer private-test-key")
            if origin:headers.append("Origin: "+origin)
            writer.write(("\r\n".join(headers)+"\r\n\r\n").encode()+payload);await writer.drain()
            result=await reader.read();writer.close();await writer.wait_closed()
            head,body=result.split(b"\r\n\r\n",1)
            return int(head.split(b" ")[1]),body
        try:
            code,_=await request("/",authorized=False);self.assertEqual(code,403)
            code,body=await request("/");self.assertEqual(code,200);self.assertIn(b"Drawing studio",body)
            code,body=await request("/api/import","POST",{"svg":SVG,"options":OPTIONS})
            self.assertEqual(code,200)
            job=json.loads(body);self.assertTrue(job["paths"])
            code,body=await request("/api/import","POST",{
                "image":{"width":8,"height":8,"pixels":base64.b64encode(bytes(64)).decode()},
                "name":"test.png","options":dict(OPTIONS,quality="fast",image_mode="outlines")})
            self.assertEqual(code,200)
            self.assertEqual(json.loads(body)["source_type"],"image")
            code,_=await request("/api/import","POST",{"image":{"width":9999},"options":OPTIONS})
            self.assertEqual(code,400)
            code,_=await request("/api/manual","POST",{"op":"home"},origin="https://evil.example")
            self.assertEqual(code,400)
            await self.ready()
            code,_=await request("/api/start","POST",{"id":job["id"],"reviewed":True})
            self.assertEqual(code,200)
            await until(lambda:self.controller.jobs[job["id"]]["state"]=="completed")
            code,body=await request("/api/status")
            self.assertEqual(next(j for j in json.loads(body)["jobs"] if j["id"]==job["id"])["state"],"completed")
        finally:
            server.close();await server.wait_closed()

if __name__ == "__main__": unittest.main()
