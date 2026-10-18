"""Rebuild the existing Detectron2 CPU extension with the same Windows ABI.

Run in a VS 2022 x64 Native Tools prompt using full CPython 3.12, Torch
2.8.0+cpu and torchvision 0.23.0+cpu. Source and output must be explicit.
This does not fetch code, weights, CUDA or alter the existing source directory.
"""
import argparse
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12):
        raise RuntimeError('Windows CPython 3.12 x64 required')
    if importlib.metadata.version('torch') != '2.8.0+cpu' or importlib.metadata.version('torchvision') != '0.23.0+cpu':
        raise RuntimeError('Existing locked Torch CPU ABI required; no automatic upgrade')
    if not shutil.which('cl.exe'):
        raise RuntimeError('Use the Visual Studio 2022 x64 Native Tools prompt')
    output = args.output.resolve()
    if output.exists() or not str(output).isascii():
        raise RuntimeError('Use a new ASCII build directory; existing output is preserved')
    if not (args.source / 'setup.py').is_file():
        raise RuntimeError('Explicit Detectron2 source with setup.py required')
    output.mkdir(parents=True)
    source = output / 'source'
    shutil.copytree(args.source, source, ignore=shutil.ignore_patterns('.git', 'build', '*.pyd', '__pycache__', '.local', '.private'))
    include, libs = output / 'python-include', output / 'python-libs'
    shutil.copytree(Path(sys.base_prefix) / 'include', include)
    shutil.copytree(Path(sys.base_prefix) / 'libs', libs)
    (output / 'tmp').mkdir()
    env = os.environ.copy()
    env.update(MAX_JOBS='2', FORCE_CUDA='0', DISTUTILS_USE_SDK='1',
               TEMP=str(output / 'tmp'), TMP=str(output / 'tmp'), VSLANG='1033')
    subprocess.run([sys.executable, 'setup.py', 'build_ext', '--inplace',
                    '--build-temp', str(output / 'objects'), '--include-dirs', str(include),
                    '--library-dirs', str(libs)], cwd=source, env=env, check=True)
    print('Compiled CPU source directory:', source)


if __name__ == '__main__':
    main()
