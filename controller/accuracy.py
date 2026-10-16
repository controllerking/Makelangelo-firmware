"""Measured calibration artwork; generation never commands the robot."""
import math
from .artwork import PAPER, finite


def diagnostic_paths(options):
    pw,ph=PAPER[options.get('paper','18 × 24')]
    margin=finite(options.get('margin',25.4),'margin')
    w,h=pw-2*margin,ph-2*margin
    if min(w,h)<60:
        raise ValueError('Accuracy pattern needs at least 60 mm of drawing area')
    paths=[[(0,0),(w,0),(w,h),(0,h),(0,0)]]
    for x in range(50,math.ceil(w),50): paths.append([(x,0),(x,h)])
    for y in range(50,math.ceil(h),50): paths.append([(0,y),(w,y)])
    paths.extend([[(0,0),(w,h)],[(0,h),(w,0)]])
    paths.append([(w/2+25*math.cos(i*math.tau/256),h/2+25*math.sin(i*math.tau/256)) for i in range(257)])
    return paths,(0,0,w,h)


def measurement_report(samples):
    """Analyze held-out measured XY offsets without silently altering calibration."""
    if not 3<=len(samples)<=100:
        raise ValueError('Supply 3–100 measured grid intersections')
    errors=[]
    for sample in samples:
        expected,measured=sample['expected'],sample['measured']
        if len(expected)!=2 or len(measured)!=2: raise ValueError('Expected XY coordinate pairs')
        dx,dy=[finite(b,'measured position')-finite(a,'expected position') for a,b in zip(expected,measured)]
        errors.append((dx,dy))
    return dict(samples=len(errors),rms_mm=math.sqrt(sum(x*x+y*y for x,y in errors)/len(errors)),
                max_mm=max(math.hypot(x,y) for x,y in errors),
                mean_dx_mm=sum(x for x,y in errors)/len(errors),mean_dy_mm=sum(y for x,y in errors)/len(errors))


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description='Analyze measured accuracy-grid intersections without changing robot calibration')
    parser.add_argument('measurements',type=Path,help='JSON array of expected/measured XY pairs in millimeters')
    args=parser.parse_args()
    print(json.dumps(measurement_report(json.loads(args.measurements.read_text())),indent=2))
