"""Compact, checksummed on-device plot format (16 bytes per command)."""
import math
import struct
import zlib

RECORD=struct.Struct("<Ifff")
MAX_BYTES=1024*1024

def encode_plot(job):
    data=bytearray()
    last_pen="up"
    for command in job["commands"]:
        op=command["op"]
        if op=="move":
            x,y,feed=[float(command[k]) for k in ("x","y","feed")]
            if not all(math.isfinite(v) for v in (x,y,feed)) or not .1<=feed<=30:
                raise ValueError("Invalid plot movement")
            data.extend(RECORD.pack(0,x,y,feed))
        elif op=="pen":
            role=command.get("role")
            if role not in ("up","down"):raise ValueError("Plot pen commands need a calibrated role")
            data.extend(RECORD.pack(1 if role=="up" else 2,0,0,0));last_pen=role
        elif op=="sync":data.extend(RECORD.pack(3,0,0,0))
        else:raise ValueError("Unsupported stored-plot operation")
    if not data or job["commands"][-1]["op"]!="sync" or last_pen!="up":
        raise ValueError("Plot must finish with pen lifted and sync")
    if len(data)>MAX_BYTES:raise ValueError("Plot exceeds the 1 MiB device limit; use a faster/simpler conversion preset or split the drawing")
    return bytes(data),zlib.crc32(data)
