"""Bounded grayscale-to-pen conversion; decoding happens in the local browser.

No cloud calls, image-codec dependency or original file persistence. Coordinates
retain the full image frame, including whitespace, until paper placement.
"""
from __future__ import annotations
import base64
import binascii
import math

try: import numpy as np  # optional: only the wavy-line style needs it
except ImportError: np = None

from .artwork import MAX_POINTS, PAPER, finite, distance_line

PRESETS = {
    "fast": {"label": "Fast", "resolution": 256, "spacing": 1.8, "strokes": 3000,
             "sample": 1.2, "tolerance": .4, "feed": 15, "wave_points": 15000, "hatch_pitch": 3., "hatch_strokes": 800,
             "description": "Fewer lines, bolder shapes, shorter plots."},
    "balanced": {"label": "Balanced", "resolution": 512, "spacing": 1., "strokes": 7000,
                 "sample": .75, "tolerance": .2, "feed": 10, "wave_points": 35000, "hatch_pitch": 2., "hatch_strokes": 2000,
                 "description": "A practical balance of detail and drawing time."},
    "detailed": {"label": "Detailed", "resolution": 768, "spacing": .5, "strokes": 14000,
                 "sample": .45, "tolerance": .1, "feed": 6, "wave_points": 55000, "hatch_pitch": 1.4, "hatch_strokes": 4000,
                 "description": "Denser shading and finer outlines; longer plots."},
    "ultra": {"label": "Ultra", "resolution": 2048, "spacing": .3, "strokes": 400000,
              "sample": .3, "tolerance": .04, "feed": 6, "wave_points": 800000, "hatch_pitch": .6, "hatch_strokes": 120000,
              "wave_min_pitch": .5, "sketch_shapes": 400, "sketch_min_mm": .6,
              "description": "As fine as the pen allows; plots can run many hours and upload in parts."},
}
MAX_DIMENSION = 4096
BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def preset(options):
    key = options.get("quality", "balanced")
    if not isinstance(key, str) or key not in PRESETS:
        raise ValueError("Unknown quality preset")
    return key, PRESETS[key]


def decode_gray(image):
    if not isinstance(image, dict): raise ValueError("Invalid image data")
    w, h = image.get("width"), image.get("height")
    if type(w) is not int or type(h) is not int or not 2 <= w <= MAX_DIMENSION or not 2 <= h <= MAX_DIMENSION:
        raise ValueError("Image dimensions must be 2–%d pixels after resizing" % MAX_DIMENSION)
    encoded = image.get("pixels")
    if not isinstance(encoded, str) or len(encoded) > 4*((w*h+2)//3):
        raise ValueError("Invalid grayscale image size")
    try: pixels = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error): raise ValueError("Invalid image encoding") from None
    if len(pixels) != w*h: raise ValueError("Grayscale pixel count does not match dimensions")
    return w, h, pixels


def box_blur(a, k):
    """Separable box blur with edge padding (numpy cumulative sums)."""
    if k <= 1: return a
    pad = k//2
    for axis in (0, 1):
        n = a.shape[axis]
        spec = [(pad, k-1-pad) if i == axis else (0, 0) for i in range(2)]
        c = np.cumsum(np.pad(a, spec, mode="edge"), axis=axis)
        c = np.concatenate([np.zeros_like(np.take(c, [0], axis=axis)), c], axis=axis)
        a = (np.take(c, range(k, k+n), axis=axis) - np.take(c, range(0, n), axis=axis))/k
    return a


def tone(w, h, pixels):
    """Darkness 0..1 with the picture's own tonal range stretched to fill it."""
    dark = 1.-np.frombuffer(pixels, np.uint8).reshape(h, w).astype(np.float64)/255.
    lo, hi = np.percentile(dark, (2, 98))
    return np.clip((dark-lo)/(hi-lo), 0., 1.) if hi-lo > .05 else dark


HATCH_ANGLES = (math.radians(45), math.radians(135), 0., math.pi/2)
HATCH_LEVELS = (.12, .32, .52, .72)   # darkness at which each layer switches on


