"""Four-corner paper calibration without an axis-alignment assumption."""
import math
import time
import uuid

from .artwork import PAPER, finite
from .corner_reference import infer_reference

CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")


def position(width, left, right):
    if min(left,right) <= 0: raise ValueError("Invalid inferred belt lengths; check motor direction and captures")
    x = (left*left+width*width-right*right)/(2*width)
    depth = left*left-x*x
    if depth <= 0: raise ValueError("Captured lengths do not form a valid triangle")
    return x, -math.sqrt(depth)


def fit(draft):
    paper = draft["paper"]
    if paper not in PAPER: raise ValueError("Unknown paper size")
    width = finite(draft["width"], "motor spacing")
    if not 100 <= width <= 2000: raise ValueError("Motor spacing must be 100–2000 mm")
    spu = [finite(v,"steps/mm") for v in draft["spu"]]
    if len(spu) != 2 or not all(1 <= v <= 10000 for v in spu): raise ValueError("Invalid motor scale")
    counts = draft["corners"]
    if set(counts) != set(CORNERS): raise ValueError("Capture all four corners in order")
    belts = {key:[finite(v,"corner steps")/s for v,s in zip(counts[key],spu)] for key in CORNERS}
    if any(len(counts[key]) != 2 for key in CORNERS): raise ValueError("Invalid corner capture")
    pw,ph = PAPER[paper]
    if any(math.dist(belts[a],belts[b])<1 for i,a in enumerate(CORNERS) for b in CORNERS[i+1:]):
        raise ValueError("Corner captures are degenerate; capture four distinct corners")
    (zero_l,zero_r),error = infer_reference(width,[belts[key] for key in CORNERS],pw,ph,position)
    measured = {}
    for name in CORNERS:
        lengths = [zero_l+belts[name][0],zero_r+belts[name][1]]
        if not all(0 < v <= 4000 for v in lengths): raise ValueError("Invalid inferred belt reference")
        xy = position(width,*lengths)
        measured[name] = {"steps":list(counts[name]),"belts":lengths,"xy":list(xy)}
    points = [measured[key]["xy"] for key in CORNERS]
    for i in range(4):
        a,b,c = points[i],points[(i+1)%4],points[(i+2)%4]
        if (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]) >= -.1:
            raise ValueError("Corners must form a non-crossing outline in top-left, top-right, bottom-right, bottom-left order")
    xmin,xmax = min(p[0] for p in points),max(p[0] for p in points)
    ymin,ymax = min(p[1] for p in points),max(p[1] for p in points)
    return {"version":2,"id":str(uuid.uuid4()),"created":time.time(),"paper":paper,
            "width":width,"spu":spu,"zero_belts":[zero_l,zero_r],
            "left":points[0][0],"top":points[0][1],"paper_rect":[xmin,ymax,xmax-xmin,ymax-ymin],
            "bounds":[max(10,xmin-3),max(-2000,ymin-3),min(width-10,xmax+3),min(-40,ymax+3)],
            "corners":measured,"max_error_mm":round(error,3)}


def reference_command(calibration, lengths):
    xmin,ymin,xmax,ymax = calibration["bounds"]
    return {"op":"cal_apply","confirm":True,"cal_id":calibration["id"],"width":calibration["width"],
            "l":lengths[0],"r":lengths[1],"xmin":xmin,"xmax":xmax,"ymin":ymin,"ymax":ymax}
