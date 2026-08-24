import java.io.*;
import java.util.*;

import org.apache.logging.log4j.Logger;

import de.starface.bo.callhandling.actions.ModuleBusinessObject;
import de.starface.callhandling.enums.HangupCause;
import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IAGIJavaExecutable;
import de.vertico.starface.module.core.runtime.IAGIRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import de.vertico.starface.module.core.runtime.functions.callHandling.call.GetCaller2;
import de.vertico.starface.module.core.runtime.functions.lang.string.regexp.SimpleMatch;
import de.vertico.starface.module.core.runtime.functions.system.Log2;

/**
 * CallBlocker — weist Anrufe unerwünschter Rufnummern ab.
 *
 * Wird als IAGIJavaExecutable-Baustein in die Anrufroute der Ziel-Gruppe
 * eingehängt. Blockiert nur bei Treffer — bei keinem Treffer wird der Anruf
 * unangetastet weitergeleitet (niemals answer()/parkCall()).
 *
 * Kompilieren:
 *   javac -cp "classes:lib/starface-callhandling-10.0.2.5.jar:..." CallBlocker.java
 *
 * @author si.module
 */
@Function(visibility = Visibility.Public, rookieFunction = false,
          description = "Weist Anrufe von Rufnummern in der Blocklist ab.")
public class CallBlocker implements IAGIJavaExecutable
{
    // ##########################################################################################
    // Variablen: werden vom Modul-Editor befüllt
    // KEIN @InputVar mehr (seit v5): Ein Call-Processing-Entrypoint kann die
    // Eingabevariable beim automatischen Aufruf nicht befüllen — STARFACE warnt
    // dann beim Speichern im Designer „An entry point uses a function with input
    // variables“. Der Blocklist-Pfad ist fix = Instanz-Datenverzeichnis.

    @OutputVar(label = "BlockStatus", description =
               "BlockStatus ist true wenn der Anruf blockiert wurde, false sonst",
               type = VariableType.BOOLEAN)
    public boolean BlockStatus = false;

    // ##########################################################################################

    @Override
    public void execute(IAGIRuntimeEnvironment context) throws Exception
    {
        Logger log = context.getLog();
        String channel = context.getCallerChannelName();

        logAll(context, "INFO", "CallBlocker: EINTRITT (channel="
               + (channel == null ? "null" : channel) + ")");

        // Kein aktiver Kanal? → nichts tun
        if (channel == null || channel.isEmpty())
        {
            logAll(context, "INFO", "CallBlocker: kein aktiver Kanal -> Abbruch");
            return;
        }

        // 1) Anrufernummer auflösen
        String callerNumber = resolveCallerNumber(context);
        logAll(context, "INFO", "CallBlocker: callerSignallingNumber RAW = '"
               + callerNumber + "'");
        if (callerNumber == null)
        {
            logAll(context, "WARN", "CallBlocker: keine Anrufernummer gefunden -> Abbruch");
            return;
        }

        String normalized = normalize(callerNumber);
        logAll(context, "INFO", "CallBlocker: normalisiert = '" + normalized + "'");
        if (normalized.isEmpty())
        {
            logAll(context, "WARN", "CallBlocker: nummer nach Normalisierung leer -> Abbruch");
            return;
        }

        // 2) Blocklist laden (ListResource der Instanz, seit v22)
        List<String> patterns = loadBlocklist(context, log);
        logAll(context, "INFO", "CallBlocker: Blocklist geladen -> "
               + patterns.size() + " Muster: " + patterns);

        // 3) Prüfen — exakt die STARFACE-SimpleMatch-Semantik (wie Referenzmodul
        //    "Blacklist v64"): Wildcard '*' = beliebig viele Zeichen, '?' = genau
        //    eines, kompletter String-Match. Verglichen wird gegen die RAW-
        //    Anrufernummer (callerSignallingNumber) und als Fallback gegen die
        //    normalisierte Form (deckt 0…/0049…-Lieferungen der Anlage ab).
        logAll(context, "INFO", "CallBlocker: prüfe Anruf von " + callerNumber
               + " (normalisiert: " + normalized + ") gegen "
               + patterns.size() + " Muster");
        if (matchesAny(context, callerNumber, normalized, patterns))
        {
            // 4) Abweisen + Log — BLOCKED-Meldung nur über den dokumentierten
            //    Log2-Baustein (Modul-Log); getLog() ist kein Schreib-Baustein!
            ModuleBusinessObject MBO = (ModuleBusinessObject)
                context.springApplicationContext().getBean(ModuleBusinessObject.class);
            MBO.hangup(channel, HangupCause.NORMAL_CLEARING);
            logAll(context, "INFO", "BLOCKED: Anruf von " + callerNumber
                   + " (normalisiert: " + normalized + ") abgewiesen (Blocklist)");
            BlockStatus = true;
            return;
        }
        // Kein Treffer: nichts weiter tun — Route läuft normal weiter
        logAll(context, "INFO", "CallBlocker: kein Treffer -> Anruf läuft normal weiter");
        BlockStatus = false;
    }

