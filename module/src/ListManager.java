/*
 * ListManager — Lese-/Schreib-Zugriff auf die textList der Modul-Instanz.
 *
 * Seit v22 ist die ListResource der Instanz die EINZIGE Datenquelle
 * (kein blocklist.txt-Dateiumweg mehr). Der Zugriff bildet exakt den
 * Weg des Instanz-Editors ab (bytecode-verifiziert, STARFACE 10.0.2.5,
 * Klassen MultiValueConfig.setValues + ConfigurableFactory.buildConfig):
 *
 *   1) variable.getValue()  = ID der ListResource (im Descriptor:
 *      <value>56f65b6e-f5e5-49ad-9dc4-53bf7c4e97a8</value>)
 *   2) instance.getListResource(id) -> ListResource
 *      (bei null: neue Resource anlegen + in instance.getResources() aufnehmen)
 *   3) lr.setValues(elements)
 *   4) variable.setValue(lr.getId())  — Variable zeigt auf die Resource
 *   5) runtime.updateModuleInstance(project) — persistiert instance-config.xml
 *
 * Der Instanz-Editor LÄDT die textList über denselben Weg
 * (instance.getListResource(variable.getValue())), daher erscheinen die
 * Werte sofort im Tab "Geblockte Rufnummern".
 *
 * VORHER (v4-v21): blocklist.txt im Instanz-Datenverzeichnis — der GUI-Tab
 * blieb leer, weil der Editor die Resource über die Variablen-ID adressiert,
 * nicht über den Variablennamen (v21-Fehler: getListResource(VAR_NAME)).
 */

import java.io.*;
import java.util.*;

import org.apache.logging.log4j.Logger;

import de.vertico.starface.module.core.model.ModuleInstance;
import de.vertico.starface.module.core.model.ModuleInstanceProject;
import de.vertico.starface.module.core.model.Variable;
import de.vertico.starface.module.core.model.resource.ListResource;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.ModuleRuntime;

public class ListManager
{
    /**
     * Name der Modul-GUI-Variable (declariert in module-descriptor.xml unter
     * module/inputVars, type LIST; gebunden an die textList im inputGUITabs-Tab
     * "Geblockte Rufnummern"). Der Name/ID-Satz stammt aus dem STARFACE-Designer-
     * Export (kanonisches Format, Descriptor version=15).
     */
    public static final String GUI_BLOCKED_NUMBERS_VAR_NAME = "GUI_GEBLOCKTE_RUFNUMMERN";
    public static final String GUI_BLOCKED_NUMBERS_VAR_ID =
        "c42f4bb5-dfa4-42bb-b907-1aae15471d1d";

    /** Liest die Blocklist aus der ListResource der Instanz. */
    public static List<String> loadBlocklist(IRuntimeEnvironment context, Logger log)
    {
        List<String> entries = new ArrayList<>();
        try
        {
            ModuleInstance mi = getModuleInstance(context, log);
            if (mi == null)
            {
                return entries;
            }

            Variable var = mi.getInputVar(GUI_BLOCKED_NUMBERS_VAR_NAME);
            if (var == null)
            {
                log.warn("ListManager: Variable '" + GUI_BLOCKED_NUMBERS_VAR_NAME
                         + "' nicht gefunden");
                return entries;
            }

            ListResource lr = getListResourceForVariable(mi, var);
            if (lr == null)
            {
                log.info("ListManager: keine ListResource für Variable '"
                         + GUI_BLOCKED_NUMBERS_VAR_NAME + "' — Liste leer");
                return entries;
            }

            List<String> values = lr.getValues();
            if (values != null)
            {
                entries.addAll(values);
            }
            log.info("ListManager: " + entries.size()
                     + " Einträge aus ListResource gelesen (ID=" + lr.getId() + ")");
        }
        catch (Exception e)
        {
            log.error("ListManager: Lesefehler aus ListResource", e);
        }
        return entries;
    }

    /** Speichert die Liste (alle Einträge werden neu geschrieben). */
    public static void saveBlocklist(List<String> entries, IRuntimeEnvironment context,
                                     Logger log)
    {
        try
        {
            ModuleInstance mi = getModuleInstance(context, log);
            if (mi == null)
            {
                return;
            }

            Variable var = mi.getInputVar(GUI_BLOCKED_NUMBERS_VAR_NAME);
            if (var == null)
            {
                log.warn("ListManager: Variable '" + GUI_BLOCKED_NUMBERS_VAR_NAME
                         + "' nicht gefunden — nichts geschrieben");
                return;
            }

            // Editor-Weg: ListResource über die ID aus variable.getValue()
            ListResource lr = getListResourceForVariable(mi, var);
            if (lr == null)
            {
                lr = new ListResource();
                lr.setName(GUI_BLOCKED_NUMBERS_VAR_NAME);
                mi.addResource(lr);
                log.info("ListManager: neue ListResource angelegt (Name="
                         + GUI_BLOCKED_NUMBERS_VAR_NAME + ")");
            }

            lr.setValues(entries);
            // Variable auf die Resource verweisen lassen (Editor macht das
            // identisch: Variable.setValue(ListResource.getId()))
            if (!Objects.equals(var.getValue(), lr.getId()))
            {
                var.setValue(lr.getId());
            }

            // Persistieren: schreibt instance-config.xml + feuert InstanceUpdated
            ModuleRuntime runtime =
                context.springApplicationContext().getBean(ModuleRuntime.class);
            ModuleInstanceProject project = new ModuleInstanceProject(mi);
            runtime.updateModuleInstance(project);

            log.info("ListManager: " + entries.size()
                     + " Eintraege in ListResource geschrieben (ID=" + lr.getId() + ")");
        }
        catch (Exception e)
        {
            log.error("ListManager: Schreibfehler in ListResource", e);
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

    // ##########################################################################################
    // Interne Helfer

    /** Holt die Modul-Instanz aus dem InvocationInfo. */
    private static ModuleInstance getModuleInstance(IRuntimeEnvironment context, Logger log)
    {
        try
        {
            ModuleInstance mi = context.getInvocationInfo().getModuleInstance();
            if (mi == null)
            {
                log.warn("ListManager: getInvocationInfo().getModuleInstance() == null");
            }
            return mi;
        }
        catch (Exception e)
        {
            log.warn("ListManager: getModuleInstance fehlgeschlagen", e);
            return null;
        }
    }

    /**
     * Besorgt die ListResource, auf die die Variable zeigt (Editor-Weg:
     * variable.getValue() = Resource-ID). Fällt auf die Modul-Default-Resource
     * zurück, falls die Instanz noch keine eigene hat.
     */
    private static ListResource getListResourceForVariable(ModuleInstance mi, Variable var)
    {
        String resId = var.getValue();
        if (resId != null && !resId.isEmpty())
        {
            ListResource lr = mi.getListResource(resId);
            if (lr != null)
            {
                return lr;
            }
        }
        return null;
    }
}
