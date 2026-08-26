import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Collections;

import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.InputVar;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import de.vertico.starface.module.core.runtime.functions.system.Log2;

/**
 * UpdateDeployer v1 (PingChannel): End-to-End-Beweis des Update-Kanals.
 *
 * Lädt eine signierte, zeitbegrenzte Download-URL (nginx secure_link auf
 * modulupdates.meiser.family) direkt von der Anlage und meldet HTTP-Status +
 * gelesene Bytes. Damit ist P1 (Anlage -> Update-Domäne) final bewiesen,
 * BEVOR irgendein Import-Mechanismus auf der Anlage läuft.
 *
 * v1 ist bewusst read-only: KEIN Modul-Import, KEIN Schreibzugriff. Das
 * updateToken wird in v1 nur entgegengenommen (Echo in die Antwort, Prüfung
 * ab v2 im UpdateFromUrl-RPC gegen die Instanz-Konfiguration).
 *
 * Antwortformat (Output "response"):
 *   HTTP 200 (1534 bytes)
 *   ERROR: <Klassenname>: <Meldung>          (netz/io)
 */
@Function(visibility=Visibility.Private, rookieFunction=false,
          description="UpdateDeployer v1: lädt einen signierten Download und meldet HTTP-Status + Größe (Kanal-Beweis).")
public class PingChannel implements IBaseExecutable
{
	@InputVar(label="signedUrl", description="Signierte, zeitbegrenzte Download-URL (nginx secure_link)", type=VariableType.STRING)
	public String signedUrl = "";

	@InputVar(label="updateToken", description="Instanz-Token (v1: Echo, Prüfung ab v2 im UpdateFromUrl-RPC)", type=VariableType.STRING)
	public String updateToken = "";

	@OutputVar(label="response", description="HTTP &lt;code&gt; (&lt;bytes&gt; bytes) oder ERROR-Meldung", type=VariableType.STRING)
	public String response = "";

	@Override
	public void execute(IRuntimeEnvironment context) throws Exception
	{
		try {
			if (signedUrl == null || signedUrl.isEmpty()) {
				response = "ERROR: signedUrl leer";
				return;
			}
			URL u = new URL(signedUrl);
			HttpURLConnection c = (HttpURLConnection) u.openConnection();
			c.setConnectTimeout(15000);
			c.setReadTimeout(15000);
			c.setInstanceFollowRedirects(true);
			c.setRequestProperty("User-Agent", "UpdateDeployer/1 (STARFACE)");
			int code = c.getResponseCode();
			long size = 0L;
			InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
			if (in != null) {
				try {
					byte[] buf = new byte[8192];
					long max = 1024L * 1024L; // 1 MB Cap (nur Kanal-Beweis)
					int n;
					while ((n = in.read(buf)) > 0) {
						size += n;
						if (size > max) {
							size = max + 1L;
							break;
						}
					}
				} finally {
					in.close();
				}
			}
			c.disconnect();
			response = String.format("HTTP %d (%d bytes)", code, size);
		} catch (Exception e) {
			response = "ERROR: " + e.getClass().getSimpleName() + ": " + e.getMessage();
			try {
				Log2 l = new Log2();
				l.logLevel = "ERROR";
				l.messages = Collections.singletonList("PingChannel: " + e);
				l.execute(context);
			} catch (Exception ignore) {
				// Logging ist optional — Fehler steht bereits in response.
			}
		}
	}
}
