/*
 * ListRemove — XML-RPC Entrypoint: entfernt Nummern aus der Blocklist.
 * Aufrufname: [Instanzname].ListRemove
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
          description = "Entfernt Nummern aus der Blocklist.")
public class ListRemove implements IBaseExecutable
{
    @InputVar(label = "Nummern", description = "Komma-getrennte Liste der zu entfernenden Nummern",
              type = VariableType.STRING)
    public String INPUT_NUMMERN = "";

    @OutputVar(label = "Entfernt", description = "Anzahl erfolgreich entfernter Nummern",
               type = VariableType.NUMBER)
    public Integer OUTPUT_ANZAHL = 0;

    @Override
    public void execute(IRuntimeEnvironment context) throws Exception
    {
        Logger log = context.getLog();
        if (INPUT_NUMMERN.isEmpty())
        {
            OUTPUT_ANZAHL = 0;
            log.info("ListRemove: leere Eingabe — nichts zu tun");
            return;
        }

        String[] nummern = INPUT_NUMMERN.split(",");
        List<String> toRemove = new ArrayList<>();
        for (String n : nummern)
        {
            n = n.trim();
            if (!n.isEmpty())
            {
                toRemove.add(n);
            }
        }

        ListManager.removeBlocklistEntries(toRemove, context, log);
        OUTPUT_ANZAHL = toRemove.size();
        log.info("ListRemove: " + toRemove.size() + " Nummern entfernt");
    }
}
