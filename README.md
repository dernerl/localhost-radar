# localhost-radar

Shows every TCP port currently listening on this machine, and which project
(if any) it belongs to — for the moment you've forgotten a dev server is still
running, or want to open a project's local URL and can't remember the port.

## The problem

Dev servers, Docker containers, or a stray `python -m http.server` keep
running long after you've moved on. Tools like
[Overmind](https://github.com/DarthSim/overmind) that start several dev
servers from one central `Procfile` only track processes started through
that `Procfile` — anything started ad hoc (a database container, a one-off
server in some other repo) stays invisible to that view.

`localhost-radar` doesn't care how a process was started. It scans **every**
listening TCP socket via `lsof`, deliberately unfiltered to known dev
runtimes — a filtered view would miss exactly the forgotten Docker DB it's
meant to catch — and resolves each one back to the owning process and, where
resolvable, its working directory.

## What gets checked

- Every listening TCP socket (`lsof -iTCP -sTCP:LISTEN`), deduplicated across
  IPv4/IPv6 dual-stack binds on the same port.
- Owning process: PID, command, user.
- Working directory of the process (`lsof -d cwd`), and the last path
  component of it as a friendly project label — no attempt to parse a
  Procfile or match against a list of known project roots, see
  [ADR 0001](docs/adr/0001-standalone-repo-und-voller-port-scan.md).
- **Bind scope**: `loopback` (127.0.0.1/::1 — only this machine can reach it)
  vs. `exposed` (`*`, `0.0.0.0`, or a real interface IP — reachable from the
  LAN). A dev server exposed beyond loopback is worth a second look.

A small built-in denylist filters out macOS system daemons that are always
listening and never dev-relevant (`rapportd`, `ControlCenter`, `mDNSResponder`,
…). It's a denylist, not an allowlist — everything else still shows up.

## Usage

```sh
python3 localhost_radar.py
# count=8 exposed=3
```

Writes two files next to the script:

- `state.json` — machine-readable, for further processing
- `reports/latest.md` — human-readable report

No dependencies beyond Python 3.10+ (`X | None` syntax) and `lsof` (built
into macOS). No sudo needed — `lsof` sees your own processes without it.

### Configuration

To exclude additional noisy background apps (Spotify Connect, sync clients,
…), extend the built-in denylist:

```sh
RADAR_EXCLUDE_COMMANDS="Spotify,OneDrive Sync Service" python3 localhost_radar.py
```

Comma-separated, case-insensitive, matched against the process command name.
Additive — it extends the built-in list, it doesn't replace it.

## Menu bar

The SwiftBar display deliberately lives in its own repo:
[dernerl/swiftbar-plugins](https://github.com/dernerl/swiftbar-plugins). It
reads `state.json` and is entirely optional — this tool runs on its own.
Clicking a port entry there opens `http://localhost:<port>` directly.

## License

MIT — see [LICENSE](LICENSE).
