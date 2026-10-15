"""SVG/path preparation. No SVG scripts, URLs, or browser DOM are executed."""
from __future__ import annotations
import math
import re
import xml.etree.ElementTree as ET

NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?"
TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|" + NUMBER)
IDENTITY = (1., 0., 0., 1., 0., 0.)
MAX_POINTS = 100_000
PAPER = {"Letter": (215.9, 279.4), "11 × 14": (279.4, 355.6),
         "11 × 17": (279.4, 431.8), "12 × 18": (304.8, 457.2),
         "16 × 20": (406.4, 508.0), "18 × 24": (457.2, 609.6),
         "A4": (210., 297.), "A3": (297., 420.), "A2": (420., 594.)}


def finite(value, name="value"):
    try:
        n = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(n) or abs(n) > 1e9:
        raise ValueError(f"{name} must be finite and within range")
    return n


def multiply(a, b):
    return (a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
            a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
            a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5])


def point(m, p):
    x, y = p
    return (m[0]*x+m[2]*y+m[4], m[1]*x+m[3]*y+m[5])


def transform(text):
    result = IDENTITY
    consumed = ""
    for match in re.finditer(r"([A-Za-z]+)\s*\(([^)]*)\)", text):
        name, args = match.groups()
        values = [finite(v) for v in re.findall(NUMBER, args)]
        if re.sub(NUMBER + r"|[\s,]", "", args):
            raise ValueError("Invalid SVG transform")
        if name == "matrix" and len(values) == 6:
            m = tuple(values)
        elif name == "translate" and len(values) in (1, 2):
            m = (1, 0, 0, 1, values[0], values[1] if len(values) == 2 else 0)
        elif name == "scale" and len(values) in (1, 2):
            m = (values[0], 0, 0, values[-1], 0, 0)
        elif name == "rotate" and len(values) in (1, 3):
            angle = math.radians(values[0])
            m = (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0, 0)
            if len(values) == 3:
                x, y = values[1:]
                m = multiply(multiply((1, 0, 0, 1, x, y), m), (1, 0, 0, 1, -x, -y))
        elif name in ("skewX", "skewY") and len(values) == 1:
            k = math.tan(math.radians(values[0]))
            m = (1, 0, k, 1, 0, 0) if name == "skewX" else (1, k, 0, 1, 0, 0)
        else:
            raise ValueError(f"Unsupported SVG transform: {name}")
        result = multiply(result, m)
        consumed += match.group(0)
    if re.sub(r"[\s,]", "", re.sub(r"[A-Za-z]+\s*\([^)]*\)", "", text)):
        raise ValueError("Invalid SVG transform")
    return result


