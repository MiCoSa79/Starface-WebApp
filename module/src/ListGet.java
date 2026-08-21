/*
 * ListGet — XML-RPC Entrypoint: gibt alle Blocklist-Einträge zurück.
 * Aufrufname: [Instanzname].ListGet
 */

import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.InputVar;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;

import java.util.List;

@Function(visibility = Visibility.Public, rookieFunction = false,
          description = "Gibt alle Nummern der Blocklist zurück.")
public class ListGet implements IBaseExecutable
{
    @InputVar(label = "", description = "", type = VariableType.STRING)
    public String INPUT_DEFAULT = "";

    @OutputVar(label = "Nummern", description = "Komma-getrennte Liste aller Nummern",
               type = VariableType.STRING)
    public String OUTPUT_NUMMERN = "";

    @Override
    public void execute(IRuntimeEnvironment context) throws Exception
    {
        List<String> entries = ListManager.loadBlocklist();
        OUTPUT_NUMMERN = String.join(",", entries);
    }
}