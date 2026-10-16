import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from controller.color import PENS, prepare_color, separate, decode_rgb
from controller.plot_segments import execution_parts
from controller.server import Controller, save_json
from controller.transport import DeviceError
import test_stored_plot as stored_tests

OPTIONS=dict(paper='Letter',left=200,top=-170,margin=25.4,feed=10,
             color_mode='rgbk',color_dither=False,quality='fast',image_mode='hatching')


def color_image():
    # Four exact palette swatches with a white border, preserving a shared frame.
    w,h=24,12
    pixels=bytes(v for y in range(h) for x in range(w)
                 for v in ((255,255,255) if x in (0,w-1) or y in (0,h-1) else PENS[min(3,x//6)][3]))
    return dict(width=w,height=h,channels=3,pixels=base64.b64encode(pixels).decode())


class ColorConversionTests(unittest.TestCase):
    def test_four_stages_share_frame_and_safe_endings(self):
        job=prepare_color(color_image(),OPTIONS,90,40)
        self.assertEqual([s['pen'] for s in job['color_stages']],['red','green','blue','black'])
        parts,owners=execution_parts(job,256)
        self.assertEqual(sorted(set(owners)),[0,1,2,3])
        self.assertGreater(len(parts),4)
        for stage in job['color_stages']:
            commands=job['commands'][stage['command_start']:stage['command_end']]
            self.assertEqual(commands[-2]['role'],'up')
            self.assertEqual(commands[-1]['op'],'sync')
            xs=[x for path in job['paths'][stage['path_start']:stage['path_end']] for x,y in path]
            self.assertTrue(xs)
        # Swatches remain left-to-right rather than being scaled individually.
        extents=[min(x for path in job['paths'][s['path_start']:s['path_end']] for x,y in path) for s in job['color_stages']]
        self.assertEqual(extents,sorted(extents))

    def test_white_skipped_black_not_rgb_channels(self):
        white=bytes([255]*12)
        self.assertEqual(set(separate(2,2,white,True)),{4})
        self.assertTrue(set(separate(8,8,bytes([128])*8*8*3,True)) <= {3,4})
        rgb=bytes(PENS[3][3])*4
        self.assertEqual(set(separate(2,2,rgb,True)),{3})
        with self.assertRaisesRegex(ValueError,'blank|pale'):
            prepare_color(dict(width=2,height=2,channels=3,pixels=base64.b64encode(white).decode()),OPTIONS,90,40)

    def test_payload_and_resolution_bounds(self):
        for image in ({},dict(width=2,height=2,channels=3,pixels='AAAA'),dict(width=1000,height=2,channels=3,pixels='')):
            with self.assertRaises(ValueError):decode_rgb(image,OPTIONS)
        image=dict(width=300,height=2,channels=3,pixels=base64.b64encode(bytes([255])*1800).decode())
        w,h,p=decode_rgb(image,OPTIONS)
        self.assertEqual(w,256);self.assertEqual(len(p),w*h*3)


class ColorExecutionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=stored_tests.StoredPlotTests.asyncSetUp
    asyncTearDown=stored_tests.StoredPlotTests.asyncTearDown

    async def wait_for(self,predicate,timeout=10):
        async with asyncio.timeout(timeout):
            while not predicate():
                self.c.snapshot()
                await asyncio.sleep(.01)

    async def begin_color(self):
        self.robot.delay=.0001
        job=self.c.import_artwork(dict(image=color_image(),options=OPTIONS,name='Swatches'))
        await self.c.start(job['id'],True)
        return self.c.jobs[job['id']]

    async def confirm(self,job):
        return await self.c.confirm_pen_change(dict(id=job['id'],run=job['plot_run'],stage=job['pending_stage'],confirmed=True))

    async def test_no_motion_before_each_pen_confirmation(self):
        job=await self.begin_color()
        self.assertEqual(job['state'],'awaiting_pen')
        self.assertEqual(len(self.robot.plot_starts),0)
        for index,stage in enumerate(job['color_stages']):
            self.assertEqual(job['pending_stage'],index)
            before=len(self.robot.plot_starts)
            await asyncio.sleep(.03)
            self.assertEqual(len(self.robot.plot_starts),before)
            await self.confirm(job)
            await self.wait_for(lambda:job['state'] in ('awaiting_pen','completed','error'))
            self.assertNotEqual(job['state'],'error',job['message'])
            self.assertEqual(self.robot.pen,self.robot.pen_up)
        self.assertEqual(job['state'],'completed')
        self.assertIsNone(self.c.active)
        self.assertEqual(len(self.robot.plot_starts),4)

    async def test_restart_retains_unconfirmed_stage(self):
        job=await self.begin_color()
        await self.confirm(job)
        await self.wait_for(lambda:job['state']=='awaiting_pen')
        self.assertEqual(job['pending_stage'],1)
        data=self.c.data_dir;config=self.c.robot
        save_json(data/'paper_calibration.json',self.c.calibration)
        await self.c.close()
        self.c=Controller(data,config)
        await self.c.connect();await asyncio.sleep(.1)
        retained=self.c.jobs[job['id']]
        self.assertEqual(retained['state'],'awaiting_pen')
        self.assertEqual(retained['pending_stage'],1)
        self.assertEqual(len(self.robot.plot_starts),1)
        self.assertEqual(self.c.active,job['id'])
        await self.confirm(retained)
        await self.wait_for(lambda:retained['state']=='awaiting_pen')
        self.assertEqual(retained['pending_stage'],2)

    async def test_stale_missing_confirmation_and_reboot_rejected(self):
        job=await self.begin_color()
        for values in (dict(confirmed=False),dict(stage=1),dict(run='old-run')):
            request=dict(id=job['id'],run=job['plot_run'],stage=0,confirmed=True,**{})
            request.update(values)
            with self.assertRaises(ValueError):await self.c.confirm_pen_change(request)
        self.assertEqual(len(self.robot.plot_starts),0)
        self.robot.reboot();await self.c.connect()
        self.assertEqual(job['state'],'interrupted')
        with self.assertRaises(ValueError):await self.confirm(job)

    async def test_color_requires_updated_firmware(self):
        job=self.c.import_artwork(dict(image=color_image(),options=OPTIONS))
        self.c.link.state['stored_plot_api']=1
        with self.assertRaisesRegex(ValueError,'firmware'):
            await self.c.start(job['id'],True)
        self.assertIsNone(self.c.active)

    async def test_color_multipart_does_not_ask_for_pen_between_same_color_parts(self):
        self.robot.plot_capacity=256;self.c.link.state['plot_capacity']=256
        job=await self.begin_color()
        await self.confirm(job)
        await self.wait_for(lambda:job['state']=='awaiting_pen')
        self.assertEqual(job['pending_stage'],1)
        self.assertGreater(len(self.robot.plot_starts),1)
        self.assertEqual(self.robot.plot_state,'waiting')
