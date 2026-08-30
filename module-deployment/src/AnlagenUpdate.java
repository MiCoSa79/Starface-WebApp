import java.util.Collections;
import java.util.List;
import java.util.Locale;

import de.starface.license.manager.LicenseComponent;
import de.starface.license.manager.ws.beans.UpdateInfo;
import de.starface.license.manager.ws.beans.license.Version;
import de.vertico.starface.ajax.ServerUpdateHandler;
import de.vertico.starface.manager.SessionManager;
import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.InputVar;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import de.vertico.starface.module.core.runtime.functions.system.Log2;
import de.vertico.starface.servlets.LogoutServlet;

/**
 * Deployment-Modul v10 (AnlagenUpdate): stoesst ein STARFACE-Server-Update
 * (System-/RPM-Update) auf der Anlage an.
 *
 * Ablauf (1:1 Muster ServerUpdateHandler.prepareAndStartAutomaticUpdate, Bytecode-
 * verifiziert; Referenz Admin Power Pack EXECUTE_STARFACE_UPDATE):
 *   1. updateToken gegen Instanz-Variable GU_UPDATE_TOKEN pruefen (F-C-Schutz)
 *   2. Zielversion gegen die frische Update-Liste validieren:
 *        LicenseComponent.fetchUpdates(Version.VersionType.Final, Locale.GERMAN)
 *        -> UpdateInfo mit version == Zielversion suchen
 *      (die URL kommt NICHT ungeprueft vom Aufrufer, sondern aus dem UpdateInfo;
 *       ein abweichender updateUrl-Parameter = veraltete Anzeige -> Abbruch)
 *   3. Ausfuehrung in separatem Daemon-Thread mit 2 s Initial-Verzoegerung,
 *      damit die XML-RPC-Antwort ("OK ...") sicher den Aufrufer erreicht,
 *      BEVOR SessionManager.logoutAll(SERVER_UPDATE) alle Sessions (inkl. der
 *      aufrufenden) killt. Reihenfolge zwingend:
 *        suh.setLocale(GERMAN) -> setUpdateUri(url) -> setOldVersion(buildVersion)
 *        -> setUpdateInfo(ui) -> setTargetVersion(version)
 *        -> SessionManager.logoutAll(LogoutType.SERVER_UPDATE)
 *        -> suh.shutdownServices()   (Asterisk/XMPP/Federation/SystemCheck)
 *        -> suh.startUpdate()        (UpdateController.startPart1 -> DNF-Pipeline,
 *                                     switchToUpdateserver, dnfUpdate, Reboot)
 *
 * Antwortformat (Output "response"):
 *   OK: Update auf <version> angestoessen (Anlage startet den Update-Prozess)
 *   ERROR: <Klassenname>: <Meldung>    (Validierung/Abfrage)
 *
 * ACHTUNG: Anlagen-Update = Eingriff in die Produktion (Reboot, TK-Ausfall,
 * Voicemail/Fax temporaer verschoben, DB-Upgrade). Nur bewusst ausloesen!
 */
@Function(visibility=Visibility.Private, rookieFunction=false,
          description="Deployment-Modul v10: stoesst ein STARFACE-Server-Update (Final-Kanal) auf der Anlage an.")
public class AnlagenUpdate implements IBaseExecutable
{
	@InputVar(label="version", description="Zielversion aus der Update-Liste (z. B. 10.0.3.0)", type=VariableType.STRING)
	public String version = "";

	@InputVar(label="updateUrl", description="Erwartete DNF-Repo-URL (Plausibilitaets-Check)", type=VariableType.STRING)
	public String updateUrl = "";

	@InputVar(label="updateToken", description="Vom Aufrufer uebergebenes Token", type=VariableType.STRING)
	public String updateToken = "";

	@InputVar(label="installedToken", description="Instanz-Variable GU_UPDATE_TOKEN (Vergleich F-C)", type=VariableType.STRING)
	public String installedToken = "";

