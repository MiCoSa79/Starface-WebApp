"""Zeitzonen-Helfer für geplante Aufgaben (Anlagen-Updates, dm-v10).

Nutzer-Vorgabe (30.08.2026): „Bei Uhrzeiten auf die Zeitzone achten“.
Der Container läuft in UTC, der Admin plant in Europe/Berlin (Sommerzeit
UTC+2, Winterzeit UTC+1). Deshalb:

  * ALLE gespeicherten/verglichenen Zeitpunkte sind UTC (ISO-8601 mit
    Offset), erzeugt von lokal_naive_zu_utc_iso().
  * Die Berlin-Umrechnung passiert NUR an den Grenzen: Formular-Input
    (datetime-local = lokale Browser-Zeit) und Anzeige (Tabelle).
  * Kein Import aus main → zyklusfrei von Routen und Scheduler nutzbar.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


def lokal_naive_zu_utc_iso(value, tz=BERLIN):
    """'2026-08-31T22:00' (datetime-local, Europe/Berlin) -> UTC-ISO (Sekunden).

    Sommerzeit-Beispiel: 2026-08-31T22:00 (CEST, UTC+2) wird zu
    '2026-08-31T20:00:00+00:00'. Ungültige/Eingaben ohne Parse -> None.
    """
    try:
        dt = datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def utc_iso_zu_lokal_anzeige(value, tz=BERLIN):
    """'2026-08-31T20:00:00+00:00' (UTC) -> '31.08.2026, 22:00 Uhr' (Berlin)."""
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value or "")
    return dt.astimezone(tz).strftime("%d.%m.%Y, %H:%M Uhr")


def utc_now_iso():
    """Aktueller UTC-Zeitpunkt als ISO-String ohne Mikrosekunden.

    Gleiche Länge/Format wie lokal_naive_zu_utc_iso() -> lexikografische
    SQL-Vergleiche (scheduled_at <= ?) sind dadurch exakt.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def lokal_now_dt_local(tz=BERLIN):
    """Jetztzeit als datetime-local-String (Europe/Berlin), z. B. für das
    min-Attribut des Planungs-Inputs: 2026-08-31T22:00."""
    return datetime.now(tz).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M")
