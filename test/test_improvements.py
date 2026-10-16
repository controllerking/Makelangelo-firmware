import asyncio
import math
import tempfile
import unittest
from pathlib import Path
from controller.artwork import prepare, PAPER
from controller.toolpath import route, ramp_seconds
from controller.plot_segments import split_commands
from controller.plot import encode_plot, RECORD
from controller.accuracy import diagnostic_paths, measurement_report
import test_stored_plot as stored_tests

OPTS=dict(paper='Letter',left=100,top=-100,margin=20,feed=10)

class ToolpathTests(unittest.TestCase):
    def test_no_redundant_pen_commands_and_separate_travel_speed(self):
        j=prepare([[(0,0),(1,0)],[(1,1),(0,1)]],dict(OPTS,travel_feed=20))
        for a,b in zip(j['commands'],j['commands'][1:]):
            self.assertFalse(a['op']==b['op']=='pen' and a['role']==b['role'])
        self.assertEqual([c['feed'] for c in j['commands'] if c['op']=='move'],[20,10,20,10])
        self.assertAlmostEqual(j['pen_seconds'],4*(ramp_seconds(50,35,100)+.3),places=2)

    def test_endpoint_preserved_below_old_filter(self):
        j=prepare([[(0,0),(100,0),(100.005,0)]],dict(OPTS,path_tolerance=0))
        self.assertEqual(len(j['paths'][0]),3)
        self.assertEqual(j['commands'][-3]['x'],j['paths'][0][-1][0])

    def test_route_never_worse_or_adds_ink(self):
        paths=[[(0,0),(1,0)],[(90,0),(91,0)],[(3,0),(2,0)]]
        result=route(paths,True)
        cost=lambda ps:sum(math.dist(a[-1],b[0]) for a,b in zip(ps,ps[1:]))
        self.assertLess(cost(result),cost(paths))
        self.assertEqual(sorted(sorted(p) for p in result),sorted(sorted(p) for p in paths))

    def test_split_preserves_all_drawn_segments_including_long_path(self):
        commands=[dict(op='pen',role='up'),dict(op='move',x=0,y=-100,feed=10),dict(op='pen',role='down')]
        commands.extend(dict(op='move',x=i,y=-100-i%2,feed=10) for i in range(1,80))
        commands.extend([dict(op='pen',role='up'),dict(op='sync')])
        def ink(cmds):
            pen='up';previous=None;segments=[]
            for c in cmds:
                if c['op']=='pen':pen=c['role']
                elif c['op']=='move':
                    xy=(c['x'],c['y'])
                    if pen=='down' and previous is not None:segments.append((previous,xy))
                    previous=xy
            return segments
        parts=split_commands(commands,256)
        self.assertGreater(len(parts),1)
        self.assertEqual([s for part in parts for s in ink(part)],ink(commands))
        for part in parts:
            payload,_=encode_plot({'commands':part})
            self.assertLessEqual(len(payload),256)
            self.assertEqual(part[-1]['op'],'sync')
            self.assertEqual([c for c in part if c['op']=='pen'][-1]['role'],'up')

    def test_accuracy_grid_and_report(self):
        paths,bounds=diagnostic_paths(OPTS)
        self.assertEqual(bounds,(0,0,PAPER['Letter'][0]-40,PAPER['Letter'][1]-40))
        self.assertAlmostEqual(max(x for x,y in paths[-1])-min(x for x,y in paths[-1]),50)
        report=measurement_report([{'expected':[0,0],'measured':[.3,.4]}]*3)
        self.assertAlmostEqual(report['rms_mm'],.5)

class MultipartTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=stored_tests.StoredPlotTests.asyncSetUp
    asyncTearDown=stored_tests.StoredPlotTests.asyncTearDown
    job=stored_tests.StoredPlotTests.job
    # Inherit the real socket setup; small advertised flash forces multiple parts.
    async def wait_for(self, predicate, timeout=8):
        async with asyncio.timeout(timeout):
            while not predicate():
                self.c.snapshot()
                await asyncio.sleep(.01)

    async def begin_parts(self):
        self.robot.plot_capacity=256
        self.c.link.state['plot_capacity']=256
        j=self.job()
        await self.c.start(j['id'],True)
        await self.wait_for(lambda:self.robot.plot_running)
        self.assertEqual(self.c.jobs[j['id']]['execution'],'segmented')
        return j

    async def test_parts_wait_offline_then_continue_without_replay(self):
        j=await self.begin_parts()
        await self.c.link.close()
        await self.wait_for(lambda:self.robot.plot_state=='waiting')
        first=(self.robot.x,self.robot.y,self.robot.plot_completed)
        await asyncio.sleep(.1)
        self.assertEqual(first,(self.robot.x,self.robot.y,self.robot.plot_completed))
        self.assertEqual(self.robot.pen,self.robot.pen_up)
        await self.c.connect()
        await self.wait_for(lambda:self.c.active is None)
        self.assertEqual(self.c.jobs[j['id']]['state'],'completed')
        self.assertEqual(self.c.jobs[j['id']]['completed'],j['command_count'])

    async def test_controller_restart_adopts_same_boot_part(self):
        j=await self.begin_parts()
        data=self.c.data_dir;robot_config=self.c.robot
        from controller.server import save_json
        save_json(data/'paper_calibration.json',self.c.calibration)
        await self.c.close()
        await self.wait_for(lambda:self.robot.plot_state=='waiting')
        from controller.server import Controller
        self.c=Controller(data,robot_config)
        await self.c.connect()
        await self.wait_for(lambda:self.c.active is None)
        self.assertEqual(self.c.jobs[j['id']]['state'],'completed')

    async def test_multipart_reboot_does_not_continue(self):
        j=await self.begin_parts()
        self.robot.reboot()
        await self.c.connect()
        await asyncio.sleep(.05)
        self.assertIsNone(self.c.active)
        self.assertEqual(self.c.jobs[j['id']]['state'],'interrupted')
        self.assertFalse(self.robot.plot_running)

    async def test_pause_between_parts_prevents_continuation(self):
        j=await self.begin_parts()
        await self.c.pause()
        await asyncio.sleep(.05)
        done=self.robot.plot_completed
        await asyncio.sleep(.1)
        self.assertEqual(done,self.robot.plot_completed)
        await self.c.resume()
        await self.wait_for(lambda:self.c.active is None)
        self.assertEqual(self.c.jobs[j['id']]['state'],'completed')

    async def test_waiting_part_rejects_wrong_chain_and_stop_blocks_next(self):
        import uuid
        from controller.transport import DeviceError
        j=await self.begin_parts()
        await self.c.link.close()
        await self.wait_for(lambda:self.robot.plot_state=='waiting')
        self.c.worker.cancel()
        await asyncio.gather(self.c.worker,return_exceptions=True)
        self.c.jobs[j['id']]['state']='paused'
        await self.c.connect()
        meta=dict(job=str(uuid.uuid4()),parent=str(uuid.uuid4()),chain=str(uuid.uuid4()),part=1,final=True,
                  cal=self.robot.calibration_id,count=2,crc=0,up=90,down=40,spu0=80,spu1=80,confirm=True)
        with self.assertRaisesRegex(DeviceError,'continuation'):
            await self.c.link.control('plot_begin',**meta)
        await self.c.stop()
        self.assertEqual(self.robot.plot_state,'stopped')
        self.assertFalse(self.robot.plot_running)
        with self.assertRaisesRegex(DeviceError,'fault'):
            await self.c.link.control('plot_begin',**meta)

    async def test_disconnect_after_start_reconciles_without_replaying_part(self):
        j=await self.begin_parts()
        part=self.robot.plot_saved['part']
        run=self.robot.plot_run
        await self.c.link.close()
        await self.c.connect()
        self.assertEqual(self.robot.plot_run,run)
        await self.wait_for(lambda:self.c.active is None)
        self.assertEqual(self.c.jobs[j['id']]['state'],'completed')

    async def test_lost_upload_and_start_ack_do_not_repeat_drawing(self):
        for operation in ('plot_chunk','plot_commit','plot_start'):
            with self.subTest(operation=operation):
                self.robot.plot_capacity=256
                self.c.link.state['plot_capacity']=256
                self.robot.drop_plot_ack=operation
                starts=len(self.robot.plot_starts)
                j=self.job()
                await self.c.start(j['id'],True)
                await self.wait_for(lambda:not self.c.link.connected)
                await self.c.connect()
                await self.wait_for(lambda:self.c.active is None)
                self.assertEqual(self.c.jobs[j['id']]['state'],'completed',self.c.jobs[j['id']]['message'])
                trace=self.robot.plot_starts[starts:]
                self.assertEqual(len(trace),self.c.jobs[j['id']]['transfer_parts'])
                self.assertEqual(len(trace),len(set(trace)))
