import json
from pathlib import Path
import tempfile
import unittest

from controller.config import RobotConfig
from controller.server import Controller
from controller.simulator import SimulatedRobot


class PenCalibrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.robot=await SimulatedRobot(delay=.002).start()
        self.c=Controller(Path(self.temp.name),RobotConfig("127.0.0.1",self.robot.port,self.robot.token))
        await self.c.connect()

    async def asyncTearDown(self):
        await self.c.close();await self.robot.close();self.temp.cleanup()

    async def action(self,action,**values):
        return await self.c.pen_calibration_action(dict(action=action,**values))

    async def test_save_and_reboot_without_paper_homing_or_xy_motion(self):
        xy=self.robot.x,self.robot.y
        with self.assertRaises(ValueError): await self.action("begin")
        await self.action("begin",confirmed=True)
        await self.action("capture",role="up")
        await self.action("adjust",delta=-5)
        await self.action("capture",role="down")
        await self.action("test",role="up")
        self.assertEqual(self.robot.pen,90)
        await self.action("test",role="down")
        self.assertEqual(self.robot.pen,85)
        await self.action("save")
        self.assertEqual((self.robot.pen_up,self.robot.pen_down,self.robot.pen),(90,85,90))
        self.assertEqual((self.robot.x,self.robot.y),xy)
        self.assertFalse(self.robot.homed)
        saved=json.loads((Path(self.temp.name)/"pen_calibration.json").read_text())
        self.assertEqual((saved["up"],saved["down"]),(90,85))
        self.robot.reboot()
        await self.c.connect()
        self.assertTrue(self.c.link.state["pen_calibrated"])
        self.assertEqual(self.c.link.state["pen_down"],85)

    async def test_range_validation_cancel_and_reversed_linkage(self):
        await self.action("begin",confirmed=True)
        await self.action("capture",role="up")
        await self.action("capture",role="down")
        with self.assertRaises(ValueError):await self.action("save")
        for delta in (0,6,True):
            with self.assertRaises(ValueError):await self.action("adjust",delta=delta)
        self.c.pen_draft["angle"]=170
        with self.assertRaises(ValueError):await self.action("adjust",delta=1)
        await self.action("cancel")
        self.assertIsNone(self.c.pen_draft)
        self.assertFalse(self.robot.pen_tuning)
        await self.action("begin",confirmed=True)
        await self.action("capture",role="down")
        await self.action("adjust",delta=-5)
        await self.action("capture",role="up")
        await self.action("save")
        self.assertEqual((self.robot.pen_up,self.robot.pen_down,self.robot.pen),(85,90,85))
        await self.c.link.control("stop")
        self.assertEqual(self.robot.pen,85)

    async def test_coarse_adjustment_and_direct_angle(self):
        await self.action("begin",confirmed=True)
        await self.action("adjust",delta=30)
        self.assertEqual(self.robot.pen,120)
        await self.action("adjust",delta=-10)
        self.assertEqual(self.robot.pen,110)
        for angle in (9,171,90.5,True,None):
            with self.assertRaises(ValueError):await self.action("set",angle=angle)
        for angle in (10,170,90):
            await self.action("set",angle=angle)
            self.assertEqual(self.robot.pen,angle)
        self.assertEqual((self.robot.x,self.robot.y),(400,-200))

    async def test_exclusion_stale_boot_and_changed_job_angles(self):
        job=self.c.import_artwork({"svg":"<svg><path d='M0 0L1 1'/></svg>","options":{"paper":"Letter","left":200,"top":-170}})
        await self.action("begin",confirmed=True)
        with self.assertRaises(ValueError):await self.c.calibration_action({"action":"begin"})
        with self.assertRaises(ValueError):await self.c.manual("pen_down")
        async with self.c.operation_lock:
            with self.assertRaises(ValueError):await self.action("adjust",delta=1)
        await self.action("capture",role="up")
        await self.action("adjust",delta=-5)
        await self.action("capture",role="down")
        await self.action("save")
        with self.assertRaisesRegex(ValueError,"Pen positions changed"):
            self.c.validate_job(self.c.jobs[job["id"]])
        await self.action("begin",confirmed=True)
        self.c.pen_draft["boot"]="stale"
        with self.assertRaises(ValueError):await self.action("adjust",delta=1)
