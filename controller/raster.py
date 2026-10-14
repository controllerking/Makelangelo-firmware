"""Bounded grayscale-to-pen conversion; decoding happens in the local browser.

No cloud calls, image-codec dependency or original file persistence. Coordinates
retain the full image frame, including whitespace, until paper placement.
"""
from __future__ import annotations
import base64
import binascii
import math

from .artwork import MAX_POINTS, PAPER, finite, distance_line

PRESETS = {
    "fast": {"label": "Fast", "resolution": 256, "spacing": 1.8, "strokes": 3000,
             "sample": 1.2, "tolerance": .4, "feed": 15,
             "description": "Fewer lines, bolder shapes, shorter plots."},
    "balanced": {"label": "Balanced", "resolution": 512, "spacing": 1., "strokes": 7000,
                 "sample": .75, "tolerance": .2, "feed": 10,
                 "description": "A practical balance of detail and drawing time."},
    "detailed": {"label": "Detailed", "resolution": 768, "spacing": .5, "strokes": 14000,
                 "sample": .45, "tolerance": .1, "feed": 6,
                 "description": "Denser shading and finer outlines; longer plots."},
}
MAX_DIMENSION = 768
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
        raise ValueError("Image dimensions must be 2–768 pixels after resizing")
    encoded = image.get("pixels")
    if not isinstance(encoded, str) or len(encoded) > 4*((w*h+2)//3):
        raise ValueError("Invalid grayscale image size")
    try: pixels = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error): raise ValueError("Invalid image encoding") from None
    if len(pixels) != w*h: raise ValueError("Grayscale pixel count does not match dimensions")
    return w, h, pixels


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
        if work > 2_000_000: raise ValueError("Outline too complex; choose Fast or a simpler image")
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
        if columns*rows > 2_000_000: raise ValueError("Shading too dense; choose Fast or smaller paper")
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
            if len(paths)*6 > 95_000: raise ValueError("Image needs too many pen lifts; choose Fast or smaller paper")
    else: raise ValueError("Unknown image conversion style")
    if not paths: raise ValueError("No drawable marks found; try another style or adjust the outline threshold")
    warnings = ["Image converted to monochrome pen strokes. A working pen-lift servo is required.",
                "Time is approximate; acceleration, pen lifts and the first travel move add time."]
    if adjusted: warnings.append("Shading spacing adapted to paper size to keep this preset's plot budget bounded.")
    return paths, warnings, {"source_type":"image", "quality":key,
                            "image_mode":mode, "image_size":[w,h]}, (0.,0.,float(w),float(h))
