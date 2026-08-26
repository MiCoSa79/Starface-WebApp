import java.util.Collections;
import java.util.List;

import de.vertico.starface.module.core.ModuleRegistry;
import de.vertico.starface.module.core.model.Module;
import de.vertico.starface.module.core.model.ModuleInstanceRO;
import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import de.vertico.starface.module.core.runtime.functions.system.Log2;

/**
 * Telefonie-Monitoring: liefert alle installierten Module mit Version, Vendor
 * und Instanz-Status (aktiv/deaktiviert) als JSON-String. Die WebApp gleicht
 * diese IST-Daten mit den SOLL-Modulen (app/modules/*.sfm) ab.
 *
 * API-Quelle (offizielles SFWiki-Beispiel GetAllModules.java) — ABER FALLE:
 *   MR.getInstances4Module(id) ist im Interface ModuleRegistry deklariert, wird
 *   von ModuleRegistryBase (Implementierung der Anlage) NICHT implementiert ->
 *   Laufzeit-Fault "No item with that key" (Befund 2026-08-26, Testanlage).
 *   FIX: Instanzen aus MR.getInstalledInstances() (ModuleInstanceRO: getModuleId/
 *   getName/getDisabled — javap-verifiziert an der Extraktion) per getModuleId()
 *   dem Modul zuordnen. Schutz: module-monitoring/verify_api_refs.py prüft jede
 *   gerufene de.vertico-Methode gegen die Implementierungsklassen.
 *
 * Antwortformat (JSON, Output "moduleJson"):
 *   [{"id":"...","name":"CallBlocker","version":28,"vendor":"MiCoSa79",
 *     "instances":[{"name":"CallBlocker","disabled":false}]}]
 * Bei internem Fehler: {"error":"<meldung>"} — die WebApp unterscheidet das
 * von der leeren Liste "[]" (Modul installiert, aber keine Module gemeldet).
 */
@Function(visibility=Visibility.Private, rookieFunction=false,
          description="Liefert installierte Module (Name, Version, Vendor) mit Instanz-Status als JSON fuer den WebApp-Modulabgleich.")
public class ModuleStatus implements IBaseExecutable
{
	@OutputVar(label="moduleJson", description="JSON-Array aller installierten Module (eingebaute ohne Version/Vendor ausgenommen): [{id,name,version,vendor,instances:[{name,disabled}]}]", type=VariableType.STRING)
	public String moduleJson = "[]";

	@Override
	public void execute(IRuntimeEnvironment context) throws Exception
	{
		try {
			ModuleRegistry MR = (ModuleRegistry) context.springApplicationContext()
					.getBean(ModuleRegistry.class);

			StringBuilder sb = new StringBuilder("[");
			boolean first = true;
			for (Module M : MR.getModules()) {
				Long ver = M.getVersion();
				String vendor = M.getVendor();
				// Eingebaute Module (keine Version, kein Vendor) ueberspringen —
				// exakt das offizielle GetAllModules-Filterkriterium.
				if ((ver == null || ver.longValue() == 0L)
						&& (vendor == null || vendor.isEmpty())) {
					continue;
				}
				if (!first) {
					sb.append(",");
				}
				first = false;
				sb.append("{\"id\":").append(json(M.getId()));
				sb.append(",\"name\":").append(json(M.getName()));
				sb.append(",\"version\":").append(ver == null ? 0L : ver.longValue());
				sb.append(",\"vendor\":").append(json(vendor));
				sb.append(",\"instances\":[");
				boolean firstI = true;
				for (ModuleInstanceRO MIS : MR.getInstalledInstances()) {
					if (!MIS.getModuleId().equals(M.getId())) {
						continue;
					}
					if (!firstI) {
						sb.append(",");
					}
					firstI = false;
					sb.append("{\"name\":").append(json(MIS.getName()));
					sb.append(",\"disabled\":").append(MIS.getDisabled());
					sb.append("}");
				}
				sb.append("]}");
			}
			sb.append("]");
			moduleJson = sb.toString();
		} catch (Exception e) {
			moduleJson = "{\"error\":" + json(String.valueOf(e.getMessage())) + "}";
			try {
				Log2 l = new Log2();
				l.logLevel = "ERROR";
				l.messages = Collections.singletonList("ModuleStatus: " + e.getMessage());
				l.execute(context);
			} catch (Exception ignore) {
				// Logging ist optional — Fehler steht bereits in moduleJson.
			}
		}
	}

	private static String json(String s)
	{
		return "\"" + escapeJson(s) + "\"";
	}

	private static String escapeJson(String s)
	{
		if (s == null) {
			return "";
		}
		StringBuilder sb = new StringBuilder();
		for (int i = 0; i < s.length(); i++) {
			char c = s.charAt(i);
			switch (c) {
				case '"':  sb.append("\\\""); break;
				case '\\': sb.append("\\\\"); break;
				case '\n': sb.append("\\n"); break;
				case '\r': sb.append("\\r"); break;
				case '\t': sb.append("\\t"); break;
				default:
					if (c < 0x20) {
						sb.append(String.format("\\u%04x", (int) c));
					} else {
						sb.append(c);
					}
			}
		}
		return sb.toString();
	}
}
