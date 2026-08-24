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

        // Kein aktiver Kanal? → nichts tun
        if (channel == null || channel.isEmpty())
        {
            return;
        }

        // 1) Anrufernummer auflösen
        String callerNumber = resolveCallerNumber(context);
        if (callerNumber == null)
        {
            log.debug("CallBlocker: keine Anrufernummer gefunden");
            return;
        }

        String normalized = normalize(callerNumber);
        if (normalized.isEmpty())
        {
            log.debug("CallBlocker: nummer nach Normalisierung leer");
            return;
        }

        // 2) Blocklist laden
        List<String> patterns = loadBlocklist(context, log);

        // 3) Prüfen
        log.info("CallBlocker: prüfe Anruf von " + callerNumber
                 + " (normalisiert: " + normalized + ") gegen "
                 + patterns.size() + " Muster");
        if (matchesAny(normalized, patterns))
        {
            // 4) Abweisen + Log
            ModuleBusinessObject MBO = (ModuleBusinessObject)
                context.springApplicationContext().getBean(ModuleBusinessObject.class);
            MBO.hangup(channel, HangupCause.NORMAL_CLEARING);
            log.info("BLOCKED: Anruf von " + callerNumber + " (normalisiert: "
                     + normalized + ") abgewiesen (Blocklist)");
            BlockStatus = true;
            return;
        }
        // Kein Treffer: nichts weiter tun — Route läuft normal weiter
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

    /** Liest die blocklist.txt aus dem Instanz-Datenverzeichnis oder aus dem angegebenen Pfad. */
    private List<String> loadBlocklist(IAGIRuntimeEnvironment context, Logger log)
    {
        List<String> entries = new ArrayList<>();
        File f = getBlocklistFile(context);

        if (!f.exists())
        {
            log.warn("CallBlocker: blocklist.txt nicht gefunden: " + f.getAbsolutePath());
            return entries;
        }

        try
        {
            List<String> lines = java.nio.file.Files.readAllLines(f.toPath());
            for (String line : lines)
            {
                line = line.trim();
                if (!line.isEmpty() && !line.startsWith("#"))
                {
                    entries.add(line);
                }
            }
        }
        catch (IOException e)
        {
            log.error("CallBlocker: Fehler beim Lesen der Blocklist: "
                      + f.getAbsolutePath(), e);
        }
        return entries;
    }

    /** Ermittelt den Pfad zur blocklist.txt — immer Instanz-Datenverzeichnis. */
    private File getBlocklistFile(IAGIRuntimeEnvironment context)
    {
        // Fix: Instanz-Datenverzeichnis (verifizierter API-Weg, seit v4 — vorher
        // System.getenv("STARFACE_MODULE_ID") + /tmp-Fallback, beides falsch).
        // Der frühere @InputVar "Blocklist-Pfad" ist entfernt (v5): Entrypoint-
        // Funktionen dürfen keine Eingabevariablen haben, und ein getrennter
        // Pfad würde zudem von ListManager (RPCs) nicht geschrieben.
        return new File(context.getInstanceDataDir(), "blocklist.txt");
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

    /** Prüft, ob eine Zahl mit einem der Wildcard-Muster übereinstimmt. */
    private boolean matchesAny(String number, List<String> patterns)
    {
        for (String p : patterns)
        {
            // Muster ebenfalls normalisieren: +49*, 0049*, 0162*, 4916* → 49…
            String pattern = normalize(p);
            if (pattern.isEmpty())
            {
                continue;
            }
            if (matchNumber(number, pattern)) return true;
        }
        return false;
    }

    /**
     * Ein Wildcard-Muster gegen eine Zahl prüfen.
     *
     * +41*  → beginnt mit +41
     * 004912345678 (bzw. +4912345678, 012345678, 4912345678)  → exakte Übereinstimmung
     * 2??  → beginnt mit 2, dann genau 2 weitere Zeichen
     * ???  → genau 3 Zeichen, jedes beliebig
     * *9162  → endet mit 9162 (Suffix-Wildcard, egal welche Vorwahl)
     * +49*80 → beginnt mit +49, endet mit 80 (als Suffix: +49* → beginnt, +80 → endet)
     */
    private boolean matchNumber(String number, String pattern)
    {
        // 1) Exakte Übereinstimmung
        if (number.equals(pattern)) return true;

        // 2) Wildcard-Suffix (+41*, 49*)
        if (pattern.endsWith("*") && pattern.length() > 1)
        {
            return number.startsWith(pattern.substring(0, pattern.length() - 1));
        }

        // 3) ?-Platzhalter (2??, ???)
        if (pattern.contains("?"))
        {
            if (number.length() != pattern.length()) return false;
            for (int i = 0; i < pattern.length(); i++)
            {
                if (pattern.charAt(i) != '?' && pattern.charAt(i) != number.charAt(i))
                    return false;
            }
            return true;
        }

        // 4) Suffix-Match mit + und * (+41*80 → endet mit 80)
        if (pattern.startsWith("+") && pattern.contains("*"))
        {
            // +41*80 → prefix = +41, suffix = 80
            int star = pattern.indexOf('*');
            String prefix = pattern.substring(0, star);
            String suffix = pattern.substring(star + 1);
            if (suffix.isEmpty()) return false;
            return number.startsWith(prefix) && number.endsWith(suffix);
        }

        // 5) Führender Stern (*9162 → endet mit 9162)
        if (pattern.startsWith("*") && pattern.length() > 1)
        {
            return number.endsWith(pattern.substring(1));
        }

        return false;
    }
}