def hatch_layers(dark, w, h, scale, pitch, bridge_mm=0):
    """Straight lines in up to four directions; darker tone gets more layers.

    A run is only two points. Short gaps are drawn through and neighbouring line
    ends are joined, so the pen lifts far less than with per-cell dashes.
    """
    pitch_px = pitch/scale
    step = max(1., pitch_px/2)
    gap = int(bridge_mm/scale/step)
    paths = []
    for layer, (theta, level) in enumerate(zip(HATCH_ANGLES, HATCH_LEVELS)):
        if dark.max() <= level: continue
        ux, uy, vx, vy = math.cos(theta), math.sin(theta), -math.sin(theta), math.cos(theta)
        offsets = [cx*vx+cy*vy for cx, cy in ((0, 0), (w, 0), (w, h), (0, h))]
        s = min(offsets)+(layer%2)*pitch_px/2
        line = 0
        while s <= max(offsets):
            t0, t1 = -1e18, 1e18
            for origin, direction, hi in ((s*vx, ux, w), (s*vy, uy, h)):
                if abs(direction) < 1e-12:
                    if not 0 <= origin <= hi: t0, t1 = 1., 0.
                else:
                    a, b = sorted(((0-origin)/direction, (hi-origin)/direction))
                    t0, t1 = max(t0, a), min(t1, b)
            if t1-t0 >= step:
                ts = np.linspace(t0, t1, int((t1-t0)/step)+1)
                xs, ys = s*vx+ts*ux, s*vy+ts*uy
                inked = dark[np.clip(ys.astype(int), 0, h-1), np.clip(xs.astype(int), 0, w-1)] > level
                if line%2: xs, ys, inked = xs[::-1], ys[::-1], inked[::-1]
                edges = np.diff(np.concatenate([[0], inked.astype(np.int8), [0]]))
                runs = []
                for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)-1):
                    if runs and a-runs[-1][1] <= gap: runs[-1][1] = b
                    else: runs.append([a, b])
                for a, b in runs:
                    if b-a < 1 or math.dist((xs[a], ys[a]), (xs[b], ys[b])) < pitch_px: continue
                    seg = [(float(xs[a]), float(ys[a])), (float(xs[b]), float(ys[b]))]
                    connect = False
                    if paths and paths[-1][1] == layer and math.dist(paths[-1][0][-1], seg[0]) <= 1.6*pitch_px:
                        start = paths[-1][0][-1]
                        n = max(2, math.ceil(math.dist(start,seg[0])/.5))
                        cx = np.linspace(start[0],seg[0][0],n)
                        cy = np.linspace(start[1],seg[0][1],n)
                        connect = bool(np.all(dark[np.clip(cy.astype(int),0,h-1),np.clip(cx.astype(int),0,w-1)] > level))
                    if connect:
                        paths[-1][0].extend(seg)
                    else: paths.append([seg, layer])
            s += pitch_px
            line += 1
    return [p for p, _ in paths]


def hatch_paths(w, h, pixels, scale, config, bridge_mm=0):
    if np is None:
        raise ValueError("Crosshatch style needs numpy on the controller (apt install python3-numpy)")
    pitch = config["hatch_pitch"]
    for _ in range(8):
        dark = box_blur(tone(w, h, pixels), max(1, round(pitch/scale/2)))
        paths = hatch_layers(dark, w, h, scale, pitch, bridge_mm)
        if len(paths) <= config["hatch_strokes"]: return paths
        pitch *= 1.3   # too many pen lifts: widen the line spacing and retry
    raise ValueError("Crosshatch needs too many pen lifts; choose Fast or smaller paper")


