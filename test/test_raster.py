import asyncio
import base64
from pathlib import Path
import tempfile
import unittest

from controller.artwork import prepare
from controller.raster import decode_gray, raster_paths, simplify, PRESETS, np as raster_np
from controller.server import Controller

OPTIONS = {"paper":"Letter", "left":100, "top":-100, "margin":20}


def image(w=32,h=24,value=0):
    pixels = bytes(value(x,y) if callable(value) else value for y in range(h) for x in range(w))
    return {"width":w,"height":h,"pixels":base64.b64encode(pixels).decode()}


class RasterTests(unittest.TestCase):
    def convert(self, data, **options):
        options = dict(OPTIONS, **options)
        paths,warnings,metadata,bounds = raster_paths(data,options)
        options.setdefault("feed",PRESETS[options.get("quality","balanced")]["feed"])
        return prepare(paths,options,source_bounds=bounds), metadata, warnings

    def test_quality_increases_density_and_time(self):
        jobs = [self.convert(image(value=100),quality=key)[0] for key in PRESETS]
        self.assertLess(jobs[0]["command_count"],jobs[1]["command_count"])
        self.assertLess(jobs[1]["command_count"],jobs[2]["command_count"])
        self.assertLess(jobs[0]["estimated_seconds"],jobs[1]["estimated_seconds"])
        self.assertLess(jobs[1]["estimated_seconds"],jobs[2]["estimated_seconds"])
        for job in jobs:
            self.assertTrue(all(120 <= x <= 295.9 and -359.4 <= y <= -120
                                for path in job["paths"] for x,y in path))
            self.assertEqual(job["commands"][-1],{"op":"sync"})

    def test_black_hatching_serpentine_and_white_rejection(self):
        paths,_,_,bounds = raster_paths(image(), OPTIONS)
        self.assertEqual(bounds,(0.,0.,32.,24.))
        self.assertLess(paths[0][0][0],paths[0][-1][0])
        self.assertGreater(paths[1][0][0],paths[1][-1][0])
        self.assertTrue(all(len(p)==2 for p in paths))
        for mode in ("hatching","outlines"):
            with self.assertRaisesRegex(ValueError,"No drawable"):
                raster_paths(image(value=255),dict(OPTIONS,image_mode=mode))

    def test_outline_frame_preserves_whitespace_and_holes(self):
        data = image(40,40,lambda x,y:0 if 10<=x<30 and 10<=y<30 and not (15<=x<25 and 15<=y<25) else 255)
        paths,_,_,_ = raster_paths(data,dict(OPTIONS,image_mode="outlines"))
        self.assertEqual(len(paths),2)
        self.assertTrue(all(p[0]==p[-1] for p in paths))
        job,metadata,warnings=self.convert(data,image_mode="outlines")
        # 20px artwork in a 40px image occupies half the printable image frame.
        self.assertAlmostEqual(job["bounds"][2]-job["bounds"][0],(215.9-40)/2,places=2)
        self.assertEqual(metadata["source_type"],"image")
        self.assertTrue(any("servo" in warning for warning in warnings))

    def test_threshold_and_simplification(self):
        data = image(value=150)
        with self.assertRaises(ValueError): self.convert(data,image_mode="outlines",threshold=128)
        job,_,_=self.convert(data,image_mode="outlines",threshold=200)
        self.assertEqual(len(job["paths"]),1)
        path=[(x,0) for x in range(5000)]
        self.assertEqual(simplify(path,.1),[path[0],path[-1]])

    def test_bad_inputs_are_bounded(self):
        good=image()
        for bad in (None,{},dict(good,width=True),dict(good,width=769),dict(good,height=0),
                    dict(good,pixels="%%%"),dict(good,pixels="AA=="),dict(good,pixels="A"*10000)):
            with self.subTest(bad=type(bad)),self.assertRaises(ValueError): decode_gray(bad)
        for options in ({"quality":"unknown"},{"quality":[]},{"image_mode":"unknown"},
                        {"image_mode":"outlines","threshold":float("nan")},{"margin":500},{"paper":[]}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                raster_paths(good,dict(OPTIONS,**options))

    def test_preset_bounds_actual_resolution(self):
        _,_,metadata,_=raster_paths(image(600,400),dict(OPTIONS,quality="fast"))
        self.assertEqual(max(metadata["image_size"]),256)


@unittest.skipIf(raster_np is None, "numpy not installed")
class WaveTests(unittest.TestCase):
    convert = RasterTests.convert

    def test_wave_is_continuous_and_budgeted(self):
        for key,cfg in PRESETS.items():
            paths,warnings,meta,bounds = raster_paths(image(value=0),dict(OPTIONS,image_mode="wave",quality=key))
            self.assertEqual(len(paths),1)                       # black image: one unbroken line
            self.assertLessEqual(sum(map(len,paths)),cfg["wave_points"]*1.1)
            self.assertEqual(meta["image_mode"],"wave")
            job,_,_ = self.convert(image(value=0),image_mode="wave",quality=key)
            self.assertLessEqual(job["command_count"],65536)

    def test_wave_swings_more_where_darker_and_skips_white(self):
        with self.assertRaises(ValueError): raster_paths(image(value=255),dict(OPTIONS,image_mode="wave"))
        w,h = 64,64
        pixels = bytes(30 if x < w//2 else 200 for y in range(h) for x in range(w))
        data = {"width":w,"height":h,"pixels":base64.b64encode(pixels).decode()}
        paths,_,_,_ = raster_paths(data,dict(OPTIONS,image_mode="wave"))
        dark = [abs(y-round(y)) for p in paths for x,y in p if x < w*.4]
        light = [abs(y-round(y)) for p in paths for x,y in p if x > w*.6]
        self.assertGreater(len(dark),0)
        self.assertGreater(len(dark),3*len(light))               # light half is mostly unmarked

    def test_wave_strokes_far_fewer_than_hatching(self):
        data = image(value=100)
        wave,_,_,_ = raster_paths(data,dict(OPTIONS,image_mode="wave",quality="balanced"))
        hatch,_,_,_ = raster_paths(data,dict(OPTIONS,image_mode="hatching",quality="balanced"))
        self.assertLess(len(wave)*5,len(hatch))


class RasterControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_manual_reference_no_longer_caps_speed(self):
        with tempfile.TemporaryDirectory() as temp:
            c=Controller(Path(temp))
            try:
                data={"image":image(),"options":dict(OPTIONS,quality="fast")}
                normal=c.build_artwork(data,{})
                legacy=c.build_artwork(data,{"reference":"manual"})
                self.assertEqual(legacy["feed"],normal["feed"])
                self.assertFalse(any("manual reference" in w for w in legacy["warnings"]))
            finally: await c.close()

    async def test_import_metadata_history_and_no_motion(self):
        with tempfile.TemporaryDirectory() as temp:
            c=Controller(Path(temp))
            try:
                job=await c.import_async({"image":image(),"name":"photo.png","options":dict(OPTIONS,quality="fast")})
                self.assertEqual(job["source_type"],"image")
                self.assertEqual(job["quality"],"fast")
                self.assertEqual(job["feed"],15)
                self.assertEqual(job["state"],"queued")
                self.assertIsNone(c.active)
                self.assertFalse(c.link.connected)
                restored=Controller(Path(temp))
                self.assertEqual(restored.jobs[job["id"]]["paths"],[[list(p) for p in path] for path in job["paths"]])
                await restored.close()
                async with c.preparation_lock:
                    with self.assertRaisesRegex(ValueError,"being prepared"):
                        await c.import_async({"image":image(),"options":OPTIONS})
            finally: await c.close()

    async def test_missing_or_malformed_options(self):
        with tempfile.TemporaryDirectory() as temp:
            c=Controller(Path(temp))
            try:
                for data in ([],{"image":image(),"options":[]},{"image":image(),"options":{}}):
                    with self.assertRaises(ValueError): await c.import_async(data)
            finally: await c.close()
