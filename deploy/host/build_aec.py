"""Build the reviewed 1.0.1 source on Linux x86_64, with two bounded workers."""
import hashlib
from pathlib import Path
import platform
import subprocess
import sys
import tarfile

archive = Path('/build/aec_audio_processing-1.0.1.tar.gz')
if platform.machine() != 'x86_64': raise RuntimeError('This AEC build is for Remote host x86_64')
assert hashlib.sha256(archive.read_bytes()).hexdigest() == 'f03a3ce3f45bf15a04a8504d0f692a651180ca2d3171bd9f3de0516e5f2b8360'
with tarfile.open(archive) as source: source.extractall('/build/source', filter='data')
root = Path('/build/source/aec_audio_processing-1.0.1')
path = root/'setup.py'
code = path.read_text()
def replace(old, new, count=1):
    global code
    if code.count(old) != count: raise RuntimeError('AEC upstream build layout changed')
    code = code.replace(old, new)
# Upstream incorrectly defines ARM64/NEON for all Linux machines.
replace("        '-DWEBRTC_HAS_NEON',\n        '-DWEBRTC_ARCH_ARM64',\n", '', 2)
replace("subprocess.check_call(['ninja', '-C', build_dir],", "subprocess.check_call(['ninja', '-j', '2', '-C', build_dir],")
# Bundle Abseil into the shared APM instead of depending on build-stage paths.
replace("        '--default-library=shared',", "        '--default-library=shared',\n        '-Dabseil-cpp:default_library=static',")
path.write_text(code)
subprocess.run([sys.executable, 'setup.py', 'bdist_wheel', '--dist-dir', '/wheels'], cwd=root, check=True)