def distance_line(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    if dx == dy == 0:
        return math.dist(p, a)
    # Distance to the segment, rather than its infinite line, preserves loops.
    t = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def cubic(a, b, c, d, tolerance, depth=0):
    if depth >= 16 or max(distance_line(b, a, d), distance_line(c, a, d)) <= tolerance:
        return [d]
    mid = lambda p, q: ((p[0]+q[0])/2, (p[1]+q[1])/2)
    ab, bc, cd = mid(a, b), mid(b, c), mid(c, d)
    abc, bcd = mid(ab, bc), mid(bc, cd)
    middle = mid(abc, bcd)
    return cubic(a, ab, abc, middle, tolerance, depth+1) + cubic(middle, bcd, cd, d, tolerance, depth+1)


def ellipse_arc(a, end, rx, ry, rotation, large, sweep, tolerance):
    if large not in (0, 1) or sweep not in (0, 1):
        raise ValueError("SVG arc flags must be 0 or 1")
    rx, ry = abs(rx), abs(ry)
    if not rx or not ry or a == end:
        return [end]
    phi = math.radians(rotation % 360)
    co, si = math.cos(phi), math.sin(phi)
    dx, dy = (a[0]-end[0])/2, (a[1]-end[1])/2
    xp, yp = co*dx+si*dy, -si*dx+co*dy
    scale = xp*xp/(rx*rx)+yp*yp/(ry*ry)
    if scale > 1:
        rx *= math.sqrt(scale); ry *= math.sqrt(scale)
    denominator = rx*rx*yp*yp+ry*ry*xp*xp
    numerator = max(0., rx*rx*ry*ry-denominator)
    factor = (-1 if large == sweep else 1)*math.sqrt(numerator/denominator) if denominator else 0
    cp = (factor*rx*yp/ry, -factor*ry*xp/rx)
    cx = co*cp[0]-si*cp[1]+(a[0]+end[0])/2
    cy = si*cp[0]+co*cp[1]+(a[1]+end[1])/2
    u = ((xp-cp[0])/rx, (yp-cp[1])/ry)
    v = ((-xp-cp[0])/rx, (-yp-cp[1])/ry)
    start = math.atan2(u[1], u[0])
    delta = math.atan2(u[0]*v[1]-u[1]*v[0], u[0]*v[0]+u[1]*v[1])
    if not sweep and delta > 0: delta -= 2*math.pi
    if sweep and delta < 0: delta += 2*math.pi
    step = max(.01, 2*math.acos(max(-1., min(1., 1-tolerance/max(rx, ry)))))
    n = max(1, min(10000, math.ceil(abs(delta)/step)))
    points = []
    for i in range(1, n+1):
        theta = start+delta*i/n
        points.append((cx+co*rx*math.cos(theta)-si*ry*math.sin(theta),
                       cy+si*rx*math.cos(theta)+co*ry*math.sin(theta)))
    points[-1] = end
    return points


def path_data(text, tolerance=.2):
    if re.sub(r"[\s,]", "", TOKEN.sub("", text)):
        raise ValueError("Unsupported or malformed SVG path")
    tokens = TOKEN.findall(text)
    paths, current = [], []
    i = 0
    cmd = None
    p = start = (0., 0.)
    last_c = last_q = None
    previous = ""
    arity = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]; i += 1
        if cmd is None:
            raise ValueError("SVG path requires a command")
        kind, relative = cmd.upper(), cmd.islower()
        if kind == "Z":
            if current and p != start: current.append(start)
            if current: paths.append(current)
            current = []; p = start; previous = "Z"; cmd = None
            last_c = last_q = None
            continue
        n = arity[kind]
        if i+n > len(tokens) or any(t.isalpha() for t in tokens[i:i+n]):
            raise ValueError(f"Incomplete SVG path command {cmd}")
        values = [finite(t) for t in tokens[i:i+n]]; i += n
        pair = lambda j: (values[j]+(p[0] if relative else 0), values[j+1]+(p[1] if relative else 0))
        new_c = new_q = None
        if kind == "M":
            if current: paths.append(current)
            p = pair(0); start = p; current = [p]
            cmd = "l" if relative else "L"
        else:
            if not current: current = [p]
            if kind == "L": end = pair(0); current.append(end)
            elif kind == "H": end = (values[0]+(p[0] if relative else 0), p[1]); current.append(end)
            elif kind == "V": end = (p[0], values[0]+(p[1] if relative else 0)); current.append(end)
            elif kind in ("C", "S"):
                if kind == "C": b, c, end = pair(0), pair(2), pair(4)
                else:
                    b = (2*p[0]-last_c[0], 2*p[1]-last_c[1]) if previous in ("C", "S") else p
                    c, end = pair(0), pair(2)
                current.extend(cubic(p, b, c, end, tolerance)); new_c = c
            elif kind in ("Q", "T"):
                b = pair(0) if kind == "Q" else ((2*p[0]-last_q[0], 2*p[1]-last_q[1]) if previous in ("Q", "T") else p)
                end = pair(2) if kind == "Q" else pair(0)
                c1 = (p[0]+(b[0]-p[0])*2/3, p[1]+(b[1]-p[1])*2/3)
                c2 = (end[0]+(b[0]-end[0])*2/3, end[1]+(b[1]-end[1])*2/3)
                current.extend(cubic(p, c1, c2, end, tolerance)); new_q = b
            elif kind == "A":
                end = pair(5)
                current.extend(ellipse_arc(p, end, *values[:5], tolerance))
            p = end
        last_c, last_q = new_c, new_q
        previous = kind
        if sum(map(len, paths))+len(current) > MAX_POINTS:
            raise ValueError("Artwork has too many points; simplify it first")
    if current: paths.append(current)
    return [p for p in paths if len(p) > 1]


def length(value, default=0):
    if value is None: return default
    match = re.fullmatch(r"\s*(" + NUMBER + r")\s*(px|mm|cm|in|pt|pc)?\s*", value)
    if not match: raise ValueError(f"Unsupported SVG length: {value}")
    scale = {None: 1, "px": 1, "mm": 96/25.4, "cm": 960/25.4, "in": 96, "pt": 96/72, "pc": 16}
    return finite(match[1])*scale[match[2]]


