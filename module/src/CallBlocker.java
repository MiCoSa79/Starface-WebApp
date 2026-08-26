import java.util.ArrayList;
import java.util.List;
import java.util.Collections;

import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IAGIJavaExecutable;
import de.vertico.starface.module.core.runtime.IAGIRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.InputVar;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import de.vertico.starface.module.core.runtime.functions.callHandling.call.GetCaller2;
import de.vertico.starface.module.core.runtime.functions.callHandling.call.Hangup;
import de.vertico.starface.module.core.runtime.functions.lang.string.regexp.SimpleMatch;
import de.vertico.starface.module.core.runtime.functions.system.Log2;

/**
 * CallBlocker — weist Anrufe unerwünschter Rufnummern ab.
 *
 * Ablauf (Blacklist-v64-Muster, v29):
 *   1. Caller-ID ermitteln: GetCaller2 → callerSignallingNumber
 *   2. foreach über alle Listeneinträge der Modul-Liste (GUI_GEBLOCKTE_RUFNUMMERN,
 *      wird vom Modul-Editor an den @InputVar Blocklist verdrahtet)
 *   3. Vergleich per originalem STARFACE-SimpleMatch (Wildcard '*' = 0..n Zeichen,
 *      '?' = genau 1, kompletter String-Match)
 *   4. Beim ersten Treffer: Schleife beenden, hangup (Hangup-Baustein, nutzt den
 *      aktiven Call des Threads) und GENAU EINE Logzeile:
 *      „Anruf von der Rufnummer <Nummer> wurde geblockt“ (Vorgabe Axel, v29:
 *      Log nur noch einzeilig und nur bei Treffern — kein sonstiges Logging).
 *   5. Kein Treffer: Anruf läuft unangetastet weiter, kein Log.
 *
 * Kompilieren (JDK21, Klassen der VM-Edition 10.0.2.5 = Version 65.0):
 *   javac -cp "classes:<PATH>/WEB-INF/classes:<PATH>/WEB-INF/lib/*" CallBlocker.java
 *
 * @author si.module
 */
@Function(visibility = Visibility.Public, rookieFunction = false,
          description = "Weist Anrufe von Rufnummern in der Blocklist ab.")
public class CallBlocker implements IAGIJavaExecutable
{
    // Liste der geblockten Rufnummern — kommt aus dem Modul:
    // Modul-Variable GUI_GEBLOCKTE_RUFNUMMERN (LIST, an die ListResource gebunden)
    @InputVar(label = "Blocklist",
              description = "Liste der geblockten Rufnummern",
              type = VariableType.LIST)
    public List<String> Blocklist = new ArrayList<String>();

    @OutputVar(label = "BlockStatus",
               description = "BlockStatus ist true wenn der Anruf blockiert wurde, false sonst",
               type = VariableType.BOOLEAN)
    public boolean BlockStatus = false;

    @Override
    public void execute(IAGIRuntimeEnvironment context) throws Exception
    {
        // 1) Caller-ID ermitteln (integrierter GetCaller2-Baustein)
        String callerNumber = resolveCallerNumber(context);
        if (callerNumber == null || callerNumber.isEmpty())
        {
            BlockStatus = false;
            return;
        }

        // 2) foreach über alle Listeneinträge — SimpleMatch gegen die RAW-Nummer
        if (Blocklist == null)
        {
            BlockStatus = false;
            return;
        }

        for (String pattern : Blocklist)
        {
            if (pattern == null || pattern.trim().isEmpty())
            {
                continue;
            }
            if (simpleMatch(context, callerNumber, pattern))
            {
                // 3) Treffer: aufhören weiter zu prüfen → hangup + genau EINE
                //    Logzeile (Vorgabe v29: nur bei Treffern, nur einzeilig)
                try
                {
                    Hangup hangup = new Hangup();
                    hangup.execute(context);
                    logAll(context, "INFO", "Anruf von der Rufnummer " + callerNumber
                           + " wurde geblockt");
                    BlockStatus = true;
                    return;
                }
                catch (Exception e)
                {
                    // Hangup-Fehler: Anruf wurde nicht abgewiesen — bewusst
                    // ohne Log (Vorgabe: Log nur bei Treffern)
                }
            }
        }

        // 4) Kein Treffer: nichts tun — Anruf läuft normal weiter, kein Log
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
     * Führt den ORIGINALEN STARFACE-SimpleMatch-Baustein direkt aus (wie das
     * Referenzmodul "Blacklist v64"): pattern wird per
     * RegExpUtil.convertSimpleRegexpToJava() in ein Java-Regex übersetzt, dann
     * text.matches() — '*'-Wildcard = 0..n Zeichen, '?' = genau ein Zeichen,
     * der GESAMTE Text muss matchen.
     */
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
            return false;
        }
    }

    /**
     * Schreibt eine Meldung in das MODUL-Log über den dokumentierten
     * Log2-Baustein (API-Doku: „Logs a message to the module log file.").
     * Hinweis: context.getLog() ist KEIN Schreib-Baustein (nur Getter) —
     * alle Ausgaben laufen ausschließlich über Log2. level: DEBUG, INFO,
     * WARN, ERROR.
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
}
