/*
 * ListAdd — XML-RPC Entrypoint: fügt Nummern zur Blocklist hinzu.
 * Aufrufname: [Instanzname].ListAdd
 */

import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.InputVar;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import org.apache.logging.log4j.Logger;

import java.util.ArrayList;
import java.util.List;

@Function(visibility = Visibility.Public, rookieFunction = false,
          description = "Fügt Nummern zur Blocklist hinzu.")
public class ListAdd implements IBaseExecutable
{
    @InputVar(label = "Nummern", description = "Komma-getrennte Liste der hinzuzufügenden Nummern",
              type = VariableType.STRING)
    public String INPUT_NUMMERN = "";

    @OutputVar(label = "Hinzugefügt", description = "Anzahl erfolgreich hinzugefügter Nummern",
               type = VariableType.NUMBER)
    public Integer OUTPUT_ANZAHL = 0;

    @Override
    public void execute(IRuntimeEnvironment context) throws Exception
    {
        Logger log = context.getLog();
        if (INPUT_NUMMERN.isEmpty())
        {
            OUTPUT_ANZAHL = 0;
            log.info("ListAdd: leere Eingabe — nichts zu tun");
            return;
        }

        String[] nummern = INPUT_NUMMERN.split(",");
        List<String> valid = new ArrayList<>();
        for (String n : nummern)
        {
            n = n.trim();
            if (!n.isEmpty() && !n.startsWith("#"))
            {
                valid.add(n);
            }
        }

        // v23-Fix: bestehende Liste LADEN und neue Nummern ANHÄNGEN.
        // Vorher wurde nur `valid` übergeben und saveBlocklist() setzte die
        // komplette ListResource auf diese Werte ⇒ alle vorhandenen Einträge
        // wurden überschrieben („nur der letzte bleibt behalten“).
        List<String> existing = ListManager.loadBlocklist(context, log);
        int added = 0;
        for (String n : valid)
        {
            if (existing.contains(n))
            {
                log.info("ListAdd: Nummer '" + n + "' bereits in der Liste — übersprungen");
            }
            else
            {
                existing.add(n);
                added++;
            }
        }
        ListManager.saveBlocklist(existing, context, log);
        // OUTPUT_ANZAHL = Anzahl verarbeiteter Eingaben (nicht nur neuer),
        // damit die WebApp keine Fehlanzeige „Bestätigung 0“ bei Duplikaten meldet.
        OUTPUT_ANZAHL = valid.size();
        log.info("ListAdd: " + valid.size() + " Nummern verarbeitet, "
                 + added + " neu angehängt (Liste gesamt: " + existing.size() + ")");
    }
}