def svg_paths(svg):
    if len(svg.encode("utf-8")) > 2_000_000:
        raise ValueError("SVG limit is 2 MB")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", svg, re.I):
        raise ValueError("SVG document types/entities are not accepted")
    try: root = ET.fromstring(svg)
    except ET.ParseError as exc: raise ValueError(f"Invalid SVG: {exc}") from None
    if root.tag.split("}")[-1] != "svg": raise ValueError("Expected an SVG document")
    nodes = list(root.iter())
    if len(nodes) > 10000: raise ValueError("SVG has too many elements")
    ids = {n.get("id"): n for n in nodes if n.get("id")}
    viewbox = [finite(v) for v in re.findall(NUMBER, root.get("viewBox", ""))]
    tolerance = max(.01, max(viewbox[2:], default=400)/2500)
    paths, warnings = [], set()
    def visit(node, parent, depth=0, references=()):
        if depth > 40: raise ValueError("SVG nesting/reference limit exceeded")
        kind = node.tag.split("}")[-1]
        style = node.get("style", "")
        if node.get("display") == "none" or re.search(r"display\s*:\s*none", style): return
        if node.get("visibility") == "hidden" or re.search(r"visibility\s*:\s*hidden", style): return
        if node.get("opacity") == "0" or re.search(r"opacity\s*:\s*0(?:\.0*)?\s*(?:;|$)", style): return
        if kind == "svg" and depth and any(node.get(k) for k in ("viewBox","x","y","width","height")):
            raise ValueError("Flatten nested SVG viewports before importing")
        if node.get("clip-path") or node.get("mask") or "clip-path:" in style or "mask:" in style:
            raise ValueError("Expand SVG clipping/masks before importing")
        matrix = multiply(parent, transform(node.get("transform", "")))
        a = lambda key, default=0: length(node.get(key), default)
        local = []
        local_tolerance = tolerance / max(math.hypot(matrix[0],matrix[1]), math.hypot(matrix[2],matrix[3]), 1e-9)
        if kind == "path": local = path_data(node.get("d", ""), local_tolerance)
        elif kind == "line": local = [[(a("x1"), a("y1")), (a("x2"), a("y2"))]]
        elif kind in ("polyline", "polygon"):
            text = node.get("points", "")
            if re.sub(NUMBER+r"|[\s,]", "", text): raise ValueError("Invalid SVG points")
            values = [finite(v) for v in re.findall(NUMBER, text)]
            if len(values) % 2: raise ValueError("Unpaired SVG coordinate")
            points = list(zip(values[::2], values[1::2]))
            if kind == "polygon" and points: points.append(points[0])
            local = [points]
        elif kind == "rect":
            x, y, w, h = a("x"), a("y"), a("width"), a("height")
            if w <= 0 or h <= 0: return
            rx = min(w/2, a("rx", a("ry")))
            ry = min(h/2, a("ry", a("rx")))
            if rx > 0 and ry > 0:
                local = path_data(f"M{x+rx} {y} H{x+w-rx} A{rx} {ry} 0 0 1 {x+w} {y+ry} V{y+h-ry} A{rx} {ry} 0 0 1 {x+w-rx} {y+h} H{x+rx} A{rx} {ry} 0 0 1 {x} {y+h-ry} V{y+ry} A{rx} {ry} 0 0 1 {x+rx} {y} Z", local_tolerance)
            else: local = [[(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)]]
        elif kind in ("circle", "ellipse"):
            cx, cy = a("cx"), a("cy")
            rx, ry = (a("r"), a("r")) if kind == "circle" else (a("rx"), a("ry"))
            if rx <= 0 or ry <= 0: return
            n = min(10000, max(32, math.ceil(2*math.pi*max(rx,ry)/max(.2, math.sqrt(tolerance*max(rx,ry))))))
            local = [[(cx+rx*math.cos(i*2*math.pi/n),cy+ry*math.sin(i*2*math.pi/n)) for i in range(n+1)]]
        elif kind == "use":
            ref = node.get("href", node.get("{http://www.w3.org/1999/xlink}href", ""))
            if not ref.startswith("#") or ref[1:] not in ids or ref in references:
                raise ValueError("Invalid or external SVG reference")
            visit(ids[ref[1:]], multiply(matrix, (1,0,0,1,a("x"),a("y"))), depth+1, references+(ref,))
            return
        elif kind in ("text", "image", "foreignObject"):
            raise ValueError(f"Convert SVG {kind} to drawing paths before importing")
        elif kind in ("defs", "metadata", "title", "desc", "script", "style", "namedview"):
            if kind == "style" and (node.text or "").strip():
                raise ValueError("Inline SVG stylesheet rules into attributes before importing")
            return
        elif kind not in ("svg", "g", "a"):
            warnings.add(f"Ignored unsupported SVG element: {kind}")
            return
        for path in local:
            if len(path) > 1: paths.append([point(matrix, p) for p in path])
        if sum(map(len, paths)) > MAX_POINTS: raise ValueError("Artwork has too many points")
        for child in node:
            visit(child, matrix, depth+1, references)
    visit(root, IDENTITY)
    if not paths: raise ValueError("No drawable paths found")
    return paths, sorted(warnings)


def demo_paths(turns=7, samples=1200):
    return [[(math.sin(3*t+.4)*(1+.12*math.cos(turns*t)),
              math.sin(4*t)*(1+.12*math.cos(turns*t)))
             for t in (i*2*math.pi/samples for i in range(samples+1))]]


