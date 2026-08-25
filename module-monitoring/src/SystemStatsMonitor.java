import java.io.BufferedReader;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import de.vertico.starface.module.core.model.VariableType;
import de.vertico.starface.module.core.model.Visibility;
import de.vertico.starface.module.core.runtime.IBaseExecutable;
import de.vertico.starface.module.core.runtime.IRuntimeEnvironment;
import de.vertico.starface.module.core.runtime.annotations.Function;
import de.vertico.starface.module.core.runtime.annotations.OutputVar;
import de.vertico.starface.module.core.runtime.functions.entities.GetStarfaceVersion;
import de.vertico.starface.module.core.runtime.functions.system.Execute4;
import de.vertico.starface.module.core.runtime.functions.system.Log2;
import de.vertico.starface.persistence.connector.WireSettingsHandler;

/**
 * Telefonie-Monitoring: sammelt Systemmetriken (RAM, CPU-Last, STARFACE-Version,
 * Hostname) und den SIP-Provider-Status (Asterisk-Registry) und stellt sie als
 * Output-Variablen bereit. Der RPC-Wrapper GetStatsRpc reicht sie per XML-RPC
 * an den WebApp-Sammler durch (InfluxDB/Grafana).
 *
 * Quellen (Bytecode-verifiziert, STARFACE 10.x / Java 21):
 *  - Hostname:            Execute4 executeAs="Shell Command", command="hostname"
 *  - Version:             Original-Baustein GetStarfaceVersion (ReleaseInfo.pbxVersion)
 *  - RAM:                 /proc/meminfo (8 Felder, Werte in kB)
 *  - CPU-Last:            /proc/loadavg (load1/5/15, running/total; die zuletzt
 *                         vergebene PID wird bewusst NICHT ausgelesen)
 *  - CPU-Kerne:           Runtime.getRuntime().availableProcessors()
 *  - Provider-Namen:      WireSettingsHandler.getRegisterForProviderLines()
 *  - Provider-Status:     Execute4 executeAs="Asterisk CLI Command",
 *                         command="sip show registry" (o-byte-Muster "Registered")
 */
@Function(visibility=Visibility.Private, rookieFunction=false,
          description="Sammelt Systemmetriken (RAM, CPU-Last, Version, Hostname) und SIP-Provider-Status fuer das Telefonie-Monitoring.")
public class SystemStatsMonitor implements IBaseExecutable
{
	@OutputVar(label="systemName", description="Hostname der Anlage", type=VariableType.STRING)
	public String systemName = "";

	@OutputVar(label="systemVersion", description="STARFACE-Version (ReleaseInfo.pbxVersion)", type=VariableType.STRING)
	public String systemVersion = "";

	@OutputVar(label="memTotal", description="MemTotal aus /proc/meminfo (kB)", type=VariableType.NUMBER)
	public Integer memTotal = 0;

	@OutputVar(label="memFree", description="MemFree aus /proc/meminfo (kB)", type=VariableType.NUMBER)
	public Integer memFree = 0;

	@OutputVar(label="memAvailable", description="MemAvailable aus /proc/meminfo (kB)", type=VariableType.NUMBER)
	public Integer memAvailable = 0;

	@OutputVar(label="buffers", description="Buffers aus /proc/meminfo (kB)", type=VariableType.NUMBER)
	public Integer buffers = 0;

	@OutputVar(label="cached", description="Cached aus /proc/meminfo (kB)", type=VariableType.NUMBER)
	public Integer cached = 0;

	@OutputVar(label="swapCached", description="SwapCached aus /proc/meminfo (kB)", type=VariableType.NUMBER)
	public Integer swapCached = 0;

	@OutputVar(label="active", description="Active aus /proc/meminfo (kB)", type=VariableType.NUMBER)
	public Integer active = 0;

	@OutputVar(label="inactive", description="Inactive aus /proc/meminfo (kB)", type=VariableType.NUMBER)
	public Integer inactive = 0;

	@OutputVar(label="load1", description="1-Minuten-Load-Average (String, Dezimal)", type=VariableType.STRING)
	public String load1 = "0";

	@OutputVar(label="load5", description="5-Minuten-Load-Average (String, Dezimal)", type=VariableType.STRING)
	public String load5 = "0";

