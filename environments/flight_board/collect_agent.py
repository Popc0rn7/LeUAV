"""Collect an existing Agent and its non-toolchain runtime dependencies."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

output = Path('/opt/flight-board')
(output/'bin').mkdir(parents=True)
(output/'lib').mkdir()
agent = Path(shutil.which('MicroXRCEAgent') or '/missing/MicroXRCEAgent')
shutil.copyfile(agent, output/'bin/MicroXRCEAgent')
(output/'bin/MicroXRCEAgent').chmod(0o755)
result = subprocess.run(['ldd', str(agent)], check=True, capture_output=True, text=True).stdout
if 'not found' in result:
    raise RuntimeError(result)
# Use the destination OS's loader, libc and C++ toolchain runtime. All other
# Agent dependencies stay private; do not overwrite PX4/Gazebo libraries.
system = {'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2', 'librt.so.1',
          'libstdc++.so.6', 'libgcc_s.so.1', 'libresolv.so.2'}
for name, path in re.findall(r'^\s*(\S+) => (/\S+)', result, re.M):
    if name not in system:
        shutil.copyfile(path, output/'lib'/name)
shutil.copyfile('/opt/uav/sources.txt', output/'agent-sources.txt')
files = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
         for path in output.rglob('*') if path.is_file()}
(output/'agent-manifest.json').write_text(json.dumps(dict(files=files, source_ldd=result), indent=2)+'\n')
