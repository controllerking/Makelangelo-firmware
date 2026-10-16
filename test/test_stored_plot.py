import asyncio
import base64
from pathlib import Path
import tempfile
import unittest
import uuid
import zlib
from controller.config import RobotConfig
from controller.server import Controller
from controller.simulator import SimulatedRobot
from controller.transport import DeviceError
from controller.plot import encode_plot,RECORD,MAX_BYTES

class StoredPlotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.robot=await SimulatedRobot(delay=.01,storage=True).start()
        self.robot.homed=True;self.robot.reference="user";self.robot.calibration_id=str(uuid.uuid4())
        self.robot.draw_bounds=[197,-452.4,418.9,-167]
        self.robot.limits=[[0,644.525],[-452.4,0]]
        self.c=Controller(Path(self.temp.name),RobotConfig("127.0.0.1",self.robot.port,self.robot.token))
        self.c.calibration={"id":self.robot.calibration_id,"paper":"Letter","width":644.525,"spu":[80,80],"left":200,"top":-170}
        await self.c.connect()

    async def asyncTearDown(self):
        await self.c.close();await self.robot.close();self.temp.cleanup()

    def job(self):
        points=" ".join(f"{i},{i%3}" for i in range(60))
        return self.c.import_artwork({"svg":f'<svg><polyline points="{points}"/></svg>'})

    async def test_upload_then_disconnect_completes_and_reconnect_reconciles(self):
        j=self.job()
        await self.c.start(j["id"],True)
        self.assertTrue(self.robot.plot_saved)
        self.assertEqual(self.robot.next,1,"Stored execution must not consume streaming IDs")
        await self.c.link.close()
        self.assertEqual(self.c.jobs[j["id"]]["state"],"running")
        for _ in range(200):
            if not self.robot.plot_running:break
            await asyncio.sleep(.01)
        self.assertFalse(self.robot.hold)
        self.assertEqual(self.robot.plot_state,"completed")
        self.assertEqual(self.robot.pen,self.robot.pen_up)
        await self.c.connect()
        self.assertIsNone(self.c.active)
        self.assertEqual(self.c.jobs[j["id"]]["state"],"completed")

    async def test_explicit_pause_resume_and_stop_still_work(self):
        j=self.job();await self.c.start(j["id"],True)
        await self.c.pause();await asyncio.sleep(.03)
        done=self.robot.plot_completed
        await asyncio.sleep(.05)
        self.assertEqual(self.robot.plot_completed,done)
        await self.c.resume();await asyncio.sleep(.05)
        self.assertGreater(self.robot.plot_completed,done)
        await self.c.stop()
        self.assertFalse(self.robot.plot_running)
        self.assertTrue(self.robot.fault)

    async def test_partial_upload_checksum_and_duplicate_start(self):
        payload=RECORD.pack(1,0,0,0)+RECORD.pack(3,0,0,0)
        job=str(uuid.uuid4());run=str(uuid.uuid4())
        meta=dict(job=job,cal=self.robot.calibration_id,count=2,crc=0,up=90,down=40,spu0=80,spu1=80,confirm=True)
        await self.c.link.control("plot_begin",**meta)
        with self.assertRaisesRegex(DeviceError,"incomplete"):await self.c.link.control("plot_commit")
        chunk=dict(offset=0,data=base64.b64encode(payload).decode())
        await self.c.link.control("plot_chunk",**chunk)
        await self.c.link.control("plot_chunk",**chunk)
        self.assertEqual(len(self.robot.plot_data),32)
        with self.assertRaisesRegex(DeviceError,"checksum"):await self.c.link.control("plot_commit")
        self.assertFalse(self.robot.plot_running)
        meta["crc"]=zlib.crc32(payload)
        await self.c.link.control("plot_begin",**meta)
        await self.c.link.control("plot_chunk",**chunk)
        await self.c.link.control("plot_commit")
        self.robot.calibration_id="changed"
        with self.assertRaisesRegex(DeviceError,"reference"):await self.c.link.control("plot_start",job=job,run=run,confirm=True)
        self.robot.calibration_id=meta["cal"]
        await self.c.link.control("plot_start",job=job,run=run,confirm=True)
        await asyncio.sleep(.08)
        await self.c.link.control("plot_start",job=job,run=run,confirm=True)
        self.assertEqual(self.robot.plot_state,"completed")

    async def test_reboot_keeps_file_but_never_resumes_unknown_position(self):
        j=self.job();await self.c.start(j["id"],True)
        self.robot.reboot()
        await self.c.connect()
        self.assertTrue(self.robot.plot_saved)
        self.assertFalse(self.robot.plot_running)
        self.assertFalse(self.robot.homed)
        self.assertEqual(self.c.jobs[j["id"]]["state"],"interrupted")
        with self.assertRaises(DeviceError):
            await self.c.link.control("plot_start",job=j["id"],run=str(uuid.uuid4()),confirm=True)

    def test_compact_format_bounds_and_roles(self):
        payload,crc=encode_plot({"commands":[{"op":"pen","role":"up"},{"op":"sync"}]})
        self.assertEqual(len(payload),32)
        self.assertEqual(crc,zlib.crc32(payload))
        for commands in ([{"op":"home"}],[{"op":"pen","role":"down"},{"op":"sync"}],
                         [{"op":"sync"}]*(MAX_BYTES//16+1)):
            with self.assertRaises(ValueError):encode_plot({"commands":commands})
