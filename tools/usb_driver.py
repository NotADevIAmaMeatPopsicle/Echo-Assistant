"""Use the pinned HWCDC fix only in this project; do not edit the shared framework."""
from pathlib import Path
import hashlib

Import('env')

driver = Path(env.subst('$PROJECT_DIR')) / 'src/vendor_hwcdc.cpp'
expected = 'bccc9863cd7d618283a4a7707aee3e010f07a0a998710468d73f863afc9f96d8'
if hashlib.sha256(driver.read_bytes()).hexdigest() != expected:
    raise RuntimeError('Pinned HWCDC source checksum mismatch')


def replace_hwcdc(node):
    path = Path(node.srcnode().get_abspath())
    if path.name == 'HWCDC.cpp' and path.parent.name == 'esp32':
        return None
    return node


env.AddBuildMiddleware(replace_hwcdc)