	@OutputVar(label="load15", description="15-Minuten-Load-Average (String, Dezimal)", type=VariableType.STRING)
	public String load15 = "0";

	@OutputVar(label="procsRunning", description="Laufende Prozesse (/proc/loadavg Feld 4 vor '/')", type=VariableType.NUMBER)
	public Integer procsRunning = 0;

	@OutputVar(label="procsTotal", description="Prozesse gesamt (/proc/loadavg Feld 4 nach '/')", type=VariableType.NUMBER)
	public Integer procsTotal = 0;

	@OutputVar(label="cpuCores", description="Anzahl CPU-Kerne (availableProcessors)", type=VariableType.NUMBER)
	public Integer cpuCores = 0;

	@OutputVar(label="providerStatus", description="Zeilen 'Name=Status' (Registered/Not registered/...) pro SIP-Provider", type=VariableType.STRING)
	public String providerStatus = "";

	@OutputVar(label="providerNames", description="Semikolon-getrennte konfigurierte SIP-Provider", type=VariableType.STRING)
	public String providerNames = "";

	@Override
	public void execute(IRuntimeEnvironment context) throws Exception
	{
		// 1) Hostname
		try {
			systemName = shell(context, "hostname").trim();
		} catch (Exception e) {
			systemName = "unknown";
		}

		// 2) STARFACE-Version (Original-Baustein)
		try {
			GetStarfaceVersion gsv = new GetStarfaceVersion();
			gsv.execute(context);
			systemVersion = (gsv.version == null) ? "" : gsv.version;
		} catch (Exception e) {
			systemVersion = "";
		}

		// 3) RAM aus /proc/meminfo
		try {
			readMeminfo();
		} catch (Exception e) {
			log(context, "SystemStats: /proc/meminfo lesen fehlgeschlagen: " + e.getMessage());
		}

		// 4) CPU-Last aus /proc/loadavg (letzte PID bewusst weggelassen)
		try {
			readLoadavg();
		} catch (Exception e) {
			log(context, "SystemStats: /proc/loadavg lesen fehlgeschlagen: " + e.getMessage());
		}

		// 5) CPU-Kerne
		cpuCores = Runtime.getRuntime().availableProcessors();

		// 6) SIP-Provider: Namen + Registry-Status
		readProviders(context);
	}

	private String shell(IRuntimeEnvironment context, String command) throws Exception
	{
		Execute4 exe = new Execute4();
		exe.executeAs = "Shell Command";
		exe.command = command;
		exe.bufferSize = 0x100000;
		exe.execute(context);
		return (exe.output == null) ? "" : exe.output;
	}

	private void readMeminfo() throws Exception
	{
		BufferedReader br = new BufferedReader(new FileReader("/proc/meminfo"));
		try {
			String line;
			while ((line = br.readLine()) != null) {
				int idx = line.indexOf(':');
				if (idx < 0) {
					continue;
				}
				String key = line.substring(0, idx).trim();
				String val = line.substring(idx + 1).replace("kB", "").trim();
				if (val.isEmpty()) {
					continue;
				}
				int v = (int) Double.parseDouble(val);
				if ("MemTotal".equals(key)) {
					memTotal = v;
				} else if ("MemFree".equals(key)) {
					memFree = v;
				} else if ("MemAvailable".equals(key)) {
					memAvailable = v;
				} else if ("Buffers".equals(key)) {
					buffers = v;
				} else if ("Cached".equals(key)) {
					cached = v;
				} else if ("SwapCached".equals(key)) {
					swapCached = v;
				} else if ("Active".equals(key)) {
					active = v;
				} else if ("Inactive".equals(key)) {
					inactive = v;
				}
			}
		} finally {
			br.close();
		}
	}

	private void readLoadavg() throws Exception
	{
		BufferedReader br = new BufferedReader(new FileReader("/proc/loadavg"));
		String line;
		try {
			line = br.readLine();
		} finally {
			br.close();
		}
		if (line == null) {
			return;
		}
		String[] t = line.trim().split("\\s+");
		if (t.length >= 1) {
			load1 = t[0];
		}
		if (t.length >= 2) {
			load5 = t[1];
		}
		if (t.length >= 3) {
			load15 = t[2];
		}
		if (t.length >= 4) {
			String[] tt = t[3].split("/");
			if (tt.length >= 1) {
				procsRunning = parseIntSafe(tt[0]);
			}
			if (tt.length >= 2) {
				procsTotal = parseIntSafe(tt[1]);
			}
		}
		// t[4] = zuletzt vergebene PID -> bewusst NICHT auslesen (Nutzer-Vorgabe)
	}

