import asyncio
import base64
import time
import unittest
import uuid
import zlib
from controller.plot import RECORD
import test_stored_plot as stored_tests

class StorageCleanupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=stored_tests.StoredPlotTests.asyncSetUp
    asyncTearDown=stored_tests.StoredPlotTests.asyncTearDown
    job=stored_tests.StoredPlotTests.job

    async def wait_for(self,predicate):
        async with asyncio.timeout(4):
            while not predicate():
                self.c.snapshot();await asyncio.sleep(.01)

    async def upload(self,commit=True):
        payload=RECORD.pack(1,0,0,0)+RECORD.pack(3,0,0,0)
        job=str(uuid.uuid4())
        await self.c.link.control('plot_begin',job=job,cal=self.robot.calibration_id,count=2,crc=zlib.crc32(payload),
                                  up=90,down=40,spu0=80,spu1=80,confirm=True)
        await self.c.link.control('plot_chunk',offset=0,data=base64.b64encode(payload).decode())
        if commit:await self.c.link.control('plot_commit')
        return job

    async def test_completed_jobs_reclaim_bytes_and_keep_receipt(self):
        for _ in range(3):
            j=self.job();await self.c.start(j['id'],True)
            await self.wait_for(lambda:self.robot.plot_state=='completed')
            self.assertEqual(self.robot.state()['plot_free'],1408*1024)
            self.assertNotIn('data',self.robot.plot_saved)
            self.assertEqual(self.robot.plot_saved['job'],j['id'])
            starts=len(self.robot.plot_starts)
            await self.c.link.control('plot_start',job=j['id'],run=self.c.jobs[j['id']]['plot_run'],confirm=True)
            self.assertEqual(len(self.robot.plot_starts),starts)
            self.c.snapshot()
            self.assertEqual(self.c.jobs[j['id']]['state'],'completed')

    async def test_stop_reclaims_ready_upload(self):
        await self.upload()
        self.assertLess(self.robot.state()['plot_free'],1408*1024)
        await self.c.link.control('stop')
        self.assertEqual(self.robot.state()['plot_free'],1408*1024)
        self.assertTrue(self.robot.fault)

    async def test_abandoned_upload_expires_and_restarts_at_zero(self):
        self.robot.plot_upload_idle=.05
        await self.upload(commit=False)
        self.assertEqual(len(self.robot.plot_data),32)
        await self.wait_for(lambda:self.robot.plot_meta is None)
        self.assertEqual(self.robot.state()['plot_free'],1408*1024)
        await self.upload()
        self.assertEqual(self.robot.plot_state,'ready')

    async def test_unstarted_file_expires_without_motion(self):
        self.robot.plot_ready_idle=.05
        await self.upload()
        await self.wait_for(lambda:self.robot.plot_state=='expired')
        self.assertEqual(self.robot.state()['plot_free'],1408*1024)
        self.assertEqual(len(self.robot.plot_starts),0)
