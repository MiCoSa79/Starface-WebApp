import java.util.Collections;
import java.util.List;

import de.vertico.starface.module.core.ModuleRegistry;
import de.vertico.starface.module.core.model.Module;
import de.vertico.starface.module.core.model.ModuleInstance;
import de.vertico.starface.module.core.model.ModuleInstanceProject;
import de.vertico.starface.module.core.model.ModuleInstanceRO;
import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.InputVar;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import de.vertico.starface.module.core.runtime.functions.system.Log2;

/**
 * Deployment-Modul v9 (dm-v9): legt eine neue Instanz eines installierten
 * Moduls an (RPC "CreateInstance").
 *
 * Ablauf (javap-verifiziert, Muster: Admin Power Pack CREATE_INSTANCE):
 *   1. Modul-ID per Modulnamen aus ModuleRegistry.getModules() (eingebaute
 *      Module ohne Vendor/Version werden ignoriert)
 *   2. Kollisionscheck gegen getInstalledInstances() (gleiche Modul-ID +
 *      Instanzname) — getInstanceByName ist package-private!
 *   3. createModuleInstance(moduleId) -> setName -> updateModuleInstance
 *      (persistieren) -> activateModuleInstance(proj, true) (sofort START)
 *
 * Antwort im Output "response": "OK: ..." oder "ERROR: ..." — die WebApp
 * wertet das Prefix aus. Log2 NUR bei unerwarteten Exceptions (Sparsamkeit).
 */
@Function(visibility=Visibility.Private, rookieFunction=false,
          description="Legt eine neue Instanz eines installierten Moduls an (ModuleRegistry.createModuleInstance + setName + update + activate).")
public class InstanzAnlegen implements IBaseExecutable
{
    @InputVar(label="moduleName", description="Name des Zielmoduls", type=VariableType.STRING)
    public String moduleName = "";

    @InputVar(label="instanceName", description="Name der neuen Instanz", type=VariableType.STRING)
    public String instanceName = "";

    @OutputVar(label="response", description="OK: ... oder ERROR: ...", type=VariableType.STRING)
    public String response = "";

    @Override
    public void execute(IRuntimeEnvironment context) throws Exception
    {
        try
        {
            if (moduleName == null || moduleName.trim().isEmpty())
            {
                response = "ERROR: moduleName leer";
                return;
            }
            if (instanceName == null || instanceName.trim().isEmpty())
            {
                response = "ERROR: instanceName leer";
                return;
            }
            String modName = moduleName.trim();
            String instName = instanceName.trim();

            ModuleRegistry MR = (ModuleRegistry) context.springApplicationContext().getBean(ModuleRegistry.class);

            // 1) Modul-ID per Namen (eingebaute Module ohne Vendor/Version ausfiltern)
            String moduleId = null;
            List<Module> modules = MR.getModules();
            if (modules != null)
            {
                for (Module m : modules)
                {
                    if (m == null) continue;
                    if (m.getVersion() == 0L && m.getVendor() != null && m.getVendor().isEmpty()) continue;
                    if (modName.equals(m.getName()))
                    {
                        moduleId = m.getId();
                        break;
                    }
                }
            }
            if (moduleId == null)
            {
                response = "ERROR: Modul nicht installiert: " + modName;
                return;
            }

            // 2) Kollisionscheck (nur innerhalb desselben Moduls)
            List<ModuleInstanceRO> instances = MR.getInstalledInstances();
            if (instances != null)
            {
                for (ModuleInstanceRO mi : instances)
                {
                    if (mi == null) continue;
                    if (moduleId.equals(mi.getModuleId()) && instName.equals(mi.getName()))
                    {
                        response = "ERROR: Instanz existiert bereits: " + instName;
                        return;
                    }
                }
            }

            // 3) Anlegen + benennen + persistieren + sofort aktivieren
            ModuleInstanceProject proj = MR.createModuleInstance(moduleId);
            ModuleInstance inst = proj.getObject();
            inst.setName(instName);
            MR.updateModuleInstance(proj);
            MR.activateModuleInstance(proj, true);

            response = "OK: Instanz " + instName + " fuer Modul " + modName + " angelegt und aktiviert";
        }
        catch (Exception e)
        {
            response = "ERROR: " + e.getClass().getSimpleName() + ": " + e.getMessage();
            try
            {
                Log2 l = new Log2();
                l.logLevel = "ERROR";
                l.messages = Collections.singletonList("InstanzAnlegen: " + e);
                l.execute(context);
            }
            catch (Exception ignore)
            {
                // Log-Fehler darf die Antwort nicht verfälschen
            }
        }
    }
}
