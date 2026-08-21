/*
 * ListManager — Lese-/Schreib-Zugriff auf blocklist.txt.
 *
 * Speichert eine Nummer pro Zeile; Zeilen mit # werden als Kommentare ignoriert.
 * Die Datei liegt im Instanz-Ordner unter res/blocklist.txt.
 */

import java.io.*;
import java.nio.file.*;
import java.util.*;

public class ListManager
{
    /** Liest die blocklist.txt und gibt die Einträge zurück. */
    public static List<String> loadBlocklist()
    {
        List<String> entries = new ArrayList<>();
        File f = getBlocklistFile();

        if (!f.exists())
        {
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
        }
        catch (IOException e)
        {
            // Kann nicht geloggt werden — keine Log-Referenz hier
        }
        return entries;
    }

    /** Speichert die Liste (alle Einträge werden neu geschrieben). */
    public static void saveBlocklist(List<String> entries)
    {
        File f = getBlocklistFile();
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
        }
        catch (IOException e)
        {
            // Kann nicht geloggt werden
        }
    }

    /** Entfernt bestimmte Nummern aus der Blocklist. */
    public static void removeBlocklistEntries(List<String> toRemove)
    {
        List<String> entries = loadBlocklist();
        entries.removeAll(toRemove);
        saveBlocklist(entries);
    }

    /** Pfad zur blocklist.txt. */
    private static File getBlocklistFile()
    {
        String instanzId = System.getenv("STARFACE_MODULE_ID");
        if (instanzId != null && !instanzId.isEmpty())
        {
            return new File("/var/starface/module/instances/repo/" + instanzId + "/res/blocklist.txt");
        }
        return new File("/tmp/blocklist-unknown.txt");
    }
}