import java.text.SimpleDateFormat;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Locale;

import de.starface.license.manager.LicenseComponent;
import de.starface.license.manager.ws.beans.UpdateInfo;
import de.starface.license.manager.ws.beans.license.Version;
import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.InputVar;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import de.vertico.starface.module.core.runtime.functions.system.Log2;

/**
 * Deployment-Modul v10 (AnlagenUpdates): fragt die auf der Anlage verfuegbaren
 * STARFACE-Server-Updates (Final-Kanal) ab und liefert sie als JSON.
 *
 * Mechanik (Bytecode-verifiziert, Muster Admin Power Pack GET_STARFACE_UPDATE_INFOS):
 *   LicenseComponent.fetchUpdates(Version.VersionType.Final, Locale.GERMAN)
 *   -> List<UpdateInfo>  (UpdateInfo.url = DNF-Repo-URL, .version = Zielversion)
 *
 * Antwortformat (Output "response"):
 *   {"current":"<installierte Version>","count":N,"updates":[
 *     {"version":"10.0.3.0","date":"2026-08-25","type":"final","url":"https://..."}, ... ]}
 *   {"error":"<Meldung>"}   bei Exception / Token-Ablehnung
 *
 * Read-only: es wird NICHTS veraendert. Kein Log2 im Normalfall (Log-Sparsamkeit),
 * nur bei Fehlern (ERROR).
 */
@Function(visibility=Visibility.Private, rookieFunction=false,
          description="Deployment-Modul v10: listet verfuegbare STARFACE-Server-Updates (Final-Kanal) auf.")
public class AnlagenUpdates implements IBaseExecutable
{
	@InputVar(label="updateToken", description="Vom Aufrufer uebergebenes Token", type=VariableType.STRING)
	public String updateToken = "";

	@InputVar(label="installedToken", description="Instanz-Variable GU_UPDATE_TOKEN (Vergleich F-C)", type=VariableType.STRING)
	public String installedToken = "";

	@OutputVar(label="response", description="JSON-Liste der verfuegbaren Updates", type=VariableType.STRING)
	public String response = "";

	@Override
	public void execute(IRuntimeEnvironment context) throws Exception
	{
		try {
			// 1) Token-Schutz (F-C): nur aktiv, wenn Instanz-Token gesetzt
			if (installedToken != null && !installedToken.isEmpty()) {
				if (updateToken == null || !installedToken.equals(updateToken)) {
					response = "{\"error\":\"updateToken falsch\"}";
					return;
				}
			}
			// 2) Update-Liste von der Anlage holen (Final-Kanal, deutsch)
			LicenseComponent lc = (LicenseComponent) context.springApplicationContext()
					.getBean(LicenseComponent.class);
			List<UpdateInfo> list = lc.fetchUpdates(Version.VersionType.Final, Locale.GERMAN);
			// 3) JSON bauen (kein Jackson noetig; minimales Escaping)
			StringBuilder sb = new StringBuilder();
			sb.append("{\"current\":").append(esc(de.vertico.starface.Version.buildVersion()))
			  .append(",\"count\":").append(list == null ? 0 : list.size())
			  .append(",\"updates\":[");
			if (list != null) {
				SimpleDateFormat df = new SimpleDateFormat("yyyy-MM-dd");
				boolean first = true;
				for (UpdateInfo ui : list) {
					if (!first) { sb.append(","); }
					first = false;
					String dateStr = "";
					Date d = ui.getDate();
					if (d != null) { dateStr = df.format(d); }
					sb.append("{\"version\":").append(esc(ui.getVersion() == null ? "" : ui.getVersion().toString()))
					  .append(",\"date\":").append(esc(dateStr))
					  .append(",\"type\":\"final\"")
					  .append(",\"url\":").append(esc(ui.getUrl() == null ? "" : ui.getUrl()))
					  .append("}");
				}
			}
			sb.append("]}");
			response = sb.toString();
		} catch (Exception e) {
			response = "{\"error\":\"" + esc(e.getClass().getSimpleName() + ": " + e.getMessage()) + "\"}";
			try {
				Log2 l = new Log2();
				l.logLevel = "ERROR";
				l.messages = Collections.singletonList("AnlagenUpdates: " + e);
				l.execute(context);
			} catch (Exception ignore) {
				// Logging optional — Fehler steht bereits in response.
			}
		}
	}

	private static String esc(String s)
	{
		if (s == null) { return "\"\""; }
		StringBuilder sb = new StringBuilder("\"");
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
		return sb.append("\"").toString();
	}
}