	@OutputVar(label="response", description="OK-/ERROR-Meldung", type=VariableType.STRING)
	public String response = "";

	@Override
	public void execute(IRuntimeEnvironment context) throws Exception
	{
		try {
			// 1) Token-Schutz (F-C): nur aktiv, wenn Instanz-Token gesetzt
			if (installedToken != null && !installedToken.isEmpty()) {
				if (updateToken == null || !installedToken.equals(updateToken)) {
					response = "ERROR: updateToken falsch";
					return;
				}
			}
			if (version == null || version.isEmpty()) {
				response = "ERROR: version leer";
				return;
			}
			// 2) Zielversion gegen die frische Update-Liste validieren
			LicenseComponent lc = (LicenseComponent) context.springApplicationContext()
					.getBean(LicenseComponent.class);
			List<UpdateInfo> list = lc.fetchUpdates(Version.VersionType.Final, Locale.GERMAN);
			UpdateInfo ui = null;
			if (list != null) {
				for (UpdateInfo u : list) {
					if (u.getVersion() != null && version.equals(u.getVersion().toString())) {
						ui = u;
						break;
					}
				}
			}
			if (ui == null) {
				response = "ERROR: Version " + version + " steht nicht in der Update-Liste (Liste neu anfordern)";
				log(context, "ERROR", "AnlagenUpdate: Version " + version + " nicht verfuegbar");
				return;
			}
			// 2b) URL-Plausibilitaet (veraltete Anzeige -> Abbruch, nie fremde URL verwenden)
			if (updateUrl != null && !updateUrl.isEmpty() && !updateUrl.equals(ui.getUrl())) {
				response = "ERROR: Update-URL passt nicht zu Version " + version + " (Liste neu anfordern)";
				log(context, "ERROR", "AnlagenUpdate: updateUrl weicht von UpdateInfo ab: " + updateUrl);
				return;
			}
			// 3) Ausfuehrung in separatem Thread (Antwort muss VOR logoutAll raus!)
			final IRuntimeEnvironment ctx = context;
			final UpdateInfo info = ui;
			Thread t = new Thread(new Runnable() {
				public void run() {
					try {
						Thread.sleep(2000L); // XML-RPC-Antwort zuerst rauslassen
					} catch (InterruptedException ie) {
						// egal
					}
					try {
						org.springframework.context.ApplicationContext app =
								(org.springframework.context.ApplicationContext) ctx.springApplicationContext();
						ServerUpdateHandler suh = (ServerUpdateHandler) app.getBean(ServerUpdateHandler.class);
						suh.setLocale(Locale.GERMAN);
						suh.setUpdateUri(info.getUrl());
						suh.setOldVersion(de.vertico.starface.Version.buildVersion());
						suh.setUpdateInfo(info);
						suh.setTargetVersion(info.getVersion().toString());
						log(ctx, "INFO", "AnlagenUpdate: stoesse Server-Update auf "
								+ info.getVersion() + " (URI " + info.getUrl() + ")");
						SessionManager sm = (SessionManager) app.getBean(SessionManager.class);
						sm.logoutAll(LogoutServlet.LogoutType.SERVER_UPDATE);
						suh.shutdownServices();
						suh.startUpdate();
					} catch (Exception e) {
						log(ctx, "ERROR", "AnlagenUpdate: Ausfuehrung fehlgeschlagen: "
								+ e.getClass().getSimpleName() + ": " + e.getMessage());
					}
				}
			});
			t.setDaemon(true);
			t.start();
			response = "OK: Update auf " + version + " angestossen (Anlage startet den Update-Prozess)";
			log(context, "INFO", "AnlagenUpdate: " + response);
		} catch (Exception e) {
			response = "ERROR: " + e.getClass().getSimpleName() + ": " + e.getMessage();
			try {
				Log2 l = new Log2();
				l.logLevel = "ERROR";
				l.messages = Collections.singletonList("AnlagenUpdate: " + e);
				l.execute(context);
			} catch (Exception ignore) {
				// Logging optional — Fehler steht bereits in response.
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