def prepare(paths, options, pen_up=90, pen_down=40, source_bounds=None):
    paper = options.get("paper", "18 × 24")
    if paper not in PAPER: raise ValueError("Unknown paper preset")
    pw, ph = PAPER[paper]
    margin = finite(options.get("margin", 25.4), "margin")
    left = finite(options.get("left"), "paper left X")
    top = finite(options.get("top"), "paper top Y")
    feed = finite(options.get("feed", 10), "feed")
    if not 0.1 <= feed <= 30: raise ValueError("Feed must be 0.1–30 mm/s")
    if margin < 0 or 2*margin >= min(pw, ph): raise ValueError("Margins leave no drawing area")
    if abs(left) > 10000 or abs(top) > 10000: raise ValueError("Paper origin is out of range")
    flat = [p for path in paths for p in path]
    if len(flat) > MAX_POINTS: raise ValueError("Too many drawing points")
    if not flat or any(not math.isfinite(v) or abs(v) > 1e9 for p in flat for v in p):
        raise ValueError("Invalid artwork coordinates")
    minx, maxx = min(p[0] for p in flat), max(p[0] for p in flat)
    miny, maxy = min(p[1] for p in flat), max(p[1] for p in flat)
    if source_bounds is not None:
        minx, miny, maxx, maxy = source_bounds
    width, height = maxx-minx, maxy-miny
    if width == height == 0: raise ValueError("Artwork has no extent")
    scale = min((pw-2*margin)/width if width else math.inf,
                (ph-2*margin)/height if height else math.inf)
    ox = left+(pw-width*scale)/2
    oy = top-(ph-height*scale)/2
    placed = [[(round(ox+(x-minx)*scale, 3), round(oy-(y-miny)*scale, 3))
               for x,y in path] for path in paths]
    corners = options.get("paper_corners")
    paper_rect = [left,top,pw,ph]
    if corners is not None:
        if len(corners)!=4 or any(len(p)!=2 for p in corners): raise ValueError("Expected four paper corners")
        corners = [[finite(v,"paper corner") for v in p] for p in corners]
        def warp(p):
            u,v = (p[0]-left)/pw,(top-p[1])/ph
            weights = [(1-u)*(1-v),u*(1-v),u*v,(1-u)*v]
            return tuple(round(sum(w*c[axis] for w,c in zip(weights,corners)),3) for axis in range(2))
        warped,point_count = [],0
        for path in placed:
            result = [warp(path[0])]
            for a,b in zip(path,path[1:]):
                # Bilinear placement can curve a diagonal. Subdivide first.
                n = max(1,math.ceil(math.dist(a,b)/5))
                if point_count+len(result)+n>MAX_POINTS: raise ValueError("Too many transformed drawing points")
                result.extend(warp((a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n)) for i in range(1,n+1))
            warped.append(result)
            point_count += len(result)
        placed = warped
        xmin,xmax = min(p[0] for p in corners),max(p[0] for p in corners)
        ymin,ymax = min(p[1] for p in corners),max(p[1] for p in corners)
        paper_rect = [xmin,ymax,xmax-xmin,ymax-ymin]
    commands, seconds, drawn, travel = [], 0., 0., 0.
    previous = None
    for path in placed:
        clean = [path[0]]
        for p in path[1:]:
            if math.dist(p, clean[-1]) >= .02: clean.append(p)
        if len(clean) < 2: continue
        commands.append({"op":"pen","angle":pen_up,"role":"up"})
        commands.append({"op":"move","x":clean[0][0],"y":clean[0][1],"feed":feed})
        if previous is not None: travel += math.dist(previous, clean[0])
        commands.append({"op":"pen","angle":pen_down,"role":"down"})
        for a,b in zip(clean, clean[1:]):
            drawn += math.dist(a,b)
            commands.append({"op":"move","x":b[0],"y":b[1],"feed":feed})
        commands.append({"op":"pen","angle":pen_up,"role":"up"})
        previous = clean[-1]; seconds += .9
    commands.append({"op":"sync"})
    if len(commands) == 1: raise ValueError("Artwork contains no nonzero drawing paths")
    if len(commands) > 100_000: raise ValueError("Job too large; simplify the SVG")
    seconds += (drawn+travel)/feed
    return {"commands":commands, "paths":placed, "paper":paper,
            "pen_up":pen_up, "pen_down":pen_down,
            "paper_rect":paper_rect, "paper_corners":corners, "paper_size":[pw,ph], "margin":margin,
            "bounds":[min(p[0] for path in placed for p in path),
                      min(p[1] for path in placed for p in path),
                      max(p[0] for path in placed for p in path),
                      max(p[1] for path in placed for p in path)],
            "estimated_seconds":round(seconds), "drawn_mm":round(drawn),
            "command_count":len(commands)}