	private void readProviders(IRuntimeEnvironment context)
	{
		List<String> configNames = new ArrayList<String>();
		try {
			WireSettingsHandler wsh = context.springApplicationContext().getBean(WireSettingsHandler.class);
			List<String> regs = wsh.getRegisterForProviderLines();
			if (regs != null) {
				configNames.addAll(regs);
			}
		} catch (Exception e) {
			log(context, "SystemStats: getRegisterForProviderLines fehlgeschlagen: " + e.getMessage());
		}

		StringBuilder names = new StringBuilder();
		for (String c : configNames) {
			if (names.length() > 0) {
				names.append(";");
			}
			names.append(c);
		}
		providerNames = names.toString();

		// Status ueber die Asterisk-Registry (o-byte-Muster: "Registered")
		String regOut = "";
		int rc = -1;
		try {
			Execute4 exe = new Execute4();
			exe.executeAs = "Asterisk CLI Command";
			exe.command = "sip show registry";
			exe.bufferSize = 0x100000;
			exe.execute(context);
			regOut = (exe.output == null) ? "" : exe.output;
			rc = exe.resultCode;
		} catch (Exception e) {
			log(context, "SystemStats: 'sip show registry' fehlgeschlagen: " + e.getMessage());
		}

		// Rohdaten ins Modul-Log (erste Inbetriebnahme: Format-Check auf der Anlage)
		log(context, "SystemStats: getRegisterForProviderLines=" + providerNames);
		log(context, "SystemStats: sip show registry (rc=" + rc + "):\n" + regOut);

		StringBuilder status = new StringBuilder();
		for (String c : configNames) {
			String state = matchRegistryState(c, regOut);
			if (state == null) {
				state = "Not registered";
			}
			if (status.length() > 0) {
				status.append("\n");
			}
			status.append(c).append("=").append(state);
		}
		if (status.length() == 0) {
			// Fallback: Registry-Zeilen direkt (falls keine Konfig-Namen kamen)
			for (String line : regOut.split("\n")) {
				String lt = line.trim();
				if (lt.isEmpty() || lt.startsWith("Host") || lt.startsWith("-") || lt.startsWith("sip registrations")) {
					continue;
				}
				String[] t = lt.split("\\s+");
				if (t.length < 4) {
					continue;
				}
				String name = t[1] + "@" + t[0];
				if (status.length() > 0) {
					status.append("\n");
				}
				status.append(name).append("=").append(t[3]);
			}
		}
		providerStatus = status.toString();
	}

	private String matchRegistryState(String configName, String regOut)
	{
		String cfgUser = configName;
		int at = configName.indexOf('@');
		if (at >= 0) {
			cfgUser = configName.substring(0, at);
		}
		String best = null;
		for (String line : regOut.split("\n")) {
			String lt = line.trim();
			if (lt.isEmpty() || lt.startsWith("Host") || lt.startsWith("-") || lt.startsWith("sip registrations")) {
				continue;
			}
			String[] t = lt.split("\\s+");
			if (t.length < 4) {
				continue;
			}
			String user = t[1];
			String host = t[0];
			if (cfgUser.equals(user) || configName.contains(host) || user.contains(cfgUser)) {
				String st = t[3];
				if ("Registered".equals(st)) {
					return "Registered";
				}
				best = st;
			}
		}
		return best;
	}

	private int parseIntSafe(String s)
	{
		try {
			return Integer.parseInt(s.trim());
		} catch (Exception e) {
			return 0;
		}
	}

	private void log(IRuntimeEnvironment context, String msg)
	{
		try {
			Log2 l = new Log2();
			l.logLevel = "INFO";
			l.messages = Collections.singletonList(msg);
			l.execute(context);
		} catch (Exception ignore) {
			// Logging-Fehler duerfen die Funktion nicht brechen
		}
	}
}
