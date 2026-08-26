#!/usr/bin/env python3
"""Erzeugt die Modul-Dokumentationen (PDF) für die Modul-Seite (/admin/modules).

Aufruf:  python3 app/scripts/generate_modul_pdfs.py
Ausgabe: app/static/docs/<ModulName>.pdf  (Spalte „Dokumentation“ verlinkt hierauf)

Layout: A4, DejaVu-Schriften (Umlaute!), roter Akzent in WebApp-Optik,
Meta-Tabelle (Kurzprofil), nummerierte Abschnitte, Schritt-/Fehler-Tabellen,
Fußzeile mit „Stand“ + Seitenzahl.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError as e:  # pragma: no cover
    sys.exit(f"reportlab fehlt: {e}")

ROOT = Path(__file__).resolve().parent.parent           # app/
OUT = ROOT / "static" / "docs"
AKZENT = colors.HexColor("#e94560")                     # WebApp-Rot
BLAU = colors.HexColor("#0f3460")
HELL = colors.HexColor("#f2f4f8")
GRAU = colors.HexColor("#555555")


def _fonts() -> dict:
    base = "/usr/share/fonts/truetype/dejavu"
    pre = {
        "normal": ("DejaVu", str(Path(base) / "DejaVuSans.ttf")),
        "bold": ("DejaVu-Bold", str(Path(base) / "DejaVuSans-Bold.ttf")),
        "mono": ("DejaVuMono", str(Path(base) / "DejaVuSansMono.ttf")),
    }
    out = {"normal": ("Helvetica",), "bold": ("Helvetica-Bold",), "mono": ("Courier",)}
    for key, (name, path) in pre.items():
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            out[key] = (name,)
        except Exception:
            pass
    return out


class Styles:
    def __init__(self, f: dict):
        n, b, m = f["normal"][0], f["bold"][0], f["mono"][0]
        self.titel = ParagraphStyle("titel", fontName=b, fontSize=21, leading=25,
                                    textColor=BLAU, spaceAfter=2)
        self.unter = ParagraphStyle("unter", fontName=n, fontSize=10.5, leading=14,
                                    textColor=GRAU, spaceAfter=10)
        self.kicker = ParagraphStyle("kicker", fontName=b, fontSize=8.5, leading=11,
                                     textColor=AKZENT)
        self.h2 = ParagraphStyle("h2", fontName=b, fontSize=13, leading=16,
                                 textColor=BLAU, spaceBefore=14, spaceAfter=5)
        self.body = ParagraphStyle("body", fontName=n, fontSize=9.5, leading=13.5,
                                   textColor=colors.HexColor("#222222"))
        self.bullet = ParagraphStyle("bullet", fontName=n, fontSize=9.5, leading=13.5,
                                     leftIndent=10, bulletIndent=2,
                                     textColor=colors.HexColor("#222222"))
        self.zelle = ParagraphStyle("zelle", fontName=n, fontSize=9, leading=12.5,
                                    textColor=colors.HexColor("#222222"))
        self.zelleb = ParagraphStyle("zelleb", fontName=b, fontSize=9, leading=12.5,
                                     textColor=colors.white)


def _p(t: str, s) -> Paragraph:
    return Paragraph(t, s)


def _meta(story, s: Styles, rows: list[tuple[str, str]]) -> None:
    data = [[_p("<b>%s</b>" % k, s.zelle), _p(v, s.zelle)] for k, v in rows]
    t = Table(data, colWidths=[38 * mm, None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HELL),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)


def _schritte(story, s: Styles, rows: list[tuple[str, str]]) -> None:
    data = [[_p("Schritt", s.zelleb), _p("Aktion", s.zelleb), _p("Ergebnis", s.zelleb)]]
    data += [[_p(str(i), s.zelle), _p(a, s.zelle), _p(e, s.zelle)]
             for i, (a, e) in enumerate(rows, 1)]
    t = Table(data, colWidths=[14 * mm, None, 52 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLAU),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HELL]),
    ]))
    story.append(t)


def _fehler(story, s: Styles, rows: list[tuple[str, str]]) -> None:
    data = [[_p("Problem", s.zelleb), _p("Lösung", s.zelleb)]]
    data += [[_p(p, s.zelle), _p(l, s.zelle)] for p, l in rows]
    t = Table(data, colWidths=[52 * mm, None], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLAU),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HELL]),
    ]))
    story.append(t)


def build_pdf(module: str, titel: str, untertitel: str, profile: list[tuple[str, str]],
              kapitel: list[dict], stand: str) -> Path:
    """kapitel: [{nummer, titel, text?, bullets?, schritte?, fehler?}]"""
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{module}.pdf"
    f = _fonts()
    s = Styles(f)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica" if not f["normal"] else f["normal"][0], 8)
        canvas.setFillColor(GRAU)
        canvas.drawString(20 * mm, 12 * mm, f"Stand: {stand}")
        canvas.drawRightString(A4[0] - 20 * mm, 12 * mm,
                               f"{module} v{module_version(module)} · Seite {doc.page}")
        canvas.setStrokeColor(AKZENT)
        canvas.setLineWidth(0.8)
        canvas.line(20 * mm, 15 * mm, A4[0] - 20 * mm, 15 * mm)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(out), pagesize=A4,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title=f"{titel} — STARFACE-WebApp-Dokumentation",
                            author="Axel Meiser - Kraemer IT")
    story = []
    story.append(_p("STARFACE WebApp · Modul-Dokumentation", s.kicker))
    story.append(_p(titel, s.titel))
    story.append(_p(untertitel, s.unter))
    story.append(Spacer(1, 2))
    _meta(story, s, profile)
    for k in kapitel:
        if k.get("pagebreak"):
            story.append(PageBreak())
        story.append(_p(f"{k['nummer']}. {k['titel']}", s.h2))
        if k.get("text"):
            story.append(_p(k["text"], s.body))
            story.append(Spacer(1, 3))
        for b in k.get("bullets", []):
            story.append(_p("• %s" % b, s.bullet))
        if k.get("bullets"):
            story.append(Spacer(1, 3))
        if k.get("schritte"):
            _schritte(story, s, k["schritte"])
            story.append(Spacer(1, 3))
        if k.get("fehler"):
            _fehler(story, s, k["fehler"])
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out


def module_version(name: str) -> str:
    return {"CallBlocker": "29", "TelefonieMonitoring": "8",
            "UpdateDeployer": "6"}.get(name, "?")


STAND = "26.08.2026"


def main() -> int:
    docs = [
        build_pdf(
            "CallBlocker",
            "CallBlocker",
            "Blocklist-Anrufabschaltung — weist Anrufe von Rufnummern auf der Blocklist ab.",
            [("Modul", "CallBlocker"), ("Aktuelle Version", "v29 (Stand 26.08.2026)"),
             ("Hersteller", "Axel Meiser - Kraemer IT"),
             ("Installationsname (Empfehlung)", "CallBlocker"),
             ("Logging", "genau 1 Zeile pro geblocktem Anruf")],
            [
                {"nummer": 1, "titel": "Was macht das Modul?",
                 "text": "CallBlocker prüft jeden eingehenden Anruf gegen die konfigurierte "
                         "Blocklist. Ein Treffer beendet den Anruf (Hangup) und schreibt genau "
                         "einen Logeintrag. Anrufe, die nicht auf der Liste stehen, laufen "
                         "unverändert durch — ganz ohne Log.",
                 "bullets": ["Blocklist-Pflege direkt in der WebApp (Nummern hinzufügen/entfernen).",
                             "Einfacher Abgleich auf die Anrufernummer (z. B. mit Vorwahl).",
                             "Umschalten/Monitoring über die Statusseite der WebApp."]},
                {"nummer": 2, "titel": "Funktionsweise",
                 "text": "Die Instanz verarbeitet eingehende Rufe im Startpfad der Anlage:",
                 "bullets": ["Eingehender Anruf → Rufnummer wird mit der Blocklist verglichen.",
                             "Treffer → Anruf wird abgewiesen (Hangup) und geloggt: "
                             "„Anruf von der Rufnummer <nr> wurde geblockt“.",
                             "Kein Treffer → Anruf läuft normal weiter (keine Logzeile).",
                             "Kein Netzwerk-/IO-Verhalten — reine Telefonie-Verarbeitung."]},
                {"nummer": 3, "titel": "Einrichtung in der Telefonanlage",
                 "schritte": [
                     ("Admin-UI → Modul-Import: CallBlocker.sfm laden (oder WebApp: "
                      "„Fehlende Module installieren“ / „Installation anstoßen“).",
                      "Modul erscheint in der Modul-Bibliothek."),
                     ("Instanz anlegen (Name frei, z. B. CallBlocker).",
                      "Instanz erscheint in der Modul-Konfiguration."),
                     ("Instanz aktivieren (Status „Aktiv“).",
                      "Blocklist-Verarbeitung läuft."),
                     ("Blocklist in der WebApp füllen (siehe Abschnitt 4).",
                      "Treffer-Nummern werden abgewiesen.")]},
                {"nummer": 4, "titel": "Einrichtung in der WebApp",
                 "schritte": [
                     ("Anlage unter Admin anlegen/konfigurieren (URL + Zugangsdaten).",
                      "Anlage wird auf Status- und Update-Seiten geführt."),
                     ("Blocklist öffnen und Rufnummern eintragen (einheitliches Format, "
                      "mit Vorwahl empfohlen).",
                      "Einträge greifen sofort auf der Anlage."),
                     ("Modul-Updates-Seite: Status SOLL/IST prüfen (v29).",
                      "Update verfügbar / aktuell sichtbar."),
                     ("Updates: „Update anstoßen“ pro Modul oder Sammel-Buttons "
                      "(„Fehlende Module installieren“ / „Module aktualisieren“).",
                      "WebApp lädt die signierte .sfm und importiert sie automatisch.")]},
                {"nummer": 5, "titel": "Versionen & Wartung",
                 "bullets": ["Updates laufen vollautomatisch über die WebApp (UpdateDeployer: "
                             "signierter Download + Import + Neustart aktiver Instanzen).",
                             "Modul-Historie v1–v29 dokumentiert (Git-Tags im Repo).",
                             "Log-Ausgabe des Moduls zeigt nur geblockte Anrufe."]},
                {"nummer": 6, "titel": "Fehlerbehebung",
                 "fehler": [
                     ("Anruf wird nicht geblockt.",
                      "Nummernformat in der Blocklist prüfen (mit Vorwahl, einheitlich); "
                      "Instanz aktiv? Modul-Status v29 (IST = SOLL)?"),
                     ("Seite zeigt „nicht installiert“.",
                      "Erst-Import anstoßen („Installation anstoßen“), danach Instanz anlegen "
                      "und aktivieren."),
                     ("Kein Log beim Blockieren.",
                      "Modul-Log der Instanz in der Admin-UI der Anlage prüfen (Instanz-Ausgabe).")]},
            ],
            STAND),
        build_pdf(
            "TelefonieMonitoring",
            "TelefonieMonitoring",
            "Systemmetriken (RAM, CPU-Last, STARFACE-Version, Hostname) und SIP-Provider-Status für die WebApp.",
            [("Modul", "TelefonieMonitoring"), ("Aktuelle Version", "v8 (Stand 26.08.2026)"),
             ("Hersteller", "Axel Meiser - Kraemer IT"),
             ("Installationsname (Vorgabe)", "TelefonieMonitoring"),
             ("Logging", "bewusst still — das Modul schreibt keine Log-Einträge")],
            [
                {"nummer": 1, "titel": "Was macht das Modul?",
                 "text": "TelefonieMonitoring liefert der WebApp die Statusdaten der Anlage: "
                         "Speichernutzung, CPU-Last, STARFACE-Version, Hostname sowie den "
                         "Registrierungs-Status der SIP-Provider. Die WebApp wertet diese Daten "
                         "aus (Statusseite/-karte, Zeitreihen über InfluxDB, Bucket 'telefonie') "
                         "und zeigt auf der Modul-Updates-Seite zusätzlich die installierte "
                         "Modul-Version (IST).",
                 "bullets": ["Auslieferung als XML-RPC-Funktionen (GetStats / GetModuleStatus).",
                             "Keine eigenen Log-Einträge (Rauschen vermeiden, bewusst still).",
                             "Fehler werden als Antwort gemeldet — die WebApp zeigt dann „—“."]},
                {"nummer": 2, "titel": "Funktionsweise",
                 "bullets": ["Die WebApp ruft die Statusfunktion periodisch auf der "
                             "konfigurierten Monitoring-Instanz auf.",
                             "Das Modul sammelt System- und Telefonie-Metriken und gibt sie "
                             "als Datensatz zurück.",
                             "GetModuleStatus liefert Version/Status des Moduls für die "
                             "Status- und Modul-Updates-Seite.",
                             "Bei Registry- oder Datenbank-Problemen wird eine Fehlerantwort "
                             "geliefert (kein Log-Aufwand auf Anlagen-Seite)."]},
                {"nummer": 3, "titel": "Einrichtung in der Telefonanlage",
                 "schritte": [
                     ("Admin-UI → Modul-Import: TelefonieMonitoring.sfm laden (oder WebApp: "
                      "„Fehlende Module installieren“ / „Installation anstoßen“).",
                      "Modul erscheint in der Modul-Bibliothek."),
                     ("Instanz anlegen — Name exakt so, wie er später in der WebApp als "
                      "monitoring_instance_name eingetragen wird (Vorgabe: "
                      "TelefonieMonitoring).",
                      "WebApp findet die Instanz auf der Anlage."),
                     ("Instanz aktivieren.",
                      "Statusfunktionen sind aufrufbar.")]},
                {"nummer": 4, "titel": "Einrichtung in der WebApp",
                 "schritte": [
                     ("Anlage unter Admin konfigurieren: monitoring_instance_name = "
                      "Instanzname aus Schritt 3.",
                      "Statusseite/Modul-Updates können die Anlage abfragen."),
                     ("Zeitreihen-Auswertung: InfluxDB-Datenquelle (Bucket 'telefonie') "
                      "konfigurieren.",
                      "Verlauf wird gespeichert und visualisiert."),
                     ("Statusseite prüfen: Karte zeigt Hostname, Version und Provider-Status.",
                      "Live-Daten sichtbar."),
                     ("Modul-Updates-Seite: IST-Version v8 verifizieren.",
                      "Update verfügbar / aktuell sichtbar.")]},
                {"nummer": 5, "titel": "Fehlerbehebung",
                 "fehler": [
                     ("Karte/Status zeigt „—“.",
                      "Instanz aktiv? Instanzname in der WebApp exakt gleich (Groß-/Kleinschreibung)? "
                      "Verbindungsdaten prüfen."),
                     ("GetModuleStatus-Fault „No item with that key“.",
                      "Instanz einmalig neu anlegen oder Modul re-importieren (bekannte "
                      "Platform-Eigenheit)."),
                     ("Status ok, aber keine Verlaufsdaten.",
                      "InfluxDB-Verbindung (Bucket 'telefonie') und Schreibrechte prüfen.")]},
            ],
            STAND),
        build_pdf(
            "UpdateDeployer",
            "UpdateDeployer",
            "Zentrales HUB-Modul für automatische Modul-Updates über die WebApp.",
            [("Modul", "UpdateDeployer"), ("Aktuelle Version", "v6 (Stand 26.08.2026)"),
             ("Hersteller", "Axel Meiser - Kraemer IT"),
             ("Installationsname (Empfehlung)", "UpdateDeployer"),
             ("Update-Basis-URL", "wird im Admin-Bereich der WebApp festgelegt")],
            [
                {"nummer": 1, "titel": "Was macht das Modul?",
                 "text": "UpdateDeployer ist das Verbindungsstück zwischen der WebApp und der "
                         "Telefonanlage für automatische Modul-Updates: Er lädt signierte "
                         "Modul-Pakete (.sfm), importiert sie und startet die aktiven Instanzen "
                         "des Zielmoduls automatisch neu. Außerdem dient er als "
                         "Erreichbarkeits-Beweis (Ping) und schützt Updates per Token.",
                 "bullets": ["Signierter Download über zeitlich begrenzte URLs (5 min).",
                             "Erst-Import UND Update über denselben Pfad — auch neue Module "
                             "können so installiert werden.",
                             "GUI-Tab „Sicherheit“ für das Update-Token (GU_UPDATE_TOKEN)."]},
                {"nummer": 2, "titel": "Funktionsweise",
                 "bullets": ["Die WebApp erzeugt eine signierte Download-URL für das "
                             "Zielmodul und ruft die Update-Funktion der Instanz auf.",
                             "Das Modul lädt die .sfm-Datei, prüft die Signatur und importiert "
                             "das Paket (ersetzt ein vorhandenes Modul bzw. legt ein neues an).",
                             "Danach werden alle aktiven Instanzen des Zielmoduls automatisch "
                             "neu gestartet; inaktive Instanzen bleiben inaktiv.",
                             "Ohne passendes GU_UPDATE_TOKEN wird kein Update ausgeführt "
                             "(Instanz-Schutz)."]},
                {"nummer": 3, "titel": "Einrichtung in der Telefonanlage",
                 "schritte": [
                     ("Admin-UI → Modul-Import: das aktuelle UpdateDeployer.sfm laden "
                      "(Download auf der Modul-Seite der WebApp).",
                      "Modul erscheint in der Modul-Bibliothek."),
                     ("Instanz anlegen (Empfehlung: UpdateDeployer).",
                      "Instanz erscheint in der Modul-Konfiguration."),
                     ("Tab „Sicherheit“ öffnen und GU_UPDATE_TOKEN setzen — derselbe Wert, "
                      "der in der WebApp als deployer_token hinterlegt ist.",
                      "WebApp und Anlage teilen sich den Update-Schlüssel."),
                     ("Instanz aktivieren.",
                      "Update-Funktionen sind aufrufbar.")]},
                {"nummer": 4, "titel": "Einrichtung in der WebApp",
                 "schritte": [
                     ("Admin → Anlage: Modul-Update-Basis-URL setzen (der im Betrieb "
                      "verwendete Update-Server; kein fester Wert).",
                      "versions.json wird vom Update-Server gespiegelt."),
                     ("deployer_instance_name = Installationsname von UpdateDeployer.",
                      "WebApp ruft die richtige Instanz auf."),
                     ("deployer_token = GU_UPDATE_TOKEN aus Schritt 3.",
                      "Updates werden von der Anlage akzeptiert."),
                     ("Modul-Updates-Seite: „Download-Test (Ping)“ ausführen.",
                      "Erreichbarkeits-Beweis grün."),
                     ("„Update anstoßen“ bzw. Sammel-Buttons nutzen.",
                      "Update läuft automatisch (Download → Import → Neustart).")]},
                {"nummer": 5, "titel": "Token-Empfehlung (GU_UPDATE_TOKEN)",
                 "text": "Der Token schützt Updates auf der Anlage und muss in der Anlage "
                         "(Tab „Sicherheit“) und in der WebApp (deployer_token) identisch sein.",
                 "bullets": ["Mindestens 32 Zeichen — je länger, desto besser "
                             "(Empfehlung: 43+ Zeichen).",
                             "URL-sicher erzeugen: python3 -c \"import secrets; "
                             "print(secrets.token_urlsafe(32))\" oder openssl rand -base64 24.",
                             "PowerShell: (New-Guid).Guid -replace '-', '' "
                             "= 32 Hex-Zeichen (läuft NICHT unter Constrained Language "
                             "Mode).",
                             "PowerShell mit .NET-API (nicht CLM): $b = New-Object byte[] 24; "
                             "[Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($b); "
                             "[Convert]::ToBase64String($b) = 32 Zeichen Base64.",
                             "Hinweis CLM: Kryptographisch starke Tokens lassen sich in einer "
                             "eingeschränkten Shell (CLM) nicht per Cmdlet erzeugen — Token "
                             "außerhalb erzeugen (Python/openssl) und in Anlage + WebApp hinterlegen.",
                             "Zeichensatz: Python token_urlsafe, openssl und die GUID-Variante liefern "
                             "URL-sichere Zeichen; Base64 kann +, / und = enthalten — für den RPC-Aufruf "
                             "unkritisch, beide Felder (Anlage ↔ WebApp) identisch füllen.",
                             "Wie ein Master-Passwort behandeln: nicht in Mails/Screenshots/Logs; "
                             "bei Verdacht auf beiden Seiten neu setzen (Anlage + WebApp)."]},
                {"nummer": 6, "titel": "Versionen",
                 "table_note": True,
                 "bullets": ["v1: PingChannel (Erreichbarkeits-Beweis über den Kanal).",
                             "v2: UpdateFromUrl — signierter Download + Modul-Import.",
                             "v4/v5: GUI-Tab „Sicherheit“ mit Token-Feld (GU_UPDATE_TOKEN).",
                             "v6: Automatischer Neustart aller aktiven Instanzen des "
                             "Zielmoduls nach dem Import."]},
                {"nummer": 7, "titel": "Fehlerbehebung",
                 "fehler": [
                     ("Update wird nicht gestartet / Download-Fehler.",
                      "Basis-URL erreichbar? Token identisch (Anlage ↔ WebApp)? URL nur 5 min "
                      "gültig — einfach erneut anstoßen."),
                     ("Meldung „Modul nicht installiert“.",
                      "Erst-Import über „Installation anstoßen“ (macht derselbe Deployer)."),
                     ("Instanz wird nicht neu gestartet.",
                      "Nur aktive Instanzen werden neu gestartet; inaktive bleiben bewusst "
                      "inaktiv."),
                     ("Nach Update kein Token im Tab „Sicherheit“.",
                      "Normal nicht zu erwarten — Import verändert die Instanz-Konfiguration "
                      "nicht; sonst Token erneut setzen.")]},
            ],
            STAND),
    ]
    for p in docs:
        print(f"OK {p.name} ({p.stat().st_size} Byte)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
