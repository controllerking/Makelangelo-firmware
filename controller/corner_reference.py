"""Rotation-invariant inference of the two unknown belt length offsets."""
import math


def infer_reference(width, belts, pw, ph, position):
    # Fit only belt offsets against rotation-invariant pairwise distances.
    # Keep actual captured points for placement, not a fitted ideal rectangle.
    local = [(0,0),(pw,0),(pw,ph),(0,ph)]
    pairs = [(i,j,math.dist(local[i],local[j])) for i in range(4) for j in range(i+1,4)]

    def residual(z):
        try:
            xy = [position(width,z[0]+b[0],z[1]+b[1]) for b in belts]
            if any(not 10 < x < width-10 or not -2000 < y < -40 for x,y in xy): return None
            return [math.dist(xy[i],xy[j])-target for i,j,target in pairs]
        except ValueError:
            return None

    best = None
    for x in (width*.25,width*.5,width*.75):
        for depth in (100,250,500,900):
            z = [math.hypot(x,depth)-belts[0][0],math.hypot(width-x,depth)-belts[0][1]]
            r = residual(z)
            if r is None: continue
            damping = .01
            for _ in range(100):
                shifted = [residual([z[0]+.01,z[1]]),residual([z[0],z[1]+.01])]
                if any(v is None for v in shifted): break
                jac = [[(v[i]-r[i])/.01 for i in range(6)] for v in shifted]
                a = sum(v*v for v in jac[0])+damping
                b = sum(v*w for v,w in zip(*jac))
                c = sum(v*v for v in jac[1])+damping
                g,h = [sum(v*w for v,w in zip(col,r)) for col in jac]
                det = a*c-b*b
                if det <= 1e-15: break
                delta = [(b*h-c*g)/det,(b*g-a*h)/det]
                factor = min(1,100/max(1,max(abs(v) for v in delta)))
                candidate = [v+factor*d for v,d in zip(z,delta)]
                nr = residual(candidate)
                if nr is not None and sum(v*v for v in nr) < sum(v*v for v in r):
                    z,r = candidate,nr
                    damping = max(1e-8,damping*.3)
                    if max(abs(v*factor) for v in delta) < 1e-6: break
                else:
                    damping *= 10
                    if damping > 1e10: break
            score = sum(v*v for v in r)
            if best is None or score < best[0]: best = score,z,r
    if best is None: raise ValueError("Captured corners cannot form a reachable belt reference; check spacing and belt directions")
    return best[1],max(abs(v) for v in best[2])