def wave_paths(w, h, pixels, scale, config):
    """Continuous rows whose swing grows with darkness: few pen lifts, smooth motion.

    Row pitch is chosen from the paper size so the whole plot fits the preset's
    point budget (the robot stores about 65k commands per job). Rows are chained
    boustrophedon-style; the pen only lifts across near-white areas.
    """
    if np is None:
        raise ValueError("Wavy line style needs numpy on the controller (apt install python3-numpy)")
    per_period = 8
    dark = tone(w, h, pixels)
    width_mm, height_mm = w*scale, h*scale
    pitch = max(config.get("wave_min_pitch",1.5), config.get("pen_pitch",0), math.sqrt(width_mm*height_mm*per_period/config["wave_points"]))
    rows = max(2, int(height_mm/pitch))
    pitch = height_mm/rows
    dark = box_blur(dark, max(1, round(pitch/scale)))
    step = pitch/per_period                      # mm between samples along a row
    count = max(2, math.ceil(width_mm/step)+1)
    xs = np.linspace(0., float(w), count)
    cols = np.clip(xs.astype(int), 0, w-1)
    swing = .6*pitch/scale                       # peak amplitude in image pixels
    paths, current, chained = [], [], False
    def flush():
        nonlocal current
        if len(current) >= 3: paths.append(current)
        current = []
    for r in range(rows):
        y0 = (r+.5)*h/rows
        d = dark[min(h-1, int(y0)), cols]
        phase = np.concatenate([[0.], np.cumsum(2*math.pi*(1.+.6*d[1:])/per_period)])
        ys = np.clip(y0+swing*d*np.sin(phase), 0., float(h))
        px, py, inked = xs, ys, d >= .03
        if r%2: px, py, inked = px[::-1], py[::-1], inked[::-1]
        index = 0
        while index < count:
            if not inked[index]:
                index += 1
                continue
            end = index
            while end < count and inked[end]: end += 1
            run = list(zip(px[index:end].tolist(), py[index:end].tolist()))
            if index == 0 and chained: current.extend(run)   # continue from previous row end
            else:
                flush(); current = run
            if end < count: flush()
            chained = end == count
            index = end
        else:
            if not (inked[-1] if count else False): chained = False
    flush()
    return paths


SKETCH_LEVELS = (.18, .42, .66)   # darkness at which a nested, darker shape begins
SKETCH_MAX_SHAPES = 60   # default; a preset may raise it with "sketch_shapes"


def _components(mask, w, h):
    """4-connected components of a boolean mask as flat index arrays, largest first."""
    flat = mask.ravel()
    seen = np.zeros(flat.size, bool)
    found = []
    for start in np.flatnonzero(flat):
        if seen[start]: continue
        seen[start] = True
        stack, members = [start], []
        while stack:
            i = stack.pop()
            members.append(i)
            x, y = i%w, i//w
            for ok, j in ((x > 0, i-1), (x < w-1, i+1), (y > 0, i-w), (y < h-1, i+w)):
                if ok and flat[j] and not seen[j]:
                    seen[j] = True
                    stack.append(j)
        found.append(np.array(members))
    return sorted(found, key=len, reverse=True)


