# ansible_runner.py
import os, json, shlex, subprocess, sys, tempfile

BASE = os.path.abspath(os.path.dirname(__file__))
PLAYBOOKS_DIR = os.path.join(BASE, "playbooks")

def _venv_bin():
    # Prefer the Python actually running this process
    exe = sys.executable
    vbin = os.path.dirname(exe)
    return vbin

def run_playbook(playbook_path, inventory=None, extra_vars=None, output_dir=None, timeout=1800):
    playbook_path = os.path.abspath(playbook_path)
    workdir = os.path.dirname(playbook_path) or PLAYBOOKS_DIR
    output_dir = os.path.abspath(output_dir or os.path.join(BASE, "outputs"))
    os.makedirs(output_dir, exist_ok=True)

    # Build env that mirrors your working CLI environment
    env = os.environ.copy()
    vbin = _venv_bin()
    env.setdefault("VIRTUAL_ENV", os.path.dirname(vbin))
    env["PATH"] = f"{vbin}:{env.get('PATH','')}"
    env.setdefault("ANSIBLE_CONFIG", os.path.join(PLAYBOOKS_DIR, "ansible.cfg"))
    # Your collections live here:
    env.setdefault("ANSIBLE_COLLECTIONS_PATHS", "/home/rothakur/dev-workspace/ansible_collections")
    env.setdefault("ANSIBLE_PYTHON_INTERPRETER", sys.executable)

    ansible_playbook = os.path.join(vbin, "ansible-playbook")

    extra_vars_path = None
    extra = extra_vars or {}
    if extra:
        fd, extra_vars_path = tempfile.mkstemp(prefix="extra_vars_", suffix=".json", dir=output_dir)
        os.write(fd, json.dumps(extra).encode("utf-8"))
        os.close(fd)

    cmd = [ansible_playbook, playbook_path]
    if inventory:
        cmd += ["-i", inventory]
    if extra_vars_path:
        cmd += ["-e", f"@{extra_vars_path}"]

    # Ensure timeout is an int (fixes the `'float' object cannot be interpreted as an integer` crash)
    tmo = int(timeout)

    proc = subprocess.run(
        cmd,
        cwd=workdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=tmo,
    )

    res = {
        "command": " ".join(shlex.quote(c) for c in cmd),
        "rc": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "workdir": workdir,
        "output_dir": output_dir,
        "ansible_playbook": ansible_playbook,
        "python": sys.executable,
        # helpful for debugging
        "env_debug": {
            "VIRTUAL_ENV": env.get("VIRTUAL_ENV"),
            "ANSIBLE_CONFIG": env.get("ANSIBLE_CONFIG"),
            "ANSIBLE_COLLECTIONS_PATHS": env.get("ANSIBLE_COLLECTIONS_PATHS"),
            "PATH_head": env.get("PATH","").split(":")[:3],
        },
        "extra_vars_path": extra_vars_path,
    }
    return res
