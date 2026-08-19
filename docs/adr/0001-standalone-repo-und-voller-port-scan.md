# 1. Standalone repo, full unfiltered port scan, cwd-basename project labels

Date: 2026-08-19

## Status

Accepted.

## Context

The recurring problem: a dev server (or a database container, or a one-off
`http.server`) keeps listening long after it's been forgotten about, and
there's no quick way to see what's currently bound to which port — or to
open a project's local URL without first digging up the port number.

An existing Overmind/Procfile setup already starts several named dev servers
from one central `Procfile`, but it only tracks processes it started itself;
anything launched ad hoc elsewhere is invisible to it. Three design questions
came up while scoping this:

1. Does this belong in an existing repo, or does it need its own?
2. Scan every listening port, or filter down to processes that look like dev
   servers (node, python, ruby, …)?
3. How to label a port with a project name — parse the Procfile, match
   against known project roots (as `azure-token-watchdog` does for its
   isolated Azure contexts), or something simpler?

## Decision

- **Standalone repo (`localhost-radar`)**, not folded into `workbench-janitor`
  or the Overmind docs. Mirrors the existing split between
  `azure-token-watchdog` and `workbench-janitor`: each tool is a small,
  independently runnable script with its own `state.json` contract; the
  SwiftBar display in `dernerl/swiftbar-plugins` is the only thing that knows
  about more than one of them.
- **Full, unfiltered port scan** (`lsof -iTCP -sTCP:LISTEN`) rather than a
  filter on known dev-server commands. A curated allowlist would reliably
  miss the case that actually matters — a database container or some other
  non-"dev-shaped" process left running on a port. Noise is handled the
  other way round: a small denylist of macOS system daemons that are always
  listening and never relevant, extensible via `RADAR_EXCLUDE_COMMANDS`.
- **Project label = `cwd` basename**, not Procfile parsing or root-matching.
  `lsof -d cwd` already gives the process's working directory for free; the
  last path component is a good-enough label for a menu bar dropdown, and
  the full `cwd` stays in `state.json` for anything that needs more. This
  intentionally skips the more thorough approach `azure-token-watchdog` uses
  (matching against known project roots via `.claude/settings.local.json`)
  — that machinery exists there because it disambiguates isolated Azure
  contexts, which need to be pinned to a specific project; here, port + cwd
  is already unambiguous, so there's nothing to disambiguate.

## Consequences

- Follows the same contract every sibling tool follows: `state.json` +
  `reports/latest.md`, no dependency on SwiftBar to be useful standalone.
- The unfiltered scan means genuinely irrelevant background apps (a sync
  client, a media app's discovery socket) show up until denylisted — an
  intentional tradeoff of some noise in exchange for never silently hiding
  an unexpected listener.
- The cwd-basename label is occasionally uninformative (nested repos like
  `DERNERLS-AI-TEAM/paperclip` label as `paperclip`, and process with no
  resolvable cwd, or `cwd=/` as menu bar agents often have, label as
  nothing) — acceptable, since the full path and the port number are always
  available in the same entry.