def sketch_paths(w, h, pixels, scale, config, bridge_mm=0):
    """Draw like a person: block in each shape's outline, then shade it, shape by shape.

    Shapes are connected areas at three nested darkness levels. Larger, lighter
    shapes are drawn first and the darker shapes inside them follow, so a partly
    finished plot already reads as the picture. Each shape owns the pixels not
    claimed by a kept darker shape, so no area is hatched twice.
    """
    if np is None:
        raise ValueError("Human sketch style needs numpy on the controller (apt install python3-numpy)")
    dark = tone(w, h, pixels)
    soft = box_blur(dark, max(1, round(1./scale)))
    min_area = max(4., (config.get("sketch_min_mm",1.5)/scale)**2)
    shapes = []                                   # (level, member indices)
    for level, cut in enumerate(SKETCH_LEVELS):
        comps = [c for c in _components(soft > cut, w, h) if len(c) >= min_area]
        shapes.extend((level, c) for c in comps)
    shapes = sorted(shapes, key=lambda s: len(s[1]), reverse=True)[:config.get("sketch_shapes",SKETCH_MAX_SHAPES)]
    if not shapes: return []
    owner = np.full(w*h, -1, np.int32)
    for number in sorted(range(len(shapes)), key=lambda n: (-shapes[n][0], len(shapes[n][1]))):
        members = shapes[number][1]
        owner[members[owner[members] < 0]] = number
    pitch = config["hatch_pitch"]
    tolerance = config["tolerance"]/scale
    order = sorted(range(len(shapes)), key=lambda n: (shapes[n][0], -len(shapes[n][1])))
    for _ in range(8):
        paths = []
        for number in order:
            members = shapes[number][1]
            xs, ys = members%w, members//w
            x0, x1, y0, y1 = xs.min(), xs.max()+1, ys.min(), ys.max()+1
            region = np.zeros((y1-y0, x1-x0), bool)
            region[ys-y0, xs-x0] = True
            mask = region.astype(np.uint8)
            outline = outlines(x1-x0, y1-y0, bytes((1-mask).ravel()*255), 128, tolerance)
            for path in outline:
                paths.append([(x+x0, y+y0) for x, y in path])
            mine = (owner.reshape(h, w)[y0:y1, x0:x1] == number)
            local = np.where(mine, soft[y0:y1, x0:x1], 0.)
            for path in hatch_layers(local, x1-x0, y1-y0, scale, pitch, bridge_mm):
                paths.append([(x+x0, y+y0) for x, y in path])
        if len(paths) <= config["hatch_strokes"]: return paths
        pitch *= 1.3
    raise ValueError("Human sketch needs too many pen lifts; choose Fast or smaller paper")


def simplify(path, tolerance):
    """Iterative RDP: no recursion overflow on long traced contours."""
    if len(path) < 3: return path
    keep = {0, len(path)-1}
    stack = [(0, len(path)-1)]
    work = 0
    while stack:
        start, end = stack.pop()
        if end-start < 2: continue
        work += end-start-1
        if work > 40_000_000: raise ValueError("Outline too complex; choose Fast or a simpler image")
        distance, index = max((distance_line(path[i], path[start], path[end]), i)
                              for i in range(start+1, end))
        if distance > tolerance:
            keep.add(index)
            stack.extend(((start,index), (index,end)))
    return [path[i] for i in sorted(keep)]


def outlines(w, h, pixels, threshold, tolerance):
    """Trace oriented cell boundaries, keeping holes and disconnected shapes."""
    edges = {}
    count = 0
    def dark(x,y): return 0 <= x < w and 0 <= y < h and pixels[y*w+x] < threshold
    def edge(a,b):
        nonlocal count
        count += 1
        if count > MAX_POINTS: raise ValueError("Image has too many outline edges; use Fast or a simpler image")
        edges.setdefault(a, []).append(b)
    for y in range(h):
        for x in range(w):
            if not dark(x,y): continue
            if not dark(x,y-1): edge((x,y),(x+1,y))
            if not dark(x+1,y): edge((x+1,y),(x+1,y+1))
            if not dark(x,y+1): edge((x+1,y+1),(x,y+1))
            if not dark(x-1,y): edge((x,y+1),(x,y))
    paths = []
    while edges:
        start = next(iter(edges))
        path, current = [start], start
        while current in edges:
            following = edges[current].pop()
            if not edges[current]: del edges[current]
            path.append(following); current = following
            if current == start: break
        clean = simplify(path, tolerance)
        if len(clean) >= 3: paths.append(clean)
    return paths


