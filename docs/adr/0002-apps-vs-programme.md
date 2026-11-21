# 2. Ports als „app“ oder „program“ einordnen

Date: 2026-11-21

## Status

Accepted. Ergänzt ADR 0001 (voller Scan bleibt).

## Context

Das Menü listete jeden lauschenden Port: Claude-Code-Sessions, VS-Code-Helper, Bitwarden,
Logi-Dienste, irrlichd. Gesucht sind aber nur die lokalen Web-Apps, die man selbst laufen hat.
Docker-Apps (OrbStack) tauchten dagegen gar nicht sinnvoll auf: Der lauschende Prozess ist der
VM-Helper mit cwd „/“.

## Decision

- Der Scan bleibt vollständig (ADR 0001). Jeder Eintrag bekommt `kind`: `app` oder `program`.
- **app** = `GET /` liefert `text/html` (egal welcher Status) **und** der Prozess läuft aus einem
  Projektordner (cwd nicht „/“, nicht in einem `.app`-Bundle) oder ist ein Docker-Port.
- Docker-Ports werden über `docker ps` dem Compose-Arbeitsordner zugeordnet, angehoben auf dessen
  Git-Toplevel (Compose-Dateien liegen oft in `deployment/`).
- `severity` orange nur bei exposed **Apps**; Programme sind nicht handlungsrelevant.
- Anzeigen (SwiftBar) zeigen nur `app`; der Report listet weiterhin alles mit Spalte „Art“.

## Consequences

- Ein HTTP-Probe pro Port und Lauf (parallel, 1,5 s Timeout), ohne Login-Daten.
- Eine reine API ohne HTML-Startseite gilt als `program` und erscheint nur im Report.
- `from __future__ import annotations` macht das Skript wieder mit dem System-Python 3.9 lauffähig.