    // ##########################################################################################
    // Hilfs-Methoden

    /** Holt die Anrufernummer über den integrierten GetCaller2-Baustein. */
    private String resolveCallerNumber(IAGIRuntimeEnvironment context)
    {
        try
        {
            GetCaller2 gc = new GetCaller2();
            gc.execute(context);
            return gc.callerSignallingNumber;
        }
        catch (Exception e)
        {
            return null;
        }
    }

    /**
     * Liest die Blocklist aus der ListResource der Instanz (seit v22,
     * keine blocklist.txt mehr). Der Zugriff nutzt denselben Weg wie der
     * Instanz-Editor: variable.getValue() = ListResource-ID.
     */
    private List<String> loadBlocklist(IAGIRuntimeEnvironment context, Logger log)
    {
        return ListManager.loadBlocklist(context, log);
    }

    /**
     * Normalisiert die Nummer für den Vergleich: Leerzeichen, Bindestriche,
     * Klammern raus; internationale Schreibweisen vereinheitlicht —
     * 0049… / +49… / 0… (national) / 49… (Landesvorwahl ohne +) werden
     * gleichwertig als 49… verglichen. Nicht-DE-Vorwahlen (+41…) bleiben
     * unangetastet (nur 00→+).
     */
    private String normalize(String num)
    {
        if (num == null) return "";
        num = num.replaceAll("[\\s\\-()]+", "");
        if (num.startsWith("00") && num.length() > 2)
        {
            num = "+" + num.substring(2);
        }
        if (num.startsWith("0") && num.length() > 1)
        {
            num = "49" + num.substring(1);
        }
        if (num.startsWith("+49"))
        {
            num = num.substring(1);
        }
        return num;
    }

    /**
     * Prüft, ob die Anrufernummer mit einem der Wildcard-Muster übereinstimmt.
     *
     * Verwendet den ORIGINALEN STARFACE-SimpleMatch-Baustein (wie das
     * Referenzmodul "Blacklist v64"): Ein Muster wird per
     * RegExpUtil.convertSimpleRegexpToJava() in ein Java-Regex übersetzt,
     * dann text.matches() — '*'-Wildcard steht für 0..n Zeichen, '?' für
     * genau ein Zeichen, der GESAMTE Text muss matchen.
     *
     * Verglichen wird 1) gegen die RAW-Anrufernummer (callerSignallingNumber)
     * und 2) als Fallback gegen die normalisierte Form (49…-Schreibweise,
     * deckt Anlagen ab, die nationale 0…/0049…-Formate liefern).
     */
    private boolean matchesAny(IAGIRuntimeEnvironment context,
                              String rawNumber, String normalizedNumber,
                              List<String> patterns)
    {
        for (String p : patterns)
        {
            if (p == null || p.trim().isEmpty())
            {
                continue;
            }
            if (simpleMatch(context, rawNumber, p)
                || (!normalizedNumber.equals(rawNumber)
                    && simpleMatch(context, normalizedNumber, p)))
            {
                logAll(context, "INFO", "BLOCKLIST-MATCH: Muster '" + p
                       + "' traf auf '" + rawNumber + "'");
                return true;
            }
            else
            {
                logAll(context, "INFO", "CallBlocker: Muster '" + p
                       + "' -> kein Match (RAW='" + rawNumber
                       + "', norm='" + normalizedNumber + "')");
            }
        }
        return false;
    }

    /**
     * Schreibt eine Meldung in das MODUL-Log über den dokumentierten
     * Log2-Baustein (API-Doku: „Logs a message to the module log file.
     * Additionally, error messages will be appended to the STARFACE error
     * log." — exakt wie das Referenzmodul "Blacklist v64"). Erscheint im
     * Modul-/Instanz-Log der Admin-UI. HINWEIS: context.getLog() ist KEIN
     * Schreib-Baustein (nur ein Getter) — alle Ausgaben laufen hier
     * ausschließlich über Log2. level: DEBUG, INFO, WARN, ERROR.
     */
    private void logAll(IAGIRuntimeEnvironment context, String level, String msg)
    {
        try
        {
            Log2 l = new Log2();
            l.logLevel = level;
            l.messages = Collections.singletonList(msg);
            l.execute(context);
        }
        catch (Exception e1)
        {
            // Log-Fehler darf den Anrufpfad nie stören — bewusst still
        }
    }

    /** Führt den STARFACE-SimpleMatch-Baustein direkt aus (wie Referenzmodul). */
    private boolean simpleMatch(IAGIRuntimeEnvironment context,
                                String text, String pattern)
    {
        try
        {
            SimpleMatch sm = new SimpleMatch();
            sm.text = text;
            sm.pattern = pattern;
            sm.execute(context);
            return Boolean.TRUE.equals(sm.matches);
        }
        catch (Exception e)
        {
            logAll(context, "ERROR", "SimpleMatch-Fehler bei Muster '"
                   + pattern + "' gegen '" + text + "': "
                   + e.getClass().getName() + ": " + e.getMessage());
            return false;
        }
    }
}