def raster_paths(image, options):
    key, config = preset(options)
    w, h, pixels = decode_gray(image)
    # API clients cannot defeat the preset's work bound with larger payloads.
    factor = min(1., config["resolution"]/max(w,h))
    nw, nh = max(2, round(w*factor)), max(2, round(h*factor))
    if (nw,nh) != (w,h):
        pixels = bytes(pixels[min(h-1,int(y*h/nh))*w+min(w-1,int(x*w/nw))]
                       for y in range(nh) for x in range(nw))
        w,h = nw,nh
    paper = options.get("paper", "18 × 24")
    if not isinstance(paper, str) or paper not in PAPER: raise ValueError("Unknown paper preset")
    pw, ph = PAPER[paper]
    margin = finite(options.get("margin",25.4), "margin")
    if margin < 0 or margin*2 >= min(pw,ph): raise ValueError("Margins leave no drawing area")
    scale = min((pw-2*margin)/w, (ph-2*margin)/h)
    pen_width = finite(options.get("pen_width",.3),"pen width")
    bridge = finite(options.get("bridge_gap",0),"bridge gap")
    if not .05 <= pen_width <= 3 or not 0 <= bridge <= 5: raise ValueError("Pen width or gap bridging is out of range")
    config = dict(config)
    config["pen_pitch"] = pen_width*1.25
    config["tolerance"] = min(config["tolerance"],pen_width/2)
    config["spacing"] = max(config["spacing"],pen_width*1.25)
    config["sample"] = max(config["sample"],pen_width)
    config["hatch_pitch"] = max(config["hatch_pitch"],pen_width*1.25)
    mode = options.get("image_mode", "hatching")
    adjusted = False
    if mode == "outlines":
        threshold = finite(options.get("threshold",128), "threshold")
        if not 1 <= threshold <= 255: raise ValueError("Outline threshold must be 1–255")
        paths = outlines(w,h,pixels,threshold,config["tolerance"]/scale)
    elif mode == "hatching":
        # Physical sample sizes keep short dithering strokes printable with a pen.
        columns = max(1, math.ceil(w*scale/config["sample"]))
        rows = max(1, math.ceil(h*scale/config["spacing"]))
        # Worst case: alternating ink/no-ink creates one stroke per two cells.
        # Adapt the grid rather than failing on ordinary photos or large paper.
        while rows*math.ceil(columns/2) > config["strokes"]:
            factor = max(1.01, math.sqrt(rows*math.ceil(columns/2)/config["strokes"]))
            columns = max(1, int(columns/factor))
            rows = max(1, int(rows/factor))
            adjusted = True
        if columns*rows > 20_000_000: raise ValueError("Shading too dense; choose Fast or smaller paper")
        paths = []
        for row in range(rows):
            y = (row+.5)*h/rows
            py = min(h-1, int(y))
            runs, start = [], None
            for col in range(columns+1):
                if col < columns:
                    px = min(w-1, int((col+.5)*w/columns))
                    gray = pixels[py*w+px]
                    ink = gray < (BAYER[row%4][col%4]+.5)*255/16
                else: ink = False
                if ink and start is None: start = col
                elif not ink and start is not None:
                    runs.append([(start*w/columns,y),(col*w/columns,y)])
                    start = None
            # Alternate direction to reduce pen-up travel across the page.
            paths.extend([list(reversed(p)) for p in reversed(runs)] if row%2 else runs)
            if len(paths)*6 > MAX_POINTS: raise ValueError("Image needs too many pen lifts; choose Fast or smaller paper")
    elif mode == "wave":
        paths = wave_paths(w, h, pixels, scale, config)
        if sum(map(len, paths)) > MAX_POINTS: raise ValueError("Wavy lines need too many points; choose Fast or smaller paper")
    elif mode == "crosshatch":
        paths = hatch_paths(w, h, pixels, scale, config, bridge)
    elif mode == "sketch":
        paths = sketch_paths(w, h, pixels, scale, config, bridge)
    else: raise ValueError("Unknown image conversion style")
    if not paths: raise ValueError("No drawable marks found; try another style or adjust the outline threshold")
    warnings = ["Image converted to monochrome pen strokes. A working pen-lift servo is required.",
                "Time includes estimated pen ramps, travel and acceleration; corner slowdowns and the first travel move add time."]
    if adjusted: warnings.append("Shading spacing adapted to paper size to keep this preset's plot budget bounded.")
    return paths, warnings, {"source_type":"image", "quality":key,
                            "image_mode":mode, "image_size":[w,h]}, (0.,0.,float(w),float(h))
