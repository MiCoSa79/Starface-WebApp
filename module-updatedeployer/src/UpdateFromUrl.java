import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;

import de.vertico.starface.module.core.ModuleRegistry;
import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.InputVar;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import de.vertico.starface.module.core.runtime.functions.system.Log2;

/**
 * UpdateDeployer v2 (UpdateFromUrl): echtes Modul-Update über die Anlage.
 *
 * Ablauf (Anstoß immer von außen per XML-RPC):
 *   1. updateToken gegen Instanz-Variable GU_UPDATE_TOKEN pruefen (F-C-Schutz)
 *   2. signierte .sfm von modulupdates.meiser.family laden (nginx secure_link
 *      validiert expires+md5 -> 403/410/200)
 *   3. Paket in Temp-Datei speichern (Cap 20 MB)
 *   4. ModuleRegistry.importModule(absPfad, true) -> Modul wird ersetzt/importiert
 *   5. Antwort: "OK: <moduleName> v<targetVersion> importiert" bzw. HTTP/ERROR
 *
 * Antwortformat (Output "response"):
 *   OK: <name> v<version> importiert
 *   HTTP 403                       (Signatur abgelaufen/ungueltig)
 *   ERROR: <Klassenname>: <Meldung> (netz/io/import)
 */
@Function(visibility=Visibility.Private, rookieFunction=false,
          description="UpdateDeployer v2: laedt ein signiertes .sfm-Paket und importiert es ueber ModuleRegistry (echtes Update).")
public class UpdateFromUrl implements IBaseExecutable
{
	@InputVar(label="moduleName", description="Name des Zielmoduls (Log/Status)", type=VariableType.STRING)
	public String moduleName = "";

	@InputVar(label="signedUrl", description="Signierte, zeitbegrenzte Download-URL (nginx secure_link)", type=VariableType.STRING)
	public String signedUrl = "";

	@InputVar(label="targetVersion", description="Zielversion des Pakets (Log/Status)", type=VariableType.STRING)
	public String targetVersion = "";

	@InputVar(label="updateToken", description="Vom Aufrufer uebergebenes Token", type=VariableType.STRING)
	public String updateToken = "";

	@InputVar(label="installedToken", description="Instanz-Variable GU_UPDATE_TOKEN (Vergleich F-C)", type=VariableType.STRING)
	public String installedToken = "";

	@OutputVar(label="response", description="OK/HTTP/ERROR-Meldung", type=VariableType.STRING)
	public String response = "";

	@Override
	public void execute(IRuntimeEnvironment context) throws Exception
	{
		Path tmp = null;
		try {
			// 1) Token-Schutz (F-C): nur aktiv, wenn Instanz-Token gesetzt
			if (installedToken != null && !installedToken.isEmpty()) {
				if (updateToken == null || !installedToken.equals(updateToken)) {
					response = "ERROR: updateToken falsch";
					log(context, "ERROR", "UpdateFromUrl: updateToken abgelehnt fuer " + moduleName);
					return;
				}
			}
			if (signedUrl == null || signedUrl.isEmpty()) {
				response = "ERROR: signedUrl leer";
				return;
			}
			// 2) Download (signierte URL, 20 MB Cap)
			URL u = new URL(signedUrl);
			HttpURLConnection c = (HttpURLConnection) u.openConnection();
			c.setConnectTimeout(15000);
			c.setReadTimeout(30000);
			c.setInstanceFollowRedirects(true);
			c.setRequestProperty("User-Agent", "UpdateDeployer/2 (STARFACE)");
			int code = c.getResponseCode();
			if (code != 200) {
				c.disconnect();
				response = "HTTP " + code;
				log(context, "ERROR", "UpdateFromUrl: Download fehlgeschlagen (" + code + ") fuer " + moduleName);
				return;
			}
			tmp = Files.createTempFile("updatedeployer-", ".sfm");
			try (InputStream in = c.getInputStream();
			     OutputStream out = Files.newOutputStream(tmp)) {
				byte[] buf = new byte[8192];
				long max = 20L * 1024L * 1024L; // 20 MB Paket-Cap
				long size = 0L;
				int n;
				while ((n = in.read(buf)) > 0) {
					out.write(buf, 0, n);
					size += n;
					if (size > max) {
						c.disconnect();
						response = "ERROR: Paket > 20 MB";
						return;
					}
				}
			}
			c.disconnect();
			log(context, "INFO", "UpdateFromUrl: Download ok (" + Files.size(tmp) + " bytes) -> importiere "
				+ moduleName + " v" + targetVersion);
			// 3) Modul-Import (Spring-Bean, nur aus Modulcode erreichbar)
			ModuleRegistry MR = (ModuleRegistry) context.springApplicationContext().getBean(ModuleRegistry.class);
			MR.importModule(tmp.toString(), true);
			response = "OK: " + moduleName + " v" + targetVersion + " importiert";
			log(context, "INFO", "UpdateFromUrl: " + response);
		} catch (Exception e) {
			response = "ERROR: " + e.getClass().getSimpleName() + ": " + e.getMessage();
			try {
				Log2 l = new Log2();
				l.logLevel = "ERROR";
				l.messages = Collections.singletonList("UpdateFromUrl: " + e);
				l.execute(context);
			} catch (Exception ignore) {
				// Logging optional — Fehler steht bereits in response.
			}
		} finally {
			if (tmp != null) {
				try {
					Files.deleteIfExists(tmp);
				} catch (Exception ignore) {
					// Temp-Datei aufraeumen ist optional.
				}
			}
		}
	}

	private void log(IRuntimeEnvironment context, String level, String msg)
	{
		try {
			Log2 l = new Log2();
			l.logLevel = level;
			l.messages = Collections.singletonList(msg);
			l.execute(context);
		} catch (Exception ignore) {
			// Logging optional.
		}
	}
}
