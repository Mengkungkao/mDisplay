"""mDisplay's requirements, fetched without root when the system lacks them.

mFruit OS installs apps as the normal user and never with sudo (its ADR 0011),
so the system packages mDisplay needs — SDL2, NumPy, Pillow — cannot be
installed system-wide by the app. When one is missing, this module fetches it
the way apt would, but into mDisplay's own data folder:

  1. ``apt-cache depends --recurse`` lists the package and everything it needs;
     ``dpkg-query`` keeps only what this system does not have;
  2. ``apt-get download`` (no root needed) fetches those .deb files from the
     system's own configured sources; apt checks each against the signed
     package lists, as for a normal install;
  3. ``dpkg-deb -x`` unpacks them under ``<data>/sysroot`` (built beside it and
     swapped in only when complete);
  4. ``<data>/sysroot/env.sh`` exports the library and Python paths, which
     ``run.sh`` and ``test.sh`` source before starting Python.

Nothing outside the data folder changes; "Delete data" removes it all.
For NumPy, a pip venv in the data folder remains the fallback when apt cannot
provide it. Usage (install.sh calls it)::

    python3 -m app.deps ensure --data DIR     fetch what is missing; exit 1 if still missing
    python3 -m app.deps check --data DIR      report only
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = (
    # (name, Debian package, check run with the candidate environment)
    ("SDL2", "libsdl2-2.0-0", "from app.display.sdl2 import SDL; print(SDL().version_text)"),
    ("NumPy", "python3-numpy", "import numpy; print(numpy.__version__)"),
    ("Pillow", "python3-pil", "import PIL, sys; v = tuple(int(x) for x in PIL.__version__.split('.')[:2]);"
                               " sys.exit('Pillow ' + PIL.__version__ + ' is older than 9.0')"
                               " if v < (9, 0) else print(PIL.__version__)"),
)
SKIP_DEPENDS = ("--no-recommends", "--no-suggests", "--no-conflicts", "--no-breaks",
                "--no-replaces", "--no-enhances", "--no-pre-depends")
TIMEOUT = 600


def say(message: str) -> None:
    print(f"mdisplay: {message}", flush=True)


def sysroot(data: str) -> str:
    return os.path.join(data, "sysroot")


def env_file(data: str) -> str:
    return os.path.join(sysroot(data), "env.sh")


def environment(data: str, base=None) -> dict:
    """The environment run.sh gives Python: the base one plus the sysroot's paths."""
    env = dict(os.environ if base is None else base)
    info_path = os.path.join(sysroot(data), "paths.json")
    try:
        with open(info_path) as handle:
            info = json.load(handle)
    except (OSError, ValueError):
        return env
    for key, values in (("LD_LIBRARY_PATH", info.get("lib_dirs", [])),
                        ("PYTHONPATH", info.get("python_dirs", []))):
        if values:
            env[key] = os.pathsep.join(values + ([env[key]] if env.get(key) else []))
    if info.get("sdl2"):
        env["MDISPLAY_SDL2"] = info["sdl2"]
    return env


def python_for(data: str) -> str:
    """The interpreter run.sh uses: the data folder's venv when install.sh made one."""
    venv = os.path.join(data, "venv", "bin", "python")
    return venv if os.access(venv, os.X_OK) else sys.executable


def check(code: str, env: dict, python: str = sys.executable) -> tuple:
    """(ok, output) of a requirement check in a fresh Python with ``env``."""
    try:
        result = subprocess.run([python, "-c", code], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr).strip().splitlines()
    return result.returncode == 0, output[-1] if output else ""


def missing(data: str) -> list:
    """[(name, package, why)] for requirements that do not load, sysroot included."""
    env = environment(data)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    absent = []
    python = python_for(data)
    for name, package, code in REQUIREMENTS:
        ok, output = check(code, env, python)
        if not ok:
            absent.append((name, package, output))
    return absent


