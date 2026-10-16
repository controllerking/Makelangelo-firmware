import asyncio
from pathlib import Path
import tempfile
import unittest
from controller.config import RobotConfig
from controller.server import Controller
from controller.simulator import SimulatedRobot

class LiveSpeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.robot=await SimulatedRobot(delay=.5).start()
        self.c=Controller(Path(self.temp.name),RobotConfig("127.0.0.1",self.robot.port,self.robot.token))
        await self.c.connect()

    async def asyncTearDown(self):
        await self.c.close();await self.robot.close();self.temp.cleanup()

    async def test_before_during_move_and_paused_no_command_ids_consumed(self):
        await self.c.set_speeds({"stepper_percent":50,"servo_speed":20})
        self.assertEqual(self.robot.next,1)
        self.robot.homed=True
        reply=await self.c.link.command({"op":"move","x":410,"y":-210,"feed":10})
        for _ in range(30):
            if self.robot.active_command:break
            await asyncio.sleep(.005)
        active=self.robot.active_command
        self.c.active="in-progress" # Speed endpoint must not reject an active draw.
        await self.c.set_speeds({"stepper_percent":25,"servo_speed":60})
        self.assertIs(self.robot.active_command,active)
        self.assertEqual(self.robot.next,reply["id"]+1)
        self.assertEqual((self.robot.stepper_percent,self.robot.servo_speed),(25,60))
        self.c.active=None
        await self.c.link.control("pause")
        await self.c.set_speeds({"stepper_percent":100,"servo_speed":5})
        self.assertTrue(self.robot.hold)

    async def test_invalid_bounds_fault_and_reboot_defaults(self):
        for percent,speed in ((9,35),(101,35),(True,35),(50,4),(50,121),(50,float("nan"))):
            with self.assertRaises(ValueError):await self.c.set_speeds({"stepper_percent":percent,"servo_speed":speed})
        self.assertEqual(self.robot.next,1)
        await self.c.set_speeds({"stepper_percent":10,"servo_speed":120})
        self.robot.reboot()
        await self.c.connect()
        self.assertEqual((self.c.link.state["stepper_percent"],self.c.link.state["servo_speed"]),(100,35))
        await self.c.link.control("stop")
        with self.assertRaises(ValueError):await self.c.set_speeds({"stepper_percent":50,"servo_speed":35})
