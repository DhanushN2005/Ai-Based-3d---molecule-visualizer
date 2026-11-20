import glob
import logging
import os
import shutil
import subprocess

log = logging.getLogger("chemverse")


def find_blender():
    """Locate blender.exe.

    Order: BLENDER_PATH env var -> `blender` on PATH -> newest install under
    C:\\Program Files\\Blender Foundation.
    """
    env = os.environ.get("BLENDER_PATH")
    if env and os.path.isfile(env):
        return env

    on_path = shutil.which("blender")
    if on_path:
        return on_path

    pattern = r"C:\Program Files\Blender Foundation\Blender *\blender.exe"
    installs = glob.glob(pattern)

    def version_key(path):
        folder = os.path.basename(os.path.dirname(path))  # "Blender 4.4"
        try:
            return tuple(int(p) for p in folder.split()[-1].split("."))
        except ValueError:
            return (0,)

    if installs:
        return max(installs, key=version_key)

    raise FileNotFoundError(
        "Blender not found. Install it or set the BLENDER_PATH environment "
        "variable to the full path of blender.exe."
    )


# Blender calling
def run_blender_script(script_path):
    cmd = [
        find_blender(),
        "--background",
        "--python",
        os.path.abspath(script_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        log.info("Blender finished: %s", result.stdout.strip()[-300:])
        if result.stderr:
            log.warning("Blender stderr: %s", result.stderr.strip()[-300:])
    except subprocess.CalledProcessError as e:
        log.error("Blender failed. stdout: %s | stderr: %s", (e.stdout or "")[-300:], (e.stderr or "")[-300:])
        raise  # Let it bubble up to the main app for full traceback
