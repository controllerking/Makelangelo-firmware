"""Physical-unit toolpath cleanup, bounded routing, and timing models."""
import math
from itertools import islice


def simplify(path, tolerance):
    from .artwork import distance_line
    if len(path) < 3 or tolerance <= 0:
        return path
    keep, stack, work = {0, len(path)-1}, [(0, len(path)-1)], 0
    while stack:
        a, b = stack.pop()
        if b-a < 2:
            continue
        work += b-a-1
        if work > 40_000_000:  # Keep the input detail rather than failing preparation.
            return path
        distance, i = max((distance_line(path[i], path[a], path[b]), i) for i in range(a+1, b))
        if distance > tolerance:
            keep.add(i)
            stack.extend(((a, i), (i, b)))
    return [path[i] for i in sorted(keep)]


def route(paths, enabled=False):
    """Bounded nearest-endpoint routing; never add ink between paths."""
    if not enabled or len(paths) < 2:
        return paths
    # Spatial buckets avoid quadratic work on thousands of hatch strokes.
    cell = max(1., math.sqrt(sum(math.dist(p[0], p[-1]) for p in paths)/len(paths)))
    buckets = {}
    for i, p in enumerate(paths):
        for reverse, end in enumerate((p[0], p[-1])):
            key = (math.floor(end[0]/cell), math.floor(end[1]/cell))
            buckets.setdefault(key, {})[(i, reverse)] = None
    def remove_endpoints(i):
        for reverse,end in enumerate((paths[i][0],paths[i][-1])):
            key=(math.floor(end[0]/cell),math.floor(end[1]/cell))
            buckets[key].pop((i,reverse),None)
    remaining = set(range(1, len(paths)))
    remove_endpoints(0)
    result = [paths[0]]
    while remaining:
        end = result[-1][-1]
        bx, by = math.floor(end[0]/cell), math.floor(end[1]/cell)
        candidates = []
        for radius in range(5):
            for x in range(bx-radius, bx+radius+1):
                for y in range(by-radius, by+radius+1):
                    if radius and max(abs(x-bx), abs(y-by)) != radius:
                        continue
                    bucket=buckets.get((x,y), {})
                    # Endpoint deletion is O(1), including coincident endpoints.
                    candidates.extend(islice(bucket,64))
            if candidates:
                break
        if not candidates:
            candidates = [(i, rev) for i in islice(remaining,64) for rev in (0,1)]
        i, rev = min(candidates, key=lambda item: (math.dist(end, paths[item[0]][-1 if item[1] else 0]), item))
        result.append(list(reversed(paths[i])) if rev else paths[i])
        remaining.remove(i)
        remove_endpoints(i)
    def travel(ps):
        return sum(math.dist(a[-1], b[0]) for a,b in zip(ps,ps[1:]))
    # Bounded local 2-opt: reverse both path order and stroke direction.
    comparisons=0
    for i in range(len(result)-2):
        if comparisons>=100_000: break
        for j in range(i+2,min(len(result)-1,i+18)):
            comparisons+=1
            before=math.dist(result[i][-1],result[i+1][0])+math.dist(result[j][-1],result[j+1][0])
            after=math.dist(result[i][-1],result[j][-1])+math.dist(result[i+1][0],result[j+1][0])
            if after+1e-6<before:
                result[i+1:j+1]=[list(reversed(p)) for p in reversed(result[i+1:j+1])]
                break
    # Do not accept a heuristic route that is worse than original ordering.
    return result if travel(result) < travel(paths) else paths


def ramp_seconds(distance, speed, acceleration):
    distance = abs(distance)
    if not distance:
        return 0.
    if distance <= speed*speed/acceleration:
        return 2*math.sqrt(distance/acceleration)
    return distance/speed + speed/acceleration


def estimate(commands, up, down, servo_speed=35., acceleration=50.):
    pen, previous = up, None
    drawing = travel = pen_time = motion_overhead = 0.
    stroke_distance, stroke_feed = 0., None
    def overhead(distance, feed):
        return max(0., ramp_seconds(distance, feed, acceleration)-distance/feed) if distance else 0.
    for command in commands:
        if command['op'] == 'pen':
            target = up if command['role'] == 'up' else down
            if target != pen:
                pen_time += ramp_seconds(target-pen, servo_speed, 100.) + .3
                if stroke_feed:
                    motion_overhead += overhead(stroke_distance, stroke_feed)
                stroke_distance, stroke_feed = 0., None
                pen = target
        elif command['op'] == 'move':
            current = (command['x'], command['y'])
            if previous is not None:
                length = math.dist(previous, current)
                if pen == up:
                    travel += length/command['feed']
                    motion_overhead += overhead(length, command['feed'])
                else:
                    drawing += length/command['feed']
                    stroke_distance += length
                    stroke_feed = command['feed']
            previous = current
    if stroke_feed:
        motion_overhead += overhead(stroke_distance, stroke_feed)
    return dict(drawing_seconds=round(drawing, 2), travel_seconds=round(travel, 2),
                pen_seconds=round(pen_time, 2), acceleration_seconds=round(motion_overhead, 2),
                estimated_seconds=round(drawing+travel+pen_time+motion_overhead))
