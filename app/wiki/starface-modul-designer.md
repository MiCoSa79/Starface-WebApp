---
title: STARFACE Modul Designer (Eigene Module bauen)
description: Anleitung für STARFACE-Module: Modul-Designer-GUI, eigene Java-Bausteine, BusinessObjects, XML-RPC-Einstiegspunkte, Firmenmodul-Muster, Stolpersteine.
updated: 2026-08-25
---

# STARFACE Modul Designer

Wie man Module für die STARFACE-Telefonanlage (PBX) baut: mit dem eingebauten
**Modul Designer** (GUI im Admin-Bereich, Bausteine per Drag & Drop verknüpfen)
und mit **eigenen Java-Klassen** („Modulbausteine"), die als erweiterte
Funktionen in Module eingespielt werden.

**Quellen** (Community-Doku, bildet die ehemalige offizielle Entwickler-Doku ab):
- Live-Wiki: https://wiki.si-solutions.ch/de/home
- GitHub-Mirror (offline lesbar): https://github.com/Fabian95qw/SFWiki
- Referenz-Code echter Bausteine: https://github.com/Fabian95qw/SF-Modulefunctions

> Die offizielle Entwickler-Doku (wiki.starface.de / developer.starface.de)
> existiert nicht mehr öffentlich — beide leiten nur noch auf starface.com um.

## Grundlagen: Modul Designer (GUI)

1. Admin-UI → Modul-Bereich → neues eigenes Modul anlegen, danach
   **Modul-Instanz(en)** erstellen (der Instanzname ist Teil späterer
   XML-RPC-Aufrufe).
2. Im Modul-Editor Bausteine („Components") per Drag & Drop auf die Arbeitsfläche
   ziehen und mit Variablen/Checks verbinden: `Visibility=Public` erscheint unter
   Components → Public, `Private` nur im eigenen Modul. Jeder Baustein hat
   Input-Variablen (Parameter) und Output-Variablen (Rückgabewerte).
3. Einstiegspunkte (Automaten/Pins), RPC Entrypoints und Ressourcen pro Instanz
   konfigurieren.
4. Module werden als **`.sfm`** (JAR-Container) exportiert/importiert
   (Modul-Library) — Details: [[starface-modul-paketierung]].

## Eigene Java-Modulbausteine

### Minimalskelett (Kernmuster)

```java
import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.InputVar;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;

@Function(visibility=Visibility.Private, rookieFunction=false, description="Default")
public class Demo implements IBaseExecutable
{
	@InputVar(label="DEFAULT", description="DEFAULT", type=VariableType.STRING)
	public String INPUT_DEFAULT="";

	@OutputVar(label="DEFAULT", description="DEFAULT", type=VariableType.OBJECT)
	public Object OUTPUT_DEFAULT="";

	@Override
	public void execute(IRuntimeEnvironment context) throws Exception
	{
		OUTPUT_DEFAULT = "10";
	}
}
```

### Regeln und Annotationen

- **Interface-Wahl:** `IBaseExecutable` für normale Bausteine;
  **`IAGIJavaExecutable`** für Call-Processing-Bausteine (Anrufverarbeitung).
- **`@Function(visibility=…)`**: Private (nur eigenes Modul) oder Public.
  `rookieFunction=true` → nur im Experten-Modus sichtbar.
- **`@InputVar` / `@OutputVar`**: Nach JEDER Annotation MUSS unmittelbar eine
  **`public`** Java-Variable folgen — STARFACE befüllt sie aus dem Modul-Editor.
  `possibleValues={...}` erzeugt ein Dropdown.
- **VariableType** (Cast-Regel: STARFACE castet auf den Java-Typ; Fehlcast →
  `null`, nur `BOOLEAN` wird `false`): `STRING`, `NUMBER` (→ `Integer`),
  `BOOLEAN` (→ `boolean`), `OBJECT`, `FILE`, `STARFACE_USER` (→ Account-ID als
  `int`), `STARFACE_GROUP`.
- **Klassenname = Dateiname, KEIN `package`** verwenden (Default-Package), damit
  die Klasse auf der Anlage einfach ladbar ist.

### Auf STARFACE-Funktionen zugreifen (BusinessObjects)

```java
PhoneBusinessObject PBO = (PhoneBusinessObject) context.provider().fetch(PhoneBusinessObject.class);
```

`context.provider().fetch(X.class)` liefert jede Systemkomponente. Wichtige
Komponenten (Auszug):

| Komponente | Zweck |
|---|---|
| `ModuleBusinessObject` | Anrufe: annehmen, Rufnummer anrufen, parken/unparken, Konferenz, Aufzeichnung, Music on Hold, Channel-Status |
| `ModuleRegistry` | Modul-Instanz-Konfiguration, GUI-Elemente, Funktionen anderer Module aufrufen, Instanzen de-/aktivieren |
| `PersonAndAccountHandler` | Benutzer anlegen/editieren/löschen, Berechtigungen, DND-Status, Lizenztyp |
| `GroupHandler` | Gruppen verwalten, Mitgliedschaften anpassen |
| `FunctionKeyManager` | Funktionstasten erstellen/löschen/editieren |
| `RedirectBusinessObject` | Benutzer-/Gruppenumleitungen |
| `SipAndPhonesHandler` | Telefone, IFMC-Konfiguration |
| `AdressBookHandler` | Kontakte, Adressbuch durchsuchen |
| `VoicemailListBusinessObject` | Voicemail-Infos |
| `UserStateBusinessObject` | Benutzerstatus + Avatar |
| `StarfaceEventService` | Events publizieren/abonnieren (`[n]changedEvent`) |
| `SystemUtils` | Systemneustart, Dienste, SSH-Deaktivierung, Systemscripts |
| `CATConnectorPGSQL` | vordefinierte DB-Abfragen |
| `Serverbusinessobject` | ECSTA, Zeitserver, Serverlast |

### Andere Modulbausteine im Code aufrufen

Bausteine sind normale Klassen unter
`de/vertico/starface/module/core/runtime/functions` — instanziieren, public
Input-Felder füllen, `execute(context)` aufrufen (Name ggf. mit Versions-Suffix:
`GetUsersOfGroup2`, `GetCaller2`, `CallPhonenumber2`):

```java
GetUsersOfGroup2 GUS = new GetUsersOfGroup2();
GUS.groupId = 1000; GUS.activeOnly = true;
try { GUS.execute(context); } catch (Exception e) { /* loggen */ }
for (Integer user : GUS.usersOfGroup) log.debug("Member: " + user);
```

**Wildcard-Vergleich NIE selbst bauen — Original `SimpleMatch` direkt
instanziieren** (CallBlocker v24, Praxis bewiesen):

```java
SimpleMatch sm = new SimpleMatch();
sm.text = callerSignallingNumber;   // RAW, NICHT normalisieren
sm.pattern = listEntry;            // RAW-Muster, z. B. "*491627876643"
sm.execute(context);
if (Boolean.TRUE.equals(sm.matches)) { /* Treffer → Hangup */ }
```

Fallen: (1) Selbstgebaute Wildcard-Matcher weichen von der STARFACE-Semantik ab
(stille Fehltreffer). (2) Muster-Normalisierung zerstört `+`/`*`-Logik — nur die
ANRUFERNUMMER optional normalisieren (2. Vergleich als Fallback RAW + normalisiert
deckt `0…`/`0049…`-Lieferformate ab). (3) `pattern`-Zeichen außerhalb `*`/`?`
sind literal (Regex-Metazeichen inkl. `+` escaped).

## Firmenmodul-Muster: Klassen & Entrypoints automatisch im Paket

Fremdmodule bringen ihre Java-Klassen **im .sfm-Paket** mit — der Import macht
alles automatisch (Bausteine registriert, Entrypoints gesetzt). Drei Zutaten:

1. **Klassen ins .sfm legen:** Baustein-`.class` in den JAR-Root, Zusatz-Code als
   Lib-JAR. Beides wird beim Import ins Modul-Verzeichnis extrahiert → automatisch
   im Classpath. Es müssen NUR die Klassen als Funktion deklariert werden, die als
   Baustein/Entrypoint-Ziel dienen — Helferklassen einfach mit einpacken.
2. **Funktionen im Descriptor deklarieren:** Jede Baustein-Klasse wird als
   `<function id="Klassenname" name="Klassenname">` gelistet (Funktions-ID =
   Klassenname!) plus `<implementationFile>Klasse.class</implementationFile>` →
   der Baustein wird beim Import automatisch registriert (kein manueller
   Resource-Upload).
3. **Entrypoints im Descriptor:** `<entryPoints>` mit
   `<agiKernelEntryPoint stage="PostTargetDeterminationIncoming">` (= Designer
   „Activation: on all incoming calls"), `<lifeCycleEntryPoint>` (Stages
   `InstanceActivated|InstanceCreated|InstanceChanged|InstanceDeactivated|
   InstanceDeleted|SystemStarted`) und `RpcEntryPoint`
   (`Type=XMLRPC_auth|XMLRPC_noauth`). Volle CallStage-Enum:
   `PreTargetDetermination`, `PostTargetDetermination`,
   `PostTargetDeterminationIncoming`, `PostLineSelection`, `PreLineDial`,
   `PostPhoneSelection`, `CallHangup`, `EmergencyCall`, `Service`.

⚠️ **rpcEntryPoint-Ziel muss eine Designer-Wrapper-Funktion sein (UUID-`targetId`),
NICHT die Java-Klasse direkt** — direkter Klassen-Target: Import ok, aber
RPC-Parameter kommen nicht an (still, `OUTPUT_ANZAHL=0`). Wrapper = Private-
Funktion ohne `implementationFile`, deren `<functionCall>`-Inputs per
`valueByReference="true"` + `<value>` (UUID der Zielvariable) verdrahtet sind.

⚠️ **Entrypoint-Zielfunktionen haben KEINE InputVariablen** — sonst Warnung
„An entry point uses a function with input variables". Braucht die Java-Funktion
doch Eingaben (z. B. Listen-Input), gilt das Wrapper-Muster auch für
Call-Entrypoints (CallBlocker v28: `CallBlockerEntry` verdrahtet die
Modul-Ebene-Variable `GUI_GEBLOCKTE_RUFNUMMERN` per UUID — Modul-Ebene-Variablen
sind per id aus Kinder-Funktionen auflösbar, Beleg Blacklist v64-Descriptor).

⚠️ **Wrapper-Output-Variablen: `<value>` IMMER leer lassen** — der Import löst
jeden nicht-leeren Output-`<value>` als Variablen-Referenz auf
(`ExecutableObject.validate()`, Importabbruch „Variable referenced in variable
'X' not found"; Java-Funktions-Defaults `0`/`false` sind ok).

⚠️ In `verify_descriptor_refs.py` (Build-Verifikation) nie `..`-XPath verwenden:
ElementTree `find('..')` liefert immer `None` — Parent-Scope per
`parent_map = {c: p for p in root.iter() for c in p}` auflösen.

## Listener / Events

Module können System-Events abonnieren (EventBus mit Annotation):

```java
import org.bushe.swing.event.annotation.EventSubscriber;
import de.vertico.starface.persistence.connector.events.DoNotDistrubSettingChangedEvent;

public class ExampleListener {
	private Log log;
	public ExampleListener(Log log) { this.log = log; }

	@EventSubscriber
	public void onDoNotDistrubSettingChangedEvent(DoNotDistrubSettingChangedEvent e) {
		log.debug("DND for account " + e.getAccountId() + " = " + e.isDoNotDisturbSetting());
	}
}
```

Registrieren/Deregistrieren über `StarfaceEventService.subscribe(listener)` /
`unsubscribe(listener)` (statische Referenz gegen Doppel-Registrierung).

**Wichtige Events:** `PresenceChangedEvent`, `TelephonyStateChangedEvent`,
`DoNotDistrubSettingChangedEvent`, `NewCallStateEvent` (⚠️ benötigt
`@EventSubscriber(eventServiceName = "CallProcessingEventService")`!),
`onModuleInstanceStateChangedEvent`, `onLineStateChangedEvent`.

## XML-RPC-Einstiegspunkte

**Weg 1 — Descriptor (Firmenmuster, empfohlen):** `<rpcEntryPoint name="…">` mit
`functionReference targetId=<Wrapper-UUID>` + `<type>XMLRPC_auth|XMLRPC_noauth</type>`
direkt in die `module-descriptor.xml` → Import erzeugt die Entrypoints
automatisch (CallBlocker v8; kein Editor-Schritt). Aufrufname bleibt
`[Instanzname].[Entrypoint-Name]`.

**Weg 2 — Editor-Freigabe (klassisch):** Im Modul-Editor eine Funktion anlegen
(Input-/Output-Variablen werden zum RPC-Protokoll), im ersten Tab **„Rpc
Entrypoints"** freigeben. **Der Instanzname ist Teil des Aufrufs**:
`[Instanzname].[Entrypoint-Name]`.

**Aufruf:**
- URL: `https://[IP]/xml-rpc?de.vertico.starface.auth=TOKEN` (Legacy ≤ 9.x) bzw.
  `https://[IP]/xml-rpc?de.vertico.starface.jwt=JWT` (STARFACE 10+).
- Body: XML-RPC `methodCall`, `methodName` = Entrypoint-Name, Parameter als
  `<struct>` mit den **Variablennamen** der Funktion.

**Auth-Token:**
- **STARFACE 10+ (JWT via OAuth):** POST an `/auth/realms/pbx/oauth2/token` mit
  `client_id=rest-client-headless`, `grant_type=password`, `scope=login`,
  `username=[Login-ID z. B. 0001]`, `password=[Benutzerpasswort]`,
  `client_secret=[Admin-UI → Server → Status → REST-API]`; User braucht das
  Recht **„API Zugriff mit OAuth Password Grant"**. access_token 5 min gültig
  (Refresh: `grant_type=refresh_token`, 6 h). Client-Auth: Basic-Auth-Header ODER
  Form-Fields (je nach Keycloak-Konfiguration — beides probieren). 401 =
  typisch fehlendes Benutzerrecht oder falsches Client-Secret — NICHT den
  Legacy-Login verwenden (fällt ab Version 11 weg).
- **Legacy (≤ 9.x):** `Token = Login:sha512(Login + "*" + sha512(Passwort))` —
  das `*` ist ein Zeichen, kein Operator.
- **Ohne Auth (Vorsicht!):** im Descriptor `<type>XMLRPC_noauth</type>` setzen
  und neu importieren. ⚠️ Kein Modul-Editor-Fenster des Moduls offen lassen,
  sonst gehen Änderungen verloren. Immer eigene Schutzlogik (eigenes Token)
  einbauen.

## Arbeits-Pflicht: Erst Doku + Referenz sezieren, nie das Erstbeste

Aus der CallBlocker-Krise (mehrfache Nutzer-Korrektur, obwohl Blacklist_v64 +
API-Doku die Lösung komplett vorgaben) gilt für **jede** neue Modul-Funktion
diese Reihenfolge:

1. **Referenzmodell finden und KOMPLETT sezieren, bevor Code entsteht:** Wenn es
   ein Muster/Referenzmodul gibt: Descriptor Zeile für Zeile (Entrypoints,
   `inputVars` inkl. `accessRights`, jede `valueByReference`-Verdrahtung) UND die
   Bytecode-Klassen der Funktionen (welche Bausteine instanziiert & befüllt
   werden). Erst danach die Architektur übernehmen.
2. **Den gesuchten Baustein in der API-Doku verifizieren und den ORIGINAL-Baustein
   (`de.vertico.starface.module.core.runtime.functions.*`) instanziieren** —
   Eigencode nur als Kleber (try/catch, Schleife, Logging). Fachlogik, die ein
   dokumentierter Baustein kann, gehört NIE selbst implementiert: Mustervergleich
   → `SimpleMatch` (nicht eigener Matcher), Anruferdaten →
   `GetCaller2.callerSignallingNumber`, Loggen → `Log2` (nicht `context.getLog()`).
3. **Vorhandene Modul-Ressourcen nutzen statt eigene Lade-Logik:** Daten, die als
   Modul-Variable bereits im Modul liegen (GUI-Listen wie
   `GUI_GEBLOCKTE_RUFNUMMERN`, accessRights=Read), kommen per Descriptor-
   Verdrahtung (`valueByReference`) in die Funktion — KEIN eigenes
   Zur-Laufzeit-Laden.
4. **Bei Unklarheit gezielt Doku-Punkt nachschlagen, nicht raten.**
5. **Eigenbau ist ausdrücklich ERWÜNSCHT — aber nur wenn nötig:** Bietet Doku/
   Referenz für die benötigte Funktion KEINEN Baustein und KEIN Muster
   (z. B. WebApp-Sync, ListAdd-Append+Dedup), dann sauber auf Basis der
   dokumentierten Patterns bauen. Faustregel: *Erst den Katalog durchsuchen, dann
   die Lücke bauen* — Eigencode als Ergänzung der Bausteine, nie als Ersatz
   vorhandener Funktionen.

## Stolpersteine (aus der Praxis)

1. **DB-Änderungen nicht sofort in der GUI sichtbar:** STARFACE lädt beim Booten
   viel in den RAM — Direkt-SQL erscheint erst nach Neustart. Immer die passende
   Systemkomponente (BusinessObject) nutzen.
2. **Thread-/Listener-Kontrollverlust:** Beim Speichern/Updaten eines Moduls im
   Designer wird eine neue Revision erzeugt, alle Klassen (inkl. static) neu
   instanziiert — alte Threads/Listener laufen weiter (nur Systemneustart stoppt
   sie). → Immer Stop-/De-Registrier-Möglichkeit einbauen.
3. **Falsche Java-Version:** STARFACE 10.x = **Java 21** (Klassen-Version 65.0);
   JDK 8 (52.0) wirft `bad class file… has wrong version 65.0`. Mit Temurin JDK 21
   kompilieren.
4. **Library-Konflikte:** Andere Version einer von STARFACE mitgelieferten Library
   → nicht nutzbar, STARFACE-Version gewinnt.
5. **Casting:** Falscher `VariableType` zum Java-Typ → `null` (BOOLEAN: `false`).
6. **Logging IMMER über den Baustein `Log2` — `context.getLog()` ist KEIN
   Schreib-Baustein!** Die API-Doku kennt genau EINEN Log-Eintrag: **Log2**
   („Logs a message to the module log file"). Muster:

   ```java
   Log2 l = new Log2();
   l.logLevel = "INFO";          // DEBUG, INFO, WARN, ERROR
   l.messages = Collections.singletonList("CallBlocker: EINTRITT ...");
   l.execute(context);           // Exception → try/catch, Fehler schlucken
   ```

   Erscheint im **Modul-/Instanz-Log** (Admin-UI → Module → Instanzen → [Instanz]
   → Log-Tab). `getLog()` nur als Java-Getter, nie als Schreib-Ziel.
7. **`rookieFunction` deprecated** in den 10.x-Annotationen (nur Warning), aber
   `-proc:none` beim javac nutzen, sonst meckert der Annotation-Processor.
8. **`HangupCause`** liegt NUR im JAR `starface-callhandling-10.0.2.5.jar`.
9. **RPC-Entrypoints im Descriptor nur mit Design-Wrapper-Zielen** (siehe oben);
   `.sfm` = JAR, **nie als nackten Zip packen** („Manifest fehlt!") — Details:
   [[starface-modul-paketierung]].

## Verwandt

- [[starface-anrufblocker]] — Anwendungsprojekt (CallBlocker v28, Web-App v0.0.97).
- [[starface-modul-paketierung]] — `.sfm` als JAR bauen und verifizieren.
