#!/usr/bin/env python3
"""localhost-radar — shows every TCP port currently listening on this machine.

The problem: dev servers, Docker containers, or a stray `python -m http.server`
keep running after you've forgotten about them, or you want to open a project's
portal and don't remember which port it landed on. This scans every listening
TCP socket (no filtering to "known" dev runtimes — that would miss exactly the
forgotten Docker DB it's meant to catch) and maps each one back to the process
and, where resolvable, the project directory it's running from.

Every port is classified as "app" (a local web app you run: answers HTTP with
HTML and runs from a project directory or a Docker container) or "program"
(background services of installed apps, IDE/CLI helper sockets, …). The scan
itself stays unfiltered; the classification only drives what displays show.

Writes state.json (machine-readable) and reports/latest.md (human-readable).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_PATH = HERE / "state.json"
REPORT_PATH = HERE / "reports" / "latest.md"

LOOPBACK_ADDRS = {"127.0.0.1", "::1", "localhost"}

# macOS system daemons that are always listening and never dev-relevant.
# Additive via RADAR_EXCLUDE_COMMANDS (comma-separated) — this is a denylist,
# not a filter down to "known" dev runtimes, so unexpected listeners still show up.
DEFAULT_EXCLUDE_COMMANDS = {
    "rapportd", "controlcenter", "identityservicesd", "sharingd",
    "airplayxpchelper", "bluetoothd", "cloudd", "trustd", "mdnsresponder",
}


def run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 1, ""


def exclude_set() -> set[str]:
    extra = os.environ.get("RADAR_EXCLUDE_COMMANDS", "")
    extra_names = {c.strip().lower() for c in extra.split(",") if c.strip()}
    return DEFAULT_EXCLUDE_COMMANDS | extra_names


def parse_name(name: str) -> tuple[str | None, int | None]:
    """'*:3000' / '127.0.0.1:5432' / '[::1]:8080' -> (addr, port)."""
    if ":" not in name:
        return None, None
    addr, _, port = name.rpartition(":")
    addr = addr.strip("[]")
    if not port.isdigit():
        return None, None
    return addr, int(port)


def raw_listeners() -> list[dict]:
    """One record per listening socket, via lsof's stable field-output mode."""
    rc, out = run(["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n", "-F", "pcLnf"])
    if not out:
        return []
    records = []
    pid = command = login = None
    for line in out.splitlines():
        if not line:
            continue
        tag, val = line[0], line[1:]
        if tag == "p":
            pid, command, login = int(val), None, None
        elif tag == "c":
            command = val
        elif tag == "L":
            login = val
        elif tag == "n":
            addr, port = parse_name(val)
            if port is not None:
                records.append({"pid": pid, "command": command, "user": login,
                                 "addr": addr, "port": port})
    return records


def cwd_for_pid(pid: int) -> str | None:
    # Race possible: the process may exit between the two lsof calls.
    rc, out = run(["lsof", "-a", "-d", "cwd", "-p", str(pid), "-F", "n"])
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def docker_ports() -> dict[int, str]:
    """Host port -> project dir of the container publishing it (Docker/OrbStack).

    The listening process is the VM helper (cwd "/"), so the project comes from the
    compose working dir, lifted to its git toplevel (compose files often sit in a
    `deployment/` subfolder).
    """
    fmt = '{{.Ports}}\t{{.Label "com.docker.compose.project.working_dir"}}\t{{.Names}}'
    rc, out = run(["docker", "ps", "--format", fmt], timeout=5)
    mapping: dict[int, str] = {}
    for line in out.splitlines():
        ports, workdir, name = (line.split("\t") + ["", ""])[:3]
        project = workdir or name
        if workdir:
            rc2, top = run(["git", "-C", workdir, "rev-parse", "--show-toplevel"], timeout=5)
            project = top.strip() if rc2 == 0 and top.strip() else workdir
        for host_port in re.findall(r":(\d+)->", ports):
            mapping[int(host_port)] = project
    return mapping


def serves_html(port: int) -> bool:
    """True if GET / answers with an HTML page (any status) — i.e. a web UI, not an API/IPC socket."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"User-Agent": "localhost-radar"})
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            ctype = resp.headers.get("Content-Type") or ""
    except urllib.error.HTTPError as e:
        ctype = e.headers.get("Content-Type") or ""
    except Exception:
        return False
    return ctype.lower().startswith("text/html")


def is_project_dir(cwd: str | None) -> bool:
    """A real working directory — not "/" (menu bar agents) and not inside an .app bundle."""
    return bool(cwd) and cwd != "/" and ".app/" not in cwd + "/"


def bind_kind(addr: str) -> str:
    if addr in LOOPBACK_ADDRS or addr.startswith("127."):
        return "loopback"
    return "exposed"  # "*", "0.0.0.0", "::", or a real interface IP


def check() -> dict:
    excluded = exclude_set()
    seen: dict[tuple[int, int], dict] = {}
    cwd_cache: dict[int, str | None] = {}

    for rec in raw_listeners():
        command = rec["command"] or ""
        if command.lower() in excluded:
            continue
        key = (rec["pid"], rec["port"])
        if key in seen:
            continue  # same port bound on both IPv4 and IPv6

        pid = rec["pid"]
        if pid not in cwd_cache:
            cwd_cache[pid] = cwd_for_pid(pid)
        cwd = cwd_cache[pid]
        # cwd="/" (common for menu bar / background agents) has no useful basename.
        project = Path(cwd).name if cwd and cwd != "/" else None

        seen[key] = {
            "port": rec["port"],
            "pid": pid,
            "command": command,
            "user": rec["user"],
            "bind": bind_kind(rec["addr"] or ""),
            "cwd": cwd,
            "project": project,
        }

    docker = docker_ports()
    for e in seen.values():
        if e["port"] in docker:
            e["cwd"] = docker[e["port"]]
            e["project"] = Path(docker[e["port"]]).name
            e["docker"] = True
    with ThreadPoolExecutor(max_workers=16) as pool:
        html = dict(zip(seen, pool.map(lambda e: serves_html(e["port"]), seen.values())))
    for key, e in seen.items():
        e["kind"] = "app" if html[key] and is_project_dir(e["cwd"]) else "program"

    ports = sorted(seen.values(), key=lambda e: e["port"])
    # Only apps count: an exposed helper socket of an installed program is not actionable.
    severity = "orange" if any(e["bind"] == "exposed" and e["kind"] == "app" for e in ports) else "green"

    return {
        "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "severity": severity,
        "count": len(ports),
        "app_count": sum(1 for e in ports if e["kind"] == "app"),
        "ports": ports,
    }


def render_report(state: dict) -> str:
    lines = [f"# localhost-radar — {state['generated']}", "",
             f"**{state['count']} Ports lauschen aktuell, davon {state['app_count']} Apps.**", ""]
    if not state["ports"]:
        lines.append("_(keine)_")
        return "\n".join(lines) + "\n"
    lines.append("| Port | Art | Projekt | Kommando | Bind | PID |")
    lines.append("|---|---|---|---|---|---|")
    for e in state["ports"]:
        bind_mark = "🌐 exposed" if e["bind"] == "exposed" else "🏠 loopback"
        lines.append(f"| {e['port']} | {e['kind']} | {e['project'] or '—'} | {e['command']} | "
                      f"{bind_mark} | {e['pid']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    state = check()
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(render_report(state), encoding="utf-8")
    exposed = sum(1 for e in state["ports"] if e["bind"] == "exposed")
    print(f"count={state['count']} apps={state['app_count']} exposed={exposed}")


if __name__ == "__main__":
    main()
