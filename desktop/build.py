"""Allowlisted portable build. No development data, env, media or cache inputs."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'backend'))
from desktop.package_scope import assert_local_frontend, assert_local_package, copy_desktop_runtime, local_core_modules
SKIP = {"__pycache__", "tests", "test", ".git", ".local", ".private"}
ROOT_DEPENDENCIES = ["fastapi", "uvicorn", "numpy", "opencv-python-headless", "pillow",
    "pillow-heif", "python-dotenv", "python-multipart", "pydantic-settings", "openai",
    "bcrypt", "httpx", "imageio-ffmpeg", "psutil", "pywebview", "torch", "torchvision",
    "fvcore", "iopath", "hydra-core", "pycocotools", "cloudpickle", "omegaconf",
    "yacs", "tabulate", "tqdm", "termcolor", "setuptools",
    "onnxruntime-directml"]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_tree(source, target):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*SKIP, "*.pyc", "*.pyo"))


def distributions(roots):
    found = {}
    for root in roots:
        if any(part.lower() in {".local", ".private"} for part in root.parts):
            raise ValueError("Private directories are forbidden build inputs")
        for dist in metadata.distributions(path=[str(root)]):
            name = canonicalize_name(dist.metadata["Name"])
            found.setdefault(name, (dist, root))
    selected, pending = {}, list(ROOT_DEPENDENCIES)
    while pending:
        name = canonicalize_name(pending.pop())
        if name in selected:
            continue
        if name not in found:
            raise RuntimeError("Missing distribution: " + name)
        dist, root = found[name]
        selected[name] = (dist, root)
        for value in dist.requires or []:
            requirement = Requirement(value)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            child = canonicalize_name(requirement.name)
            if child not in found or not requirement.specifier.contains(found[child][0].version, prereleases=True):
                raise RuntimeError(f"Unsatisfied dependency: {name} -> {requirement}")
            pending.append(child)
    return selected


def build(args):
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("Build requires Windows x64 Python 3.12")
    assert_local_frontend(PROJECT / 'frontend/dist')
    destination = args.output.resolve()
    if destination.exists():
        raise RuntimeError("Build output must be a new directory; existing files are preserved")
    destination.mkdir(parents=True)
    runtime = destination / "runtime"
    runtime.mkdir()
    source_python = Path(sys.base_prefix)
    for name in ("python.exe", "pythonw.exe", "python3.dll", "python312.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        shutil.copy2(source_python / name, runtime / name)
    copy_tree(source_python / "DLLs", runtime / "DLLs")
    shutil.copytree(source_python / "Lib", runtime / "Lib", ignore=shutil.ignore_patterns(
        *SKIP, "site-packages", "ensurepip", "idlelib", "venv", "*.pyc", "*.pyo"))
    (runtime / "python312._pth").write_text("DLLs\nLib\nLib/site-packages\n..\n../backend\nimport site\n", encoding="utf-8")
    selected = distributions(args.site)
    versions = {name: dist.version for name, (dist, _) in sorted(selected.items())}
    lock = PROJECT / "desktop/dependencies.lock.json"
    if args.write_lock:
        lock.write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")
    elif json.loads(lock.read_text(encoding="utf-8")) != versions:
        raise RuntimeError("Dependency versions differ from desktop lock")
    site = runtime / "Lib/site-packages"
    site.mkdir()
    inventory = []
    for name, (dist, root) in sorted(selected.items()):
        size = 0
        for item in dist.files or []:
            if item.is_absolute() or ".." in item.parts or "__pycache__" in item.parts or str(item).endswith((".pyc", ".pyo", ".lib", ".h", ".hpp", ".cuh")):
                continue
            source, target = root / item, site / item
            if not source.is_file():
                continue
            if source.is_symlink():
                raise RuntimeError("Distribution contains symlink")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            size += source.stat().st_size
        license_name = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See distribution license files"
        inventory.append({"name": name, "version": dist.version, "bytes": size,
                          "source": "Installed wheel / RECORD allowlist", "license": license_name[:200]})
    # Use the existing compiled ABI; do not silently rebuild/upgrade Detectron2.
    copy_tree(args.detectron / "detectron2", site / "detectron2")
    shutil.copy2(args.detectron / "LICENSE", site / "detectron2/LICENSE")
    target = destination / 'backend/core'
    target.mkdir(parents=True)
    for name in sorted(local_core_modules(PROJECT / 'backend/core')):
        shutil.copy2(PROJECT / 'backend/core' / (name + '.py'), target / (name + '.py'))
    shutil.copy2(PROJECT / 'backend/boulder_local_app.py', destination / 'backend/boulder_local_app.py')
    copy_tree(PROJECT / "backend/model_assets", destination / "backend/model_assets")
    from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer
    # Never produce an apparently usable build with missing/wrong RTMW weights.
    LocalRTMWReplayAnalyzer(device='cpu')._load_models()
    (destination / "backend/vendor").mkdir()
    for name in ("NotoSansSC-VF.ttf", "NotoSansSC-OFL.txt"):
        shutil.copy2(PROJECT / "backend/vendor" / name, destination / "backend/vendor" / name)
    shutil.copy2(PROJECT / "backend/vendor/__init__.py", destination / "backend/vendor/__init__.py")
    copy_tree(PROJECT / "backend/vendor/rtmlib", destination / "backend/vendor/rtmlib")
    copy_tree(PROJECT / "docs/bouldering-knowledge", destination / "docs/bouldering-knowledge")
    copy_desktop_runtime(PROJECT / 'desktop', destination / 'desktop')
    copy_tree(PROJECT / "frontend/dist", destination / "frontend/dist")
    index = destination / "frontend/dist/index.html"
    index.write_text(index.read_text(encoding="utf-8").replace("<head>", "<head><script>window.__AI_CLIMBING_DESKTOP__=true;</script>"), encoding="utf-8")
    (destination / "licenses").mkdir()
    shutil.copy2(PROJECT / "desktop/THIRD_PARTY.md", destination / "licenses/THIRD_PARTY.md")
    shutil.copy2(PROJECT / "desktop/使用说明.md", destination / "使用说明.md")
    if args.checkpoint:
        if any(part.lower() in {".local", ".private"} for part in args.checkpoint.parts):
            raise ValueError("Private checkpoint input is forbidden")
        (destination / "models").mkdir()
        shutil.copy2(args.checkpoint, destination / "models/verified-model_final.pth")
    compiler = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64",
                    "/reference:System.Windows.Forms.dll", "/out:" + str(destination / "AiClimbing.exe"),
                    str(PROJECT / "desktop/AiClimbing.cs")], check=True)
    assert_local_package(destination)
    inventory.append({"name": "CPython", "version": sys.version.split()[0], "source": "CPython Windows runtime", "license": "PSF"})
    inventory.append({"name": "Detectron2", "version": "0.6+a2f4a877/windows-cp312-cpu", "source": "Existing compiled source", "license": "Apache-2.0"})
    (destination / "dependencies.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(lock, destination / "dependencies.lock.json")
    critical = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            critical.append({"path": path.relative_to(destination).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    # Full audit is retained; startup hashes the native model and core resources.
    (destination / "file-manifest.json").write_text(json.dumps(critical, indent=2), encoding="utf-8")
    important = [r for r in critical if r["path"].endswith(("verified-model_final.pth", "rtmw.onnx", "detector.onnx", "manifest.json", "index.html", "python312.dll", "_C.cp312-win_amd64.pyd", "NotoSansSC-VF.ttf"))]
    (destination / "resources.json").write_text(json.dumps({"critical": important}, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(destination), "files": len(critical), "bytes": sum(x["bytes"] for x in critical), "dependencies": len(versions)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--site", type=Path, action="append", required=True)
    parser.add_argument("--detectron", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--write-lock", action="store_true")
    build(parser.parse_args())
