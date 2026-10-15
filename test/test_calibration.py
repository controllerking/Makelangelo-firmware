import asyncio
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from controller.calibration import CORNERS, fit
from controller.config import RobotConfig
from controller.server import Controller
from controller.simulator import SimulatedRobot


def captures(left=200,top=-170):
    width,pw,ph=644.525,215.9,279.4
    points=[(left,top),(left+pw,top),(left+pw,top-ph),(left,top-ph)]
    return {name:[round((math.hypot(x,y)-381)*80),round((math.hypot(width-x,y)-406.4)*80)]
            for name,(x,y) in zip(CORNERS,points)}


def draft():
    return {"paper":"Letter","width":644.525,"spu":[80,80],"corners":captures()}


class CalibrationMathTests(unittest.TestCase):
    def test_fit_absolute_lengths_and_paper_from_relative_counts(self):
        for left,top in ((200,-170),(100,-100),(300,-300)):
            # Last case intentionally extends beyond the anchor span.
            if left+215.9>624.525:continue
            d=draft();d["corners"]=captures(left,top)
            cal=fit(d)
            self.assertAlmostEqual(cal["left"],left,delta=.1)
            self.assertAlmostEqual(cal["top"],top,delta=.1)
            self.assertAlmostEqual(cal["zero_belts"][0],381,delta=.1)
            self.assertAlmostEqual(cal["zero_belts"][1],406.4,delta=.1)
            self.assertLess(cal["max_error_mm"],.1)

    def test_bad_missing_degenerate_reversed_and_wrong_corners(self):
        bad=[]
        d=draft();del d["corners"]["bottom_left"];bad.append(d)
        d=draft();d["corners"]={key:[0,0] for key in CORNERS};bad.append(d)
        d=draft();d["corners"]={k:[-v[0],v[1]] for k,v in d["corners"].items()};bad.append(d)
        d=draft();d["corners"]["bottom_right"],d["corners"]["bottom_left"]=d["corners"]["bottom_left"],d["corners"]["bottom_right"];bad.append(d)
        for d in bad:
            with self.subTest(corners=d["corners"]),self.assertRaises(ValueError):fit(d)

    def test_rotated_paper_and_captured_shape_without_residual_cutoff(self):
        angle=.18
        d=draft()
        points=[(200+math.cos(angle)*x+math.sin(angle)*y,
                 -170+math.sin(angle)*x-math.cos(angle)*y)
                for x,y in ((0,0),(215.9,0),(215.9,279.4),(0,279.4))]
        d["corners"]={name:[round((math.hypot(x,y)-381)*80),round((math.hypot(644.525-x,y)-406.4)*80)]
                      for name,(x,y) in zip(CORNERS,points)}
        cal=fit(d)
        for key,point in zip(CORNERS,points):
            self.assertLess(math.dist(cal["corners"][key]["xy"],point),.1)
        d=draft();d["corners"]["bottom_right"][0]+=800
        self.assertGreater(fit(d)["max_error_mm"],3)
        # Exact captures from the user's rejected session remain acceptable.
        d["corners"]=dict(zip(CORNERS,[[-6400,2400],[1600,-6400],[14400,7200],[7200,15200]]))
        self.assertEqual(fit(d)["version"],2)

    def test_artwork_maps_to_captured_corners(self):
        from controller.artwork import prepare
        corners=[[200,-170],[400,-140],[440,-420],[190,-450]]
        job=prepare([[(0,0),(215.9,0),(215.9,279.4),(0,279.4)]],
                    {"paper":"Letter","left":200,"top":-170,"margin":0,"paper_corners":corners})
        self.assertEqual(list(job["paths"][0][0]),corners[0])
        self.assertEqual(list(job["paths"][0][-1]),corners[3])
        for corner in corners:
            self.assertIn(tuple(corner),job["paths"][0])


class CalibrationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.robot=await SimulatedRobot(delay=.002).start()
        self.config=RobotConfig("127.0.0.1",self.robot.port,self.robot.token)
        self.c=Controller(Path(self.temp.name),self.config)
        await self.c.connect()

    async def asyncTearDown(self):
        await self.c.close();await self.robot.close();self.temp.cleanup()

    async def begin(self):
        await self.c.calibration_action({"action":"begin","paper":"Letter","width":644.525,"confirmed":True})

    async def collect(self):
        await self.begin()
        # Inject fixture encoder counts at physical corners; test individual
        # jog execution/dedup separately, avoiding thousands of UI jog clicks.
        for name,counts in captures().items():
            self.robot.jog_steps=counts
            await self.c.calibration_action({"action":"capture","corner":name})

    async def test_capture_finish_persist_speed_and_reboot_restore(self):
        await self.collect()
        await self.c.calibration_action({"action":"finish"})
        cal=self.c.calibration
        self.assertTrue(self.c.link.state["homed"])
        self.assertEqual(self.c.link.state["reference"],"user")
        job=self.c.import_artwork({"svg":"<svg><path d=\"M0 0L1 1\"/></svg>","options":{"quality":"fast","margin":20}})
        self.assertEqual(job["feed"],15)
        self.assertEqual(job["paper"],"Letter")
        self.c.validate_job(self.c.jobs[job["id"]])
        self.assertEqual(json.loads((Path(self.temp.name)/"paper_calibration.json").read_text())["id"],cal["id"])
        self.robot.reboot()
        for _ in range(50):
            if not self.c.link.connected:break
            await asyncio.sleep(.01)
        await self.c.connect()
        with self.assertRaises(ValueError):self.c.validate_job(self.c.jobs[job["id"]])
        with self.assertRaises(ValueError):await self.c.calibration_action({"action":"restore"})
        await self.c.calibration_action({"action":"restore","at_top_left":True})
        self.c.validate_job(self.c.jobs[job["id"]])
        self.assertAlmostEqual(self.c.link.state["x"],cal["corners"]["top_left"]["xy"][0],places=4)
        restored=Controller(Path(self.temp.name),self.config)
        self.assertEqual(restored.calibration["id"],cal["id"])
        await restored.close()

    async def test_bounded_jog_order_confirmation_and_duplicate(self):
        with self.assertRaises(ValueError):await self.c.calibration_action({"action":"begin","paper":"Letter","width":644.525})
        await self.begin()
        self.robot.suppress_next_ack=True
        await self.c.calibration_action({"action":"jog","axis":0,"mm":1})
        self.assertEqual(self.robot.jog_steps,[80,0])
        await self.c.calibration_action({"action":"jog","axis":1,"mm":-.25})
        self.assertEqual(self.robot.jog_steps,[80,-20])
        await self.c.calibration_action({"action":"jog","axis":0,"mm":50})
        self.assertEqual(self.robot.jog_steps,[4080,-20])
        await self.c.calibration_action({"action":"jog","axis":0,"mm":-50})
        self.assertEqual(self.robot.jog_steps,[80,-20])
        for action in ({"action":"jog","axis":0,"mm":50.01},{"action":"jog","axis":2,"mm":1},
                       {"action":"capture","corner":"top_right"},{"action":"finish"}):
            with self.assertRaises(ValueError):await self.c.calibration_action(action)
        async with self.c.operation_lock:
            with self.assertRaises(ValueError):await self.c.calibration_action({"action":"jog","axis":0,"mm":1})

    async def test_disconnect_aborts_draft_and_recalibration_invalidates_jobs(self):
        await self.begin()
        await self.c.link.close()
        await asyncio.sleep(.03)
        await self.c.connect()
        with self.assertRaises(ValueError):await self.c.calibration_action({"action":"capture","corner":"top_left"})
        await self.collect();await self.c.calibration_action({"action":"finish"})
        job=self.c.import_artwork({"svg":"<svg><path d=\"M0 0L1 1\"/></svg>","options":{"margin":20}})
        await self.collect();await self.c.calibration_action({"action":"finish"})
        with self.assertRaisesRegex(ValueError,"changed"):self.c.validate_job(self.c.jobs[job["id"]])
