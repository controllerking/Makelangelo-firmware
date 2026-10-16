"""Limited-palette RGB image separation for manual red/green/blue/black pens."""
import base64
import binascii
import math
from .artwork import MAX_POINTS, prepare
from .raster import MAX_DIMENSION, preset, raster_paths

PENS = (
    ('red', 'Red', '#dc232d', (220,35,45)),
    ('green', 'Green', '#1e8c41', (30,140,65)),
    ('blue', 'Blue', '#2350d2', (35,80,210)),
    ('black', 'Black', '#191919', (25,25,25)),
)
PALETTE = [pen[3] for pen in PENS] + [(255,255,255)]


def decode_rgb(image, options):
    if not isinstance(image,dict) or image.get('channels')!=3:
        raise ValueError('Four-pen drawings need an RGB image; upload PNG, JPG or WebP')
    w,h=image.get('width'),image.get('height')
    if type(w) is not int or type(h) is not int or not 2<=w<=MAX_DIMENSION or not 2<=h<=MAX_DIMENSION:
        raise ValueError('RGB image dimensions must be 2–768 pixels')
    encoded=image.get('pixels')
    if not isinstance(encoded,str) or len(encoded)>4*((w*h*3+2)//3): raise ValueError('Invalid RGB image size')
    try: pixels=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error): raise ValueError('Invalid RGB image encoding') from None
    if len(pixels)!=w*h*3: raise ValueError('RGB pixel count does not match dimensions')
    _,profile=preset(options)
    factor=min(1.,profile['resolution']/max(w,h))
    nw,nh=max(2,round(w*factor)),max(2,round(h*factor))
    if (nw,nh)!=(w,h):
        pixels=bytes(v for y in range(nh) for x in range(nw)
                     for offset in [(min(h-1,int(y*h/nh))*w+min(w-1,int(x*w/nw)))*3]
                     for v in pixels[offset:offset+3])
        w,h=nw,nh
    return w,h,pixels


def separate(w,h,pixels,dither=True):
    """Spatial palette dithering, never additive RGB overprinting."""
    labels=bytearray([4])*(w*h)
    current=[[0.,0.,0.] for _ in range(w+2)]
    for y in range(h):
        following=[[0.,0.,0.] for _ in range(w+2)]
        direction=1 if y%2==0 else -1
        for x in (range(w) if direction==1 else range(w-1,-1,-1)):
            offset=(y*w+x)*3
            rgb=[max(0.,min(255.,pixels[offset+c]+current[x+1][c])) for c in range(3)]
            # Keep neutral source regions neutral rather than giving gray a green cast.
            source=pixels[offset:offset+3]
            choices=(3,4) if max(source)-min(source)<12 else range(5)
            selected=min(choices,key=lambda i:sum(weight*(rgb[c]-PALETTE[i][c])**2
                                                 for c,weight in enumerate((.30,.59,.11))))
            labels[y*w+x]=selected
            if dither:
                for c in range(3):
                    error=rgb[c]-PALETTE[selected][c]
                    current[x+1+direction][c]+=error*7/16
                    following[x+1-direction][c]+=error*3/16
                    following[x+1][c]+=error*5/16
                    following[x+1+direction][c]+=error/16
        current=following
    return labels


def prepare_color(image,options,pen_up,pen_down):
    w,h,pixels=decode_rgb(image,options)
    dither=options.get('color_dither',True)
    if type(dither) is not bool: raise ValueError('Color dithering must be true or false')
    labels=separate(w,h,pixels,dither)
    commands,paths,stages=[],[],[]
    first=None
    omitted=[]
    for index,(key,name,swatch,_) in enumerate(PENS):
        if index not in labels: continue
        mask=bytes(0 if label==index else 255 for label in labels)
        # Outlines preserve solid logo edges; hatching is the default for palette photos.
        stage_options=dict(options,image_mode='outlines' if options.get('image_mode')=='outlines' else 'hatching')
        image_mask=dict(width=w,height=h,pixels=base64.b64encode(mask).decode())
        try:
            strokes,_,_,bounds=raster_paths(image_mask,stage_options)
            prepared=prepare(strokes,stage_options,pen_up,pen_down,bounds)
        except ValueError as exc:
            if str(exc).startswith(("No drawable marks found","Artwork contains no nonzero drawing paths")):
                omitted.append(name)
                continue
            raise
        if first is None: first=prepared
        stages.append(dict(pen=key,name=name,swatch=swatch,command_start=len(commands),
                           command_end=len(commands)+len(prepared['commands']),path_start=len(paths),
                           path_end=len(paths)+len(prepared['paths']),estimated_seconds=prepared['estimated_seconds']))
        commands.extend(prepared['commands']);paths.extend(prepared['paths'])
    if not stages: raise ValueError('No colored marks found; the image is blank or too pale')
    if sum(map(len,paths))>4*MAX_POINTS: raise ValueError('Color job is too complex; choose Fast')
    result=dict(first,commands=commands,paths=paths,color_stages=stages,color_mode='rgbk',
                command_count=len(commands),path_count=len(paths),image_size=[w,h],color_dither=dither,omitted_colors=omitted)
    result['estimated_seconds']=sum(s['estimated_seconds'] for s in stages)
    # Compute drawing statistics over all colors, not just the first stage.
    from .toolpath import estimate
    result.update(estimate(commands,pen_up,pen_down,float(options.get('servo_speed',35))))
    result['drawn_mm']=round(sum(math.dist(a,b) for path in paths for a,b in zip(path,path[1:])))
    result['bounds']=[min(p[0] for path in paths for p in path),min(p[1] for path in paths for p in path),
                      max(p[0] for path in paths for p in path),max(p[1] for path in paths for p in path)]
    return result
