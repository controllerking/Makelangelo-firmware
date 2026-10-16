"""Compile the real PlotStore against an in-memory FS and real ArduinoJson.

python3 test/run_storage_native.py --cxx g++ --arduinojson .pio/libdeps/esp32-polargraph/ArduinoJson/src
The host adapters replace hardware headers only; PlotStore logic is unchanged.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('--cxx',default='g++')
parser.add_argument('--arduinojson',type=Path,required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix='drawy-storage-test-') as directory:
    directory=Path(directory)
    source=(root/'src/plot_store.cpp').read_text()
    assert source.startswith('#include "configure.h"')
    (directory/'plot_store.cpp').write_text(source.replace('#include "configure.h"','#include "prelude.h"',1))
    binary=directory/'storage-test'
    subprocess.run([args.cxx,'-std=c++17','-O2','-I'+str(root/'src'),'-I'+str(root/'test/host_storage'),
                    '-I'+str(args.arduinojson.resolve()),str(directory/'plot_store.cpp'),
                    str(root/'test/plot_store_native.cpp'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    print('PASS: real PlotStore completion, Stop, expiry, failure cleanup, reboot and multipart/retry identity')
