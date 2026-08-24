/*
 * ListManager — Lese-/Schreib-Zugriff auf blocklist.txt.
 *
 * Speichert eine Nummer pro Zeile; Zeilen mit # werden als Kommentare ignoriert.
 * Die Datei liegt im Instanz-Datenverzeichnis (getInstanceDataDir()) der
 * STARFACE-Modul-Instanz — verifizierter API-Weg (STARFACE-intern genutzt
 * von io/FileFunction, Implementierung RuntimeEnvironmentImpl).
 *
 * NICHT verwenden: System.getenv("STARFACE_MODULE_ID") (wird von STARFACE
 * nicht gesetzt) und nicht /tmp (alle Instanzen teilen eine Datei, nicht
 * persistent). Seit v4 wird jede Ausführung protokolliert (Pfad + Anzahl +
 * Fehler mit Stacktrace), damit man im Instanz-Log sieht, was passiert.
 */

import java.io.*;
import java.nio.file.*;
import java.util.*;

import org.apache.logging.log4j.Logger;

import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.VariableScope;

public class ListManager
{
    /**
     * ID der Modul-GUI-Variable "Geblockte Nummern" (declariert im
     * module-descriptor.xml als GUI_BLOCKED_NUMBERS, type LIST; gebunden an
     * die textList im inputGUITabs-Tab "Geblockte Nummern").
     */
    public static final String GUI_BLOCKED_NUMBERS_VAR_ID =
        "c4d5e6f7-8a9b-4c0d-8e1f-2a3b4c5d6e7f";

    /** Pfad zur blocklist.txt im Instanz-Datenverzeichnis. */
    public static File getBlocklistFile(IRuntimeEnvironment context)
    {
        return new File(context.getInstanceDataDir(), "blocklist.txt");
    }

    /** Liest die blocklist.txt und gibt die Einträge zurück. */
    public static List<String> loadBlocklist(IRuntimeEnvironment context, Logger log)
    {
        List<String> entries = new ArrayList<>();
        File f = getBlocklistFile(context);

        if (!f.exists())
        {
            log.info("ListManager: blocklist.txt existiert noch nicht: "
                     + f.getAbsolutePath() + " (Liste leer)");
            return entries;
        }

        try
        {
            List<String> lines = Files.readAllLines(f.toPath());
            for (String line : lines)
            {
                line = line.trim();
                if (!line.isEmpty() && !line.startsWith("#"))
                {
                    entries.add(line);
                }
            }
            log.info("ListManager: " + entries.size() + " Einträge aus "
                     + f.getAbsolutePath() + " gelesen");
        }
        catch (IOException e)
        {
            log.error("ListManager: Lesefehler für " + f.getAbsolutePath(), e);
        }
        return entries;
    }

    /** Speichert die Liste (alle Einträge werden neu geschrieben). */
    public static void saveBlocklist(List<String> entries, IRuntimeEnvironment context, Logger log)
    {
        File f = getBlocklistFile(context);
        File dir = f.getParentFile();
        if (dir != null && !dir.exists())
        {
            dir.mkdirs();
        }

        try
        {
            StringBuilder sb = new StringBuilder();
            for (String entry : entries)
            {
                sb.append(entry).append("\n");
            }
            Files.write(f.toPath(), sb.toString().getBytes());
            log.info("ListManager: " + entries.size() + " Einträge nach "
                     + f.getAbsolutePath() + " geschrieben (" + sb.length() + " Bytes)");

            // GUI-Tab "Geblockte Nummern" in der Modul-Instanz aktuell halten
            syncGuiList(context, log);
        }
        catch (IOException e)
        {
            log.error("ListManager: Schreibfehler für " + f.getAbsolutePath(), e);
        }
    }

    /**
     * Schreibt den aktuellen Inhalt der blocklist.txt in die Modul-GUI-Variable
     * "Geblockte Nummern" (Instanz-Scope) — so zeigt der gleichnamige Tab in
     * der Modul-Instanz-Konfiguration der STARFACE-Verwaltung den aktuellen Stand.
     *
     * Kanonischer Weg: context.getScope(VariableScope.Instance) — STARFACE-intern
     * genauso von GetVariableValue2 genutzt (Bytecode-verifiziert, 10.0.2.5).
     */
    public static void syncGuiList(IRuntimeEnvironment context, Logger log)
    {
        try
        {
            List<String> entries = loadBlocklist(context, log);
            context.getScope(VariableScope.Instance)
                   .put(GUI_BLOCKED_NUMBERS_VAR_ID, entries);
            log.info("ListManager: GUI-Variable '" + GUI_BLOCKED_NUMBERS_VAR_ID
                     + "' aktualisiert (" + entries.size() + " Einträge)");
        }
        catch (Exception e)
        {
            log.warn("ListManager: GUI-Sync fehlgeschlagen", e);
        }
    }

    /** Entfernt bestimmte Nummern aus der Blocklist. */
    public static void removeBlocklistEntries(List<String> toRemove,
                                              IRuntimeEnvironment context, Logger log)
    {
        List<String> entries = loadBlocklist(context, log);
        entries.removeAll(toRemove);
        saveBlocklist(entries, context, log);
    }
}
