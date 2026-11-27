"""Check the built image, then start it the way the platform's cluster will, without a network (D28).

uv run python scripts/check_image.py [--image ticket-triage:local] [--timeout 240]

Image (docker image inspect, and python3 inside it):
- user 10001:10001, port 8080, ASPNETCORE_URLS on 8080;
- the app's packages under .python_packages (Python 3.13 dependency isolation), the app itself, no local settings;
- the two lab tools in /opt/triage-lab, and python3 runs them.
Host (one container: --network none, --user 10001:10001, all capabilities dropped, no new privileges; host keys as
files, read-only, AzureWebJobsSecretStorageType=kubernetes, the platform's D9):
- GET /api/health answers 200: the Python worker started and indexed the app (no exit 139);
- GET /admin/functions with the master key lists exactly the functions function_app.py registers;
- POST /api/tickets without a key: 401; GET /api/queue-depth with the KEDA host key: 503 (authorised; the queue
  can't be reached without a network);
- the host log has no "exited with code" line.
No network on purpose: a host that downloads something at start would fail here, not as a pod that never gets
ready behind the cluster's default deny. Every line OK or FAIL; exit 1 on any FAIL. The container is removed.
"""

import argparse
import importlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER = "10001:10001"
NAME = "triage-image-check"
SITE = "/home/site/wwwroot/.python_packages/lib/site-packages"
# Settings the host needs to index the app (values that go nowhere: there is no network).
SETTINGS = {
    "AzureWebJobsSecretStorageType": "kubernetes",
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "ServiceBusConnection": (
        "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;"
        "UseDevelopmentEmulator=true;"
    ),
    "TICKETS_QUEUE": "tickets",
    "QUEUE_DEPTH_ENDPOINT": "true",
}
PROBE = f"""
import json, os
site = {SITE!r}
print(json.dumps({{
    "uid": os.getuid(), "gid": os.getgid(),
    "packages": sorted(n for n in os.listdir(site) if not n.endswith(".dist-info")),
    "app": sorted(os.listdir("/home/site/wwwroot")),
    "lab": sorted(os.listdir("/opt/triage-lab")),
    "home_owner": os.stat("/home").st_uid,
}}))
"""
REQUEST = """
import os, sys, urllib.error, urllib.request
method, path = sys.argv[1:3]
headers = {"x-functions-key": os.environ["KEY"]} if os.environ.get("KEY") else {}
body = b"{}" if method == "POST" else None
request = urllib.request.Request("http://127.0.0.1:8080" + path, data=body, method=method, headers=headers)
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        print(response.status); print(response.read().decode())
except urllib.error.HTTPError as error:
    print(error.code); print(error.read().decode()[:200])
except OSError as error:
    print(0); print(type(error).__name__ + " (no HTTP answer)")
"""


def expected_functions() -> list[str]:
    """What function_app.py registers with the settings above (so this check follows the code)."""
    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    saved = os.environ.get("QUEUE_DEPTH_ENDPOINT")
    os.environ["QUEUE_DEPTH_ENDPOINT"] = SETTINGS["QUEUE_DEPTH_ENDPOINT"]
    try:
        import function_app

        app = importlib.reload(function_app).app
    finally:
        if saved is None:
            os.environ.pop("QUEUE_DEPTH_ENDPOINT")
        else:
            os.environ["QUEUE_DEPTH_ENDPOINT"] = saved
    return sorted(f.get_function_name() for f in app.get_functions())


def host_keys(functions: list[str]) -> dict[str, str]:
    """The key files the host reads (KubernetesSecretsRepository, file mode): host, KEDA's, system, per function."""
    names = ["host.master", "host.function.default", "host.function.keda", "host.systemKey.eventgrid_extension"]
    names += [f"functions.{f.lower()}.default" for f in functions]
    return {name: secrets.token_urlsafe(32) for name in names}


def docker(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False, env=env)  # noqa: S603, S607


def line(ok: bool, what: str, seen: str) -> str:
    return f"{'OK  ' if ok else 'FAIL'} {what}: {seen}"


