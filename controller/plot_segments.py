"""Safe bounded stored transfers, including splits within a long pen-down path."""
import uuid
from .plot import MAX_BYTES


def split_commands(commands, capacity=MAX_BYTES):
    limit = min(capacity, MAX_BYTES)//16
    if limit < 8:
        raise ValueError('Device storage is too small for safe plot parts')
    parts, current, pen, position = [], [], 'up', None
    for command in commands:
        if len(current) >= limit-2:
            # A boundary always drains XY and lifts the pen, even inside a curve.
            if not (current[-1]['op']=='pen' and current[-1]['role']=='up'):
                current.append({'op':'pen','role':'up'})
            current.append({'op':'sync'})
            parts.append(current)
            current = [{'op':'pen','role':'up'}]
            if position is not None:
                current.append(dict(position))
            if pen == 'down':
                current.append({'op':'pen','role':'down'})
        current.append(command)
        if command['op']=='pen':
            pen=command['role']
        elif command['op']=='move':
            position=command
    if current:
        parts.append(current)
    return parts


def part_identity(job, index):
    return (str(uuid.uuid5(uuid.UUID(job['id']), 'part:'+str(index))),
            str(uuid.uuid5(uuid.UUID(job['plot_run']), 'part:'+str(index))))


def execution_parts(job, capacity=MAX_BYTES):
    """Never combine two pen stages into the same device file."""
    stages=job.get('color_stages')
    if not stages:
        parts=split_commands(job['commands'],capacity)
        return parts,[None]*len(parts)
    parts,owners=[],[]
    for index,stage in enumerate(stages):
        section=job['commands'][stage['command_start']:stage['command_end']]
        split=split_commands(section,capacity)
        parts.extend(split);owners.extend([index]*len(split))
    return parts,owners