def run(command: list, cwd: str = None, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    env = dict(os.environ, LC_ALL="C")
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def installed(packages: list) -> set:
    if not packages:
        return set()
    result = run(["dpkg-query", "-W", "-f=${Package} ${Status}\\n", *packages], timeout=60)
    return {line.split()[0].split(":")[0] for line in result.stdout.splitlines()
            if line.endswith(" installed")}


def closure(packages: list) -> list:
    """The packages and everything they depend on (real packages only)."""
    result = run(["apt-cache", "depends", "--recurse", *SKIP_DEPENDS, *packages], timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"apt-cache: {(result.stderr or result.stdout).strip()[:300]}")
    names = []
    for line in result.stdout.splitlines():
        if line and not line.startswith((" ", "<")):
            name = line.strip().split(":")[0]
            if name not in names:
                names.append(name)
    return names


def fetch(data: str, packages: list) -> list:
    """Download and unpack ``packages`` and their missing dependencies under data/sysroot.
    Returns the packages unpacked. Raises RuntimeError with a readable reason."""
    for tool in ("apt-cache", "apt-get", "dpkg-query", "dpkg-deb"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is not available (not a Debian-based system?)")
    wanted = closure(packages)
    have = installed(wanted)
    needed = [p for p in wanted if p not in have]
    if not needed:
        return []
    os.makedirs(data, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".sysroot-", dir=data)
    try:
        debs = os.path.join(work, "debs")
        os.makedirs(debs)
        say(f"downloading {len(needed)} package(s) from this system's apt sources: "
            + " ".join(needed))
        result = run(["apt-get", "download", *needed], cwd=debs)
        if result.returncode != 0:
            reason = (result.stderr or result.stdout).strip().splitlines()
            raise RuntimeError("apt-get download failed: " + (reason[-1] if reason else "unknown")
                               + " (no network, or the package lists are out of date)")
        staged = os.path.join(work, "sysroot")
        old = sysroot(data)
        if os.path.isdir(old):                  # keep what an earlier install fetched
            shutil.copytree(old, staged, symlinks=True)
        else:
            os.makedirs(staged)
        for deb in sorted(glob.glob(os.path.join(debs, "*.deb"))):
            result = run(["dpkg-deb", "-x", deb, staged], timeout=120)
            if result.returncode != 0:
                raise RuntimeError(f"cannot unpack {os.path.basename(deb)}: {result.stderr.strip()}")
        _write_paths(staged, sorted(set(needed) | set(_previous(old))), final=old)
        if os.path.isdir(old):
            shutil.rmtree(old)
        os.replace(staged, old)
        return needed
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _previous(root: str) -> list:
    try:
        with open(os.path.join(root, "paths.json")) as handle:
            return json.load(handle).get("packages", [])
    except (OSError, ValueError):
        return []


def _write_paths(root: str, packages: list, final: str) -> None:
    """Record the library and Python folders of ``root`` as they will be at ``final``
    (the staged folder is renamed into place afterwards)."""
    lib_dirs, python_dirs, sdl2 = [], [], ""

    def placed(path: str) -> str:
        return os.path.join(final, os.path.relpath(path, root))
    for folder, _dirs, files in os.walk(root):
        if any(".so" in name for name in files):
            lib_dirs.append(placed(folder))
        base = os.path.basename(folder)
        if base in ("dist-packages", "site-packages") and placed(folder) not in python_dirs:
            python_dirs.append(placed(folder))
        for name in files:
            if name == "libSDL2-2.0.so.0":
                sdl2 = placed(os.path.join(folder, name))
    # Libraries live in .../lib/<triplet>; BLAS/LAPACK in subfolders (alternatives).
    lib_dirs = [d for d in lib_dirs if "/python" not in d] or lib_dirs
    info = {"packages": packages, "lib_dirs": lib_dirs, "python_dirs": python_dirs, "sdl2": sdl2}
    with open(os.path.join(root, "paths.json"), "w") as handle:
        json.dump(info, handle, indent=1)
    lines = ["# Written by mDisplay's install.sh (app/deps.py): packages unpacked here, not system-wide."]
    if lib_dirs:
        lines.append("export LD_LIBRARY_PATH=" + shlex.quote(os.pathsep.join(lib_dirs))
                     + '"${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"')
    if python_dirs:
        lines.append("export PYTHONPATH=" + shlex.quote(os.pathsep.join(python_dirs))
                     + '"${PYTHONPATH:+:$PYTHONPATH}"')
    if sdl2:
        lines.append("export MDISPLAY_SDL2=" + shlex.quote(sdl2))
    with open(os.path.join(root, "env.sh"), "w") as handle:
        handle.write("\n".join(lines) + "\n")


def pip_numpy(data: str) -> bool:
    """Fallback: NumPy from pip into a venv in the data folder."""
    venv = os.path.join(data, "venv")
    python = os.path.join(venv, "bin", "python")
    if not os.path.exists(python):
        if run([sys.executable, "-m", "venv", "--system-site-packages", venv]).returncode != 0:
            return False
    result = run([python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                  "--no-input", "--timeout", "60", "numpy>=1.21"])
    return result.returncode == 0


def ensure(data: str, allow_pip: bool = True) -> int:
    absent = missing(data)
    if not absent:
        return 0
    say("missing: " + ", ".join(f"{name} ({package})" for name, package, _ in absent))
    try:
        unpacked = fetch(data, [package for _, package, _ in absent])
        if unpacked:
            say(f"unpacked into {sysroot(data)}: " + " ".join(unpacked))
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        say(f"could not fetch them without root: {exc}")
    absent = missing(data)
    if any(name == "NumPy" for name, _, _ in absent) and allow_pip:
        say("trying NumPy from pip instead")
        if pip_numpy(data):
            absent = missing(data)
    if absent:
        packages = " ".join(package for _, package, _ in absent)
        for name, _package, why in absent:
            say(f"{name} still missing ({why})")
        say(f"install them once with: sudo apt-get install {packages}")
        say("(on mFruit OS: bash ~/.whisplay-os/system/current/scripts/setup-app.sh mdisplay)")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("ensure", "check"))
    parser.add_argument("--data", required=True)
    parser.add_argument("--no-pip", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "check":
        absent = missing(args.data)
        for name, package, why in absent:
            say(f"missing {name} ({package}): {why}")
        return 1 if absent else 0
    return ensure(args.data, not args.no_pip)


if __name__ == "__main__":
    sys.exit(main())