def check_image(image: str) -> list[str]:
    inspected = docker("image", "inspect", image, "--format", "{{json .Config}}")
    if inspected.returncode != 0:
        return [line(False, "image", inspected.stderr.strip()[-200:])]
    config = json.loads(inspected.stdout)
    env = dict(item.split("=", 1) for item in config.get("Env") or [])
    lines = [
        line(config.get("User") == USER, "configured user", config.get("User") or "root"),
        line(
            "8080/tcp" in (config.get("ExposedPorts") or {}),
            "exposed port",
            ", ".join(config.get("ExposedPorts") or {}),
        ),
        line(env.get("ASPNETCORE_URLS") == "http://+:8080", "host listens on", env.get("ASPNETCORE_URLS", "unset")),
    ]
    probe = docker("run", "--rm", "--network", "none", "--entrypoint", "python3", image, "-c", PROBE)
    if probe.returncode != 0:
        return [*lines, line(False, "probe inside the image", probe.stderr.strip()[-200:])]
    seen = json.loads(probe.stdout)
    packages = set(seen["packages"])
    lines += [
        line(f"{seen['uid']}:{seen['gid']}" == USER, "a process runs as", f"{seen['uid']}:{seen['gid']}"),
        line(
            {"azure", "openai", "pydantic"} <= packages,
            "app packages in .python_packages",
            f"{len(packages)} top-level",
        ),
        line("function_app.py" in seen["app"] and "triage" in seen["app"], "app in wwwroot", ", ".join(seen["app"])),
        line(
            not any(n.startswith(("local.settings", "azure.settings")) for n in seen["app"]),
            "no settings files",
            "none",
        ),
        line(seen["lab"] == ["eventgrid_stub.py", "fake_llm.py"], "lab tools", ", ".join(seen["lab"])),
        line(seen["home_owner"] == 10001, "/home owned by", str(seen["home_owner"])),
    ]
    for tool in ("fake_llm.py", "eventgrid_stub.py"):
        ran = docker(
            "run", "--rm", "--network", "none", "--entrypoint", "python3", image, f"/opt/triage-lab/{tool}", "--help"
        )
        lines.append(
            line(ran.returncode == 0 and "--host" in ran.stdout, f"python3 {tool} --help", f"exit {ran.returncode}")
        )
    return lines


def request(method: str, path: str, key: str | None = None) -> tuple[int, str]:
    env = {**os.environ, "KEY": key or ""}
    result = docker("exec", "-e", "KEY", NAME, "python3", "-c", REQUEST, method, path, env=env)
    status, _, body = result.stdout.partition("\n")
    return (int(status) if status.strip().isdigit() else 0), body.strip()


def check_host(image: str, timeout: float) -> list[str]:
    functions = expected_functions()
    keys = host_keys(functions)
    with tempfile.TemporaryDirectory(prefix="triage-keys-") as tmp:
        folder = Path(tmp)
        folder.chmod(0o755)
        for name, value in keys.items():
            (folder / name).write_text(value, encoding="utf-8")
            (folder / name).chmod(0o644)
        docker("rm", "-f", NAME)
        args = ["run", "-d", "--name", NAME, "--network", "none", "--user", USER, "--cap-drop", "ALL"]
        args += ["--security-opt", "no-new-privileges", "-v", f"{folder}:/run/secrets/functions-keys:ro"]
        for name, value in SETTINGS.items():
            args += ["-e", f"{name}={value}"]
        started = docker(*args, image)
        if started.returncode != 0:
            return [line(False, "host container started", started.stderr.strip()[-200:])]
        try:
            deadline = time.monotonic() + timeout
            status, waited = 0, time.monotonic()
            while time.monotonic() < deadline:
                status, _ = request("GET", "/api/health")
                if status == 200:
                    break
                time.sleep(3)
            lines = [line(status == 200, "GET /api/health", f"{status} after {time.monotonic() - waited:.0f} s")]
            status, body = request("GET", "/admin/functions", keys["host.master"])
            listed = sorted(f["name"] for f in json.loads(body)) if status == 200 else []
            lines.append(line(listed == functions, "functions loaded", ", ".join(listed) or f"HTTP {status}"))
            status, _ = request("POST", "/api/tickets")
            lines.append(line(status == 401, "POST /api/tickets without a key", str(status)))
            began = time.monotonic()
            status, body = request("GET", "/api/queue-depth", keys["host.function.keda"])
            took = time.monotonic() - began
            seen = f"{status} in {took:.1f} s" if status else f"{body} after {took:.0f} s"
            # 503 = authorised and the queue unreachable (no network); quickly, because KEDA waits only 3 s
            ok = status == 503 and took < 10
            lines.append(line(ok, "GET /api/queue-depth with the KEDA host key", seen))
            logs = docker("logs", NAME)
            text = logs.stdout + logs.stderr
            crashed = [entry for entry in text.splitlines() if "exited with code" in entry]
            lines.append(line(not crashed, "worker never exited", crashed[0][-160:] if crashed else "no exit"))
            if any(entry.startswith("FAIL") for entry in lines):
                lines += ["--- last 40 log lines ---", *text.splitlines()[-40:]]
            return lines
        finally:
            docker("rm", "-f", NAME)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", default="ticket-triage:local")
    parser.add_argument("--timeout", type=float, default=240, help="seconds to wait for the host (default 240)")
    args = parser.parse_args()
    lines = check_image(args.image)
    print("\n".join(lines), flush=True)
    if not any(entry.startswith("FAIL") for entry in lines):
        host = check_host(args.image, args.timeout)
        print("\n".join(host))
        lines += host
    failures = sum(entry.startswith("FAIL") for entry in lines)
    print(f"FAIL {failures} check(s)" if failures else "IMAGE CHECKS PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
