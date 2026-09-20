"""Compile and run the portable timing core, without a board or audio device."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory


def main():
    source=Path(__file__).resolve().with_name('check_timed_audio.cpp')
    # MSVC's shared compiler server can briefly retain its working directory.
    with TemporaryDirectory(prefix='echo-timed-audio-',ignore_cleanup_errors=True) as folder:
        work=Path(folder);binary=work/('timed.exe' if os.name=='nt' else 'timed')
        compiler=shutil.which('c++') or shutil.which('g++')
        if compiler:
            subprocess.run([compiler,'-std=c++17','-O2',str(source),'-o',str(binary)],check=True)
        elif os.name=='nt':
            vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
            install=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires',
                'Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
            if not install:raise RuntimeError('An existing C++ compiler is required')
            vcvars=Path(install)/'VC/Auxiliary/Build/vcvars64.bat'
            script=work/'build.cmd'
            script.write_text(f'@call "{vcvars}" >nul\n@cl /nologo /EHsc /std:c++17 /O2 "{source}" /Fe:"{binary}" /Fo:"{work / "timed.obj"}"\n',encoding='utf-8')
            subprocess.run(['cmd','/d','/c',str(script)],cwd=work,check=True)
        else:raise RuntimeError('An existing C++ compiler is required')
        subprocess.run([str(binary)],check=True)


if __name__=='__main__':main()
