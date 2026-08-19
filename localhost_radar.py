#!/usr/bin/env python3
"""localhost-radar — shows every TCP port currently listening on this machine.

The problem: dev servers, Docker containers, or a stray `python -m http.server`
keep running after you've forgotten about them, or you want to open a project's
portal and don't remember which port it landed on. This scans every listening
TCP socket (no filtering to "known" dev runtimes — that would miss exactly the
forgotten Docker DB it's meant to catch) and maps each one back to the process
and, where resolvable, the project directory it's running from.

Writes state.json (machine-readable) and reports/latest.md (human-readable).
"""
import json
import os
import re
import subprocess
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

    ports = sorted(seen.values(), key=lambda e: e["port"])
    severity = "orange" if any(e["bind"] == "exposed" for e in ports) else "green"

    return {
        "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "severity": severity,
        "count": len(ports),
        "ports": ports,
    }


def render_report(state: dict) -> str:
    lines = [f"# localhost-radar — {state['generated']}", "",
             f"**{state['count']} Ports lauschen aktuell.**", ""]
    if not state["ports"]:
        lines.append("_(keine)_")
        return "\n".join(lines) + "\n"
    lines.append("| Port | Projekt | Kommando | Bind | PID |")
    lines.append("|---|---|---|---|---|")
    for e in state["ports"]:
        bind_mark = "🌐 exposed" if e["bind"] == "exposed" else "🏠 loopback"
        lines.append(f"| {e['port']} | {e['project'] or '—'} | {e['command']} | "
                      f"{bind_mark} | {e['pid']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    state = check()
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(render_report(state), encoding="utf-8")
    exposed = sum(1 for e in state["ports"] if e["bind"] == "exposed")
    print(f"count={state['count']} exposed={exposed}")


if __name__ == "__main__":
    main()
