import asyncio
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest

from controller.config import RobotConfig, load_robot_config
from controller.server import Controller
from controller.simulator import SimulatedRobot


class ConfigTests(unittest.TestCase):
    def test_file_and_startup_environment_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/".env"
            path.write_text('# local settings\nDRAWY_ROBOT_HOST="drawy.local"\nDRAWY_ROBOT_PORT=9999\nDRAWY_ROBOT_PAIRING_KEY=private-test-key\n')
            config=load_robot_config(path,{"DRAWY_ROBOT_HOST":"192.0.2.10"})
            self.assertEqual(config.host,"192.0.2.10")
            self.assertEqual(config.port,9999)
            self.assertEqual(config.token,"private-test-key")
            self.assertNotIn(config.token,repr(config))
            with self.assertRaises(FrozenInstanceError): config.host="different.local"

    def test_missing_invalid_and_duplicate_config(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/".env"
            with self.assertRaises(ValueError):load_robot_config(path,{})
            base='DRAWY_ROBOT_HOST=drawy.local\nDRAWY_ROBOT_PAIRING_KEY=secret-test\n'
            for extra in ('DRAWY_ROBOT_PORT=0','DRAWY_ROBOT_PORT=65536','DRAWY_ROBOT_PORT=nope',
                          'DRAWY_ROBOT_HOST=other.local','UNKNOWN=value','shell command',
                          'DRAWY_ROBOT_PORT="9999'):
                path.write_text(base+extra+'\n')
                with self.subTest(extra=extra),self.assertRaises(ValueError):load_robot_config(path,{})
            path.write_text(base)
            with self.assertRaisesRegex(ValueError,"PAIRING_KEY"):
                load_robot_config(path,{"DRAWY_ROBOT_HOST":"drawy.local","DRAWY_ROBOT_PAIRING_KEY":""})


class FixedLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_credentials_not_loaded_or_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"connection.json"
            path.write_text(json.dumps({"session":"existing-session","host":"old.local","token":"old-secret","port":1}))
            c=Controller(Path(temp),RobotConfig("fixed.local",9999,"new-secret"))
            try:
                self.assertEqual(c.config,{"session":"existing-session"})
                self.assertEqual(json.loads(path.read_text()),c.config)
                self.assertEqual(c.robot.host,"fixed.local")
                self.assertNotIn("new-secret",json.dumps(c.snapshot()))
            finally:await c.close()

    async def test_auto_connect_and_reconnect_never_moves_or_resumes(self):
        with tempfile.TemporaryDirectory() as temp:
            robot=await SimulatedRobot().start()
            c=Controller(Path(temp),RobotConfig("127.0.0.1",robot.port,robot.token))
            task=asyncio.create_task(c.maintain_connection(.02))
            async def wait(predicate):
                end=asyncio.get_running_loop().time()+3
                while not predicate():
                    if asyncio.get_running_loop().time()>end:raise TimeoutError()
                    await asyncio.sleep(.01)
            try:
                await wait(lambda:c.link.connected)
                self.assertFalse(robot.executions)
                await c.link.control("pause")
                await wait(lambda:c.link.state.get("paused"))
                await c.link.close()
                await wait(lambda:c.link.connected)
                self.assertFalse(robot.executions)
                self.assertTrue(c.link.state["paused"])
                self.assertFalse(c.link.state["homed"])
                self.assertEqual(json.loads((Path(temp)/"connection.json").read_text()),c.config)
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
                await c.close();await robot.close()
