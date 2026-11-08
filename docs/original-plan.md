# RoomCheck: SafeSpace Hacks Build Plan

> Original design plan. Where it differs from the app (e.g. 'landlord' → 'host', PDF via Playwright not WeasyPrint), the README and the app are current.

Nov 2, 2026

## Summary and problem statement

RoomCheck is a laptop app with a web dashboard that needs no extra hardware. It lets a tenant or short-stay guest check, in about 10 minutes, what connected devices are in the space they just entered, which of them could be watching or controlling it, and what to do next. Working name only.

**Intended user.** A person moving into a rental room or checking into a short-stay unit (Airbnb, serviced apartment, hostel room). They are not a security specialist and have no admin access to the property's network.

**Situation and risk.** Smart devices left by a landlord, host or previous tenant can stay linked to someone else's account: Wi-Fi cameras, smart locks, routers. Those people may still be able to watch the room or unlock the door. Hidden cameras in short-stay rentals are a documented problem, which is why Carnegie Mellon researchers built Lumos to find them ([USENIX Security 2022](https://www.usenix.org/conference/usenixsecurity22/presentation/sharma-rahul)). Tenants today have no simple way to see what is on the network, who controls it, or whether a device is recording them.

**Practical improvement.** The person ends the check with three things they did not have before:

1. A plain-language list of the devices found, each with a confidence level and the evidence behind it.
2. A specific next step for each risky item, e.g. "Ask the landlord to remove previous users from the smart lock", with a message template ready to send.
3. A timestamped handover report they can keep. It shows the room's condition at move-in if there is a dispute later.

**One-line pitch.** "A digital move-in inspection: find out what's watching or controlling your room before you unpack."

## How RoomCheck stands out

Existing tools answer "is there a camera on this Wi-Fi?" RoomCheck answers the tenant's wider question: what in this room is connected, who else controls it, and can the network itself be trusted? Lead the pitch with "take control of a room you just moved into", not "find hidden cameras".

**What already exists**

| Approach | Examples | What it does | Where it falls short |
| --- | --- | --- | --- |
| Network scanner apps | Fing (hidden-camera finder is a paid Starter/Premium feature) | Lists devices on the Wi-Fi you joined and flags likely cameras | Fing itself says it [only detects cameras on the network you are scanning](https://www.fing.com/?p=737). It focuses on devices, not on whether the network or its controls can be trusted. |
| Multi-sensor detector apps | NSpy, Secure Vacation, YourSweep, Hidden Camera Detector | Combine a same-network scan with IR lens viewing, magnetic/EMF readings and checklists | [Reviewers rate app-based detection as low to moderate reliability](https://www.alibaba.com/product-insights/hidden-camera-detector-apps-do-they-actually-work-for-airbnb-safety.html), useful for initial screening only. Several are subscription-based. |
| Handheld RF / lens detectors | Pocket RF and lens-glint devices | Beep near strong radio sources; show lens reflections | Can't tell a camera from a phone or router, and give no record or next step |
| Research prototypes | Lumos, MotionCompass, SNOOPDOG | Detect and locate hidden devices from encrypted Wi-Fi traffic | Need sniffing hardware and aren't packaged for ordinary users |
| Move-in checklists | Rental-platform and home-security guides | Tell new occupants to reset smart locks and take over device accounts | Advice only. Nothing checks which devices are there or tracks whether the handover happened. |

RoomCheck's on-network camera detection overlaps with Fing, so present it as one input, not the headline.

**Six differentiators (each maps to a feature in this plan)**

1. **Covers control, not only spying.** Smart locks, cloud-linked devices and inherited accounts, which no scanner app frames as a tenant problem.
2. **Checks whether the network can be trusted.** DNS hijacking, ARP spoofing, rogue DHCP, UPnP and WPS, plus fake copies of the room's Wi-Fi (evil twins).
3. **Looks beyond the network you joined, with no extra hardware.** The laptop's own Wi-Fi and Bluetooth radios find camera setup hotspots, lookalike networks and unknown item trackers. Fing's guide [suggests checking for an unexpected second network by hand](https://www.fing.com/?p=737); RoomCheck automates it.
4. **Remembers the move-in state.** A saved baseline means a later re-scan shows what changed: "a camera-like device appeared since your move-in scan".
5. **Turns findings into action and evidence.** A tracked handover checklist, a landlord message draft and a timestamped, tamper-evident report.
6. **Honest by design.** Confidence and evidence on every finding, measured hit and false-alarm counts, never "safe". Local-only, no account, no subscription.

**Future work (one roadmap slide).** Off-network camera detection and per-spot "Privacy Zone" checks with a small Wi-Fi sensor, based on published research (MotionCompass, SNOOPDOG). Showing this proves you know where the prototype stops.

**Pitch line.** "Fing tells you what's on the Wi-Fi. RoomCheck tells you who else controls your room, whether the network can be trusted, and what changed since you moved in."

## Scope

RoomCheck is software-only: it runs on a Windows laptop and uses only the laptop's own network card, Wi-Fi and Bluetooth. Every feature below is a Must. With the hardware sensor gone, the effort goes into network trust, nearby wireless checks, the handover workflow and change tracking.

| Feature | Layer | Why it matters |
| --- | --- | --- |
| Device discovery on the user's own network (ARP sweep, mDNS, SSDP, ONVIF, Tuya broadcasts) | 1 | The core workflow; everything else builds on it |
| Vendor lookup and device-type guess with confidence and evidence | 2 | Turns MAC addresses into "probably a camera" |
| Light port and service checks on the user's own network, after consent | 2-3 | Strong camera signal (RTSP on port 554), risky services (Telnet) |
| Router and network-integrity checks: UPnP, WPS, DNS, rogue DHCP, ARP spoofing | 3 | Whether the network itself can be trusted |
| CVE lookup for models and firmware that can be identified | 3 | Known, published weaknesses in devices found |
| Nearby Wi-Fi check: lookalike networks (evil twins), camera setup hotspots, hidden and open networks | 4 | Looks beyond the network you joined, with no extra hardware |
| Bluetooth (BLE) scan for item trackers and Bluetooth locks or cameras | 4 | Complements phones' built-in unknown-tracker alerts |
| Signal-strength "warmer/colder" locator for flagged hotspots and Bluetooth devices | 4 | Helps the user find the physical device |
| Rules-based risk score and plain-language checklist | 5 | Judges score the safety benefit on this |
| AI explanations with a template fallback | 5 | Clarity criterion; never decides the verdict |
| Timestamped PDF handover report | 5 | Gives the user something to keep and act on |
| Handover assistant: tracked tasks per finding, landlord message | 6 | Turns findings into actions that actually get done |
| Move-in baseline and re-scan comparison | 6 | Shows what changed after move-in |
| Graceful failure messages (no Npcap, Location services off, Bluetooth off, client isolation) | All | Practical Functionality criterion |

**Out of scope, by design.** These are deliberate limits, not missing features:

- Logging in to, or trying passwords on, any device.
- Decrypting or storing anyone's traffic contents.
- Port scanning networks the user isn't authorised to test.
- Off-network camera detection by sniffing other networks' traffic. It needs a monitor-mode Wi-Fi sensor, so it's future work.
- Finding cameras that transmit nothing (SD-card only), or cameras that connect to a network as ordinary clients without broadcasting anything RoomCheck can see.
- Telling the user who owns a cloud-linked device account.

## System architecture and repo layout

Two collectors feed one unprivileged core. A scanner worker examines the network you joined; a wireless survey reads what nearby Wi-Fi and Bluetooth devices broadcast. The core's rules engine decides every verdict, and the dashboard and report present it.

Architecture (text version of the diagram):

```
Room network (Wi-Fi/LAN you joined) --> Scanner worker (Layers 1-3: ARP, mDNS, SSDP, ONVIF, ports, router checks)
                                            | local IPC, fixed jobs
Nearby Wi-Fi and Bluetooth --> Wireless survey (Layer 4: Windows WLAN API, Bluetooth scan with bleak)
                                            | in-process
                                            v
RoomCheck app on your laptop, served on 127.0.0.1 only:
  FastAPI core (unprivileged): device merge, noisy-OR scorer, baseline compare.
  Rules engine decides every verdict; AI never does.
    --> Dashboard (React): results, handover tasks, verify
    --> Handover report: PDF + SHA-256 + RFC 3161
Optional outside calls from the core:
  Anthropic API (explains findings; no IPs or MACs)
  NVD CVE API (product names only)
  Timestamp authority (report hash only)
```

The optional outside calls each receive only the minimum data shown. The app runs fully offline without them.

**Repo layout (one monorepo)**

```
roomcheck/
  scannerd/            # scanner worker: fixed job allowlist, local IPC with an auth key
    jobs/              # arp.py, ports.py, dhcp.py, listeners.py
  app/                 # FastAPI, unprivileged
    discovery/         # Layer 1 merge and Device model
    fingerprint/       # Layer 2 signals and noisy-OR scorer
    checks/            # Layer 3 network-integrity checks
    wireless/          # Layer 4: wlanapi.py (ctypes), ble.py (bleak), locator.py
    rules/             # engine plus YAML rules, weights and hotspot patterns
    explain/           # AI client, validator, templates
    report/            # Jinja2 template, WeasyPrint, hash, RFC 3161
    handover/          # Layer 6 task templates and status
    baseline/          # Layer 6 move-in store and diff
  web/                 # React + Vite + TypeScript dashboard
  tests/
    unit/
    fixtures/pcap/     # recorded on your own network
    fixtures/wireless/ # recorded Wi-Fi and BLE scan results, also used for replay
  docs/evaluation.md   # detection and usability results
```

## Setup and environment

RoomCheck runs on your ASUS Zenbook under Windows 11, with nothing to buy. The demo uses only devices you already own.

| Item | Purpose | Notes |
| --- | --- | --- |
| Windows 11 laptop (your Zenbook) | Runs the scanner, API and dashboard | Primary target. Keep the code cross-platform where it's cheap: Layers 1-3 also run on Linux and macOS. |
| Npcap (free, from npcap.com; also offered by the Nmap installer) | Lets scapy send and capture raw packets on Windows | The user installs it. Its free licence doesn't allow bundling it inside RoomCheck's installer, so link to it instead. |
| Nmap for Windows | Port checks (Layer 2) | `python-nmap` only wraps the binary |
| The laptop's built-in Wi-Fi and Bluetooth | Layer 4 nearby Wi-Fi and Bluetooth scans | No admin rights needed. Recent Windows 11 builds need Location services on before apps can list nearby Wi-Fi networks. |
| Your home router | Demo network you're allowed to scan | Avoid scanning a venue's network on stage |
| An old phone running an IP-camera app | Stand-in "hidden camera" for tests and the demo | Streams like a real camera. Pick an app that offers RTSP so the camera checks have something to find. |
| Your phone's hotspot | Tests for lookalike networks and camera setup hotspots | Name it like your home Wi-Fi with no password, or like a camera setup hotspot |
| Any Bluetooth device you own (earbuds, a tag, a watch) | Bluetooth scan and locator tests | Anything that advertises over Bluetooth works |

**Software to pin**

- Python 3.12 or newer (python.org installer or `uv`), with a committed lockfile.
- The latest stable Npcap and Nmap.
- The current Node.js LTS release for the frontend build.
- Python packages: `scapy`, `python-nmap`, `zeroconf`, `ssdpy`, `WSDiscovery`, `mac-vendor-lookup`, `dnspython`, `httpx`, `defusedxml`, `bleak`, `fastapi`, `uvicorn`, `pydantic`, `jinja2`, `weasyprint`, `rfc3161ng`, `anthropic`, `pywin32`.
- WeasyPrint needs the GTK/Pango runtime on Windows. Follow its Windows install guide early, or swap to a browser-based PDF export if it fights you.

**Process separation (a security design point worth showing judges)**

- A separate scanner worker process runs a fixed allowlist of scan jobs. It's the only part that may need administrator rights, e.g. if Npcap was installed in admin-only mode.
- It talks to the FastAPI app through Python's `multiprocessing.connection` on 127.0.0.1, with a random per-session auth key.
- The FastAPI app runs as a normal user and can only ask for named jobs. It can never pass arbitrary nmap arguments or targets.

## Layer 1: on-network device discovery

Layer 1 builds the device list by combining one active sweep with several passive listeners, so devices that ignore one method still show up through another. It only runs on the network the laptop is connected to.

| Step | Method | Library / tool | Active or passive | What it finds |
| --- | --- | --- | --- | --- |
| 0 | Find the interface, own IP, gateway and subnet | `scapy` `conf.route.route("0.0.0.0")`; `psutil.net_if_addrs()` for the netmask | Local only | Scan scope. If the subnet is larger than /22 (1,024 hosts), skip the sweep and go passive-only. |
| 1 | ARP sweep, 2 passes about 20 s apart (sleepy IoT devices miss the first) | `scapy` `srp(Ether(dst="ff:ff:ff:ff:ff:ff")/ARP(pdst=cidr), timeout=2, retry=1)` | Active (broadcast) | IP and MAC of every awake host |
| 2 | Passive ARP and DHCP listener for the whole scan | `scapy` `AsyncSniffer(filter="arp or (udp and (port 67 or port 68))")` | Passive | Late joiners. DHCP option 12 (hostname), 55 (parameter request list) and 60 (vendor class) as fingerprint inputs. |
| 3 | mDNS / Bonjour browse | `zeroconf`: `ZeroconfServiceTypes.find()`, then a `ServiceBrowser` per type | Passive-leaning (standard queries) | Names, service types (`_hap._tcp`, `_googlecast._tcp`, `_airplay._tcp`), TXT model strings |
| 4 | SSDP / UPnP M-SEARCH (`ssdp:all`) | `ssdpy` `SSDPClient().m_search("ssdp:all")` | Active (multicast) | Device and service types, `SERVER` header, `LOCATION` URL of the description XML |
| 5 | ONVIF WS-Discovery probe on 239.255.255.250:3702 | `WSDiscovery` (PyPI) | Active (multicast) | Devices advertising `NetworkVideoTransmitter`: an IP camera, almost certainly |
| 6 | Tuya local broadcast listener on UDP 6666 / 6667 | `scapy` sniffer on those ports | Passive | Presence of Tuya / Smart Life devices (contents are not decrypted) |

**Handling edge cases**

- **Randomised MACs.** If the locally administered bit (`0x02` in the first octet) is set, there is no vendor to look up. Label the device "private address, probably a phone or laptop" with low confidence.
- **Client isolation.** If, after 60 s, the sweep returns only the gateway and the listeners hear no other hosts, the network is hiding devices from each other (common in hotels). Say so plainly and recommend the Layer 4 off-network test.
- **Merging records.** Key each device by MAC address and merge records from every source. Keep a `sources[]` list so the UI can show how each device was found.

**Device record (Pydantic model)**

`Device { id, ip, mac, mac_is_random, vendor, hostnames[], services[], sources[], first_seen, last_seen }`

## Layer 2: device fingerprinting

Layer 2 turns each device record into a type guess ("camera, 87%") built from small, named pieces of evidence the user can inspect. It never logs in to anything. Port and banner checks run only after the user confirms they are on their own network or have permission.

**Signals and tools**

| Signal | Tool | Detail |
| --- | --- | --- |
| Vendor from MAC prefix | `mac-vendor-lookup` (IEEE OUI list) | Download the list once and bundle it, so it works offline at demo time |
| Open ports, fixed list only | `python-nmap` driving `nmap -sT -Pn -T3 --max-retries 1 --host-timeout 30s -p <list>`, run by `scannerd` | List: 23 (Telnet), 80, 443, 554 and 8554 (RTSP), 1883 and 8883 (MQTT), 6668 (Tuya local), 8000, 8080, 8443, 34567 (XMEye-type DVRs / cameras), 37777 (Dahua) |
| HTTP identity | `httpx`, a `GET /` with a 3 s timeout and 64 KB cap | `Server` header and the `<title>` text only |
| RTSP identity | A raw socket sending `OPTIONS rtsp://<ip>:554 RTSP/1.0` with `CSeq: 1` | A `200` or `401` reply confirms an RTSP video server. No credentials sent, ever. |
| UPnP description | `httpx` GET of the SSDP `LOCATION` URL, parsed with `defusedxml` | `manufacturer`, `modelName`, `deviceType`. Use `defusedxml` because device XML is untrusted input (XXE and billion-laughs attacks). |
| mDNS / DHCP strings | From Layer 1 | Model and hostname keywords, DHCP vendor class |

**Scoring method: noisy-OR over weighted evidence.** Each signal i that matches gives a weight w\_i for a device type. The type's confidence is:

```latex
P(\text{type}) = 1 - \prod_i (1 - w_i)
```

This keeps scores between 0 and 1, lets independent clues add up, and is easy to explain: "three clues pointed to a camera". Weights live in a YAML file, not in code, and are tuned against the test devices (see Testing).

| Camera evidence (starting weights) | w |
| --- | --- |
| ONVIF `NetworkVideoTransmitter` reply | 0.6 |
| RTSP server answers on 554 / 8554 | 0.5 |
| Port 34567, 37777 or 8000 open | 0.3 |
| Vendor is a camera-focused maker (e.g. Hikvision, Dahua, Hangzhou Xiongmai) | 0.3 |
| Name or model string matches `cam`, `ipc`, `nvr` or `doorbell` | 0.3 |
| Vendor makes many device types (e.g. TP-Link, Espressif) | 0.1 |
| Tuya broadcast seen, nothing else | 0.05 |

Do the same for lock / doorbell, router, hub, speaker, TV, smart plug and computer / phone. Show the user confidence bands, not raw numbers: **Likely** (0.8 and above), **Possible** (0.5 to 0.8), **Unclear** (below 0.5). Each comes with the evidence list. The UI never says a device is "safe".

## Layer 3: risk and network-integrity checks

Layer 3 answers two questions: is any device risky in itself, and is the network itself trustworthy? Every check has a rule ID, a severity and a fixed next step. All checks are read-only observations; none of them changes a device's settings.

| Rule | Check | How | Severity | Next step shown to the user |
| --- | --- | --- | --- | --- |
| R-CAM | Device likely or possibly a camera | Layer 2 score at 0.5 or above | High if "Likely", Medium if "Possible" | Find it physically. Ask the host or landlord where it is and who can view it. In a short stay, check the platform's camera disclosure rules. |
| R-LOCK | Smart lock or doorbell present | Layer 2 type | High | Ask the landlord to remove previous users and codes in the lock's app, and confirm in writing |
| R-CLOUD | Cloud-linked IoT device (e.g. Tuya) | Layer 1 / 2 signals | Medium | Ask who controls the account. A long-term tenant can ask to factory-reset it and pair it to their own account. |
| R-TELNET | Telnet (port 23) open on any device | Layer 2 port check | High | Don't use that device. Report it to the landlord. Telnet sends logins unencrypted and is a common IoT weakness. |
| R-WIFI-ENC | Wi-Fi is open or WEP | `netsh wlan show interfaces` (authentication and cipher of the current connection), cross-checked with the Layer 4 Wi-Fi survey | High | Assume traffic can be read. Use a VPN or mobile data until the landlord fixes it. |
| R-WPS | WPS enabled on the access point | The WPS information element in the access point's beacon, read from `WlanGetNetworkBssList` by the Layer 4 Wi-Fi survey | Medium | Ask the landlord to switch WPS off (it is open to PIN brute-forcing) |
| R-UPNP | Router offers UPnP Internet Gateway Device | SSDP `deviceType` contains `InternetGatewayDevice` | Medium | Devices can open ports to the internet without asking. Ask for UPnP to be disabled. |
| R-DNS | DNS looks tampered with | `dnspython`: (a) a random label under `example.com` must return NXDOMAIN; (b) a public domain must not resolve to a private or bogon IP; (c) compare with a DoH query to `cloudflare-dns.com` | High | Don't log in to anything important on this network. Tell the landlord. |
| R-ARP | Gateway IP claimed by more than one MAC | Passive ARP table from Layer 1, tracked over time | High | Possible interception. Disconnect and use mobile data. |
| R-DHCP | More than one DHCP server answers | `scapy` DHCPDISCOVER, collect OFFERs for 5 s, count distinct `server_id` values | High | Possible rogue router. Report it to the landlord. |
| R-CVE (stretch) | Known vulnerabilities for an identified model and firmware | NVD CVE API 2.0 | Info to Medium | "Known issues have been reported for this model." Phrased this way because the exact version is often unconfirmed. |

**Avoiding false alarms in the DNS check.** Different answers from the system resolver and DoH are normal (CDNs return location-based IPs). So R-DNS fires only on NXDOMAIN hijacking or private / bogon answers. The comparison is shown as context, never as the trigger.

**NVD details (stretch).** Endpoint: `https://services.nvd.nist.gov/rest/json/cves/2.0`, queried by `cpeName` (or `virtualMatchString` for version ranges); `hasKev` flags issues in CISA's actively-exploited list.

- Without an API key the limit is 5 requests per 30 s; a free key raises it to 50 ([nvdlib docs](https://nvdlib.readthedocs.io/en/latest/v2/CPEv2.html)).
- Request a key, cache every response in SQLite, and pre-cache the demo devices so the demo never waits on rate limits.

## Layer 4: nearby wireless check (Wi-Fi and Bluetooth)

Layer 4 uses the laptop's own Wi-Fi and Bluetooth radios to look beyond the network you joined, with no extra hardware. It only reads what nearby devices already broadcast publicly (network names, security settings, Bluetooth advertisements) and never connects to anything.

**Wi-Fi survey**

1. Trigger a fresh scan with `WlanScan`, then read every access point with `WlanGetNetworkBssList`, both from the Windows Native Wi-Fi API (`wlanapi.dll`) called through Python `ctypes`. Each entry gives SSID, BSSID, signal strength, channel frequency and the raw information elements. Fallback: parse `netsh wlan show networks mode=bssid`.
2. Parse the information elements: RSN for WPA2/WPA3 and cipher, the Microsoft vendor element (OUI 00:50:F2, type 4) for WPS (this feeds R-WPS in Layer 3), and a blank SSID for hidden networks.
3. Run 3 scans about 10 s apart and keep only networks seen at least twice, to filter out flicker.

| Rule | Check | Severity | Next step shown to the user |
| --- | --- | --- | --- |
| R-TWIN | Another access point uses the room network's exact name but is open or uses weaker security | High | Don't connect to it. It may be set up to intercept traffic. Ask the landlord which network is genuine. |
| R-TWIN-VENDOR | Same name and security, but that access point's maker differs from the rest and its signal is strong | Medium | "Possible lookalike." Mesh systems and extenders can explain this, so ask before assuming. |
| R-CAMHOT | A nearby network name matches a camera setup-hotspot pattern, or its maker (from the BSSID prefix) is a camera-focused vendor | Medium | A camera may be broadcasting its own network. Use the locator to see where it's strongest, then ask the host. |
| R-HIDDEN | A hidden network with a strong signal (starting threshold: stronger than -60 dBm) | Low | Often harmless, since many routers hide a second network. Shown as context, not proof. |
| R-OPEN | Open networks nearby | Info | Don't use them for anything sensitive. |

- Hotspot name patterns live in `rules/hotspot_patterns.yaml`, built from your own test devices and vendor setup manuals. Matches are hints only, because names are easy to change.
- Many access points use randomised BSSIDs for extra networks, so vendor lookup fails on them. Treat those as "maker unknown", never as a match.

**Bluetooth (BLE) scan**

1. Use `bleak`'s `BleakScanner` (Windows' WinRT Bluetooth API underneath) for 30 s with `return_adv=True`. Collect address, name, signal strength, manufacturer data and service UUIDs.
2. Classify by manufacturer ID and service UUID: item trackers (e.g. Apple Find My advertisements under company ID 0x004C), Bluetooth locks, cameras and speakers. Base tracker signatures on documented open-source work such as AirGuard (SEEMOO lab, TU Darmstadt), and credit it.
3. Bluetooth addresses rotate, so a tracker is flagged when the same advertisement format keeps appearing with a strong signal across repeated scans, not from one sighting.
4. **R-TRACKER (Medium):** "An item tracker is nearby and doesn't seem to belong to you." Next step: find it with the locator; a phone's built-in unknown-tracker alert gives a second opinion.

**Signal-strength locator ("warmer/colder")**

- For a flagged hotspot or Bluetooth device, the user walks slowly round the room holding the laptop. RoomCheck rescans and shows a smoothed signal bar with "warmer" or "colder".
- Bluetooth readings update several times a second. A Wi-Fi scan takes a few seconds, so the Wi-Fi locator is slower, and the UI says so.
- Smooth with a rolling median of the last 5 readings. Signal swings by several dB as the body blocks it, so tell the user to hold the laptop the same way throughout.
- Credit Lumos (USENIX Security 2022) for locating devices from signal strength as the user walks.

**Known blind spots (shown in the UI)**

- A camera that joins the host's network as an ordinary client broadcasts nothing Layer 4 can see. It's only found if it's on the network you joined (Layers 1-2), or with sniffing hardware (future work).
- Names, makers and tracker formats are hints, not proof. The locator gives a rough area (metres), not an exact spot.

## Layer 5: rules engine, AI explanations and tamper-evident report

Fixed rules decide every verdict. The AI only rewrites those verdicts in plain language, and the app works fully without it. This follows the same "AI explains, never decides" rule as CyberCity, and it should be said out loud in the pitch.

**Rules engine**

- Rules live in `rules/*.yaml`, loaded with `yaml.safe_load`. Each has `id`, `when` (a predicate over device and network facts), `severity`, `title`, `next_step` and `evidence_fields`.
- The engine is pure Python functions with no I/O, so it is fully unit-testable. It outputs `Finding { rule_id, severity, confidence_band, device_ref, evidence[], next_step }`.
- The room summary follows fixed logic:
  - Any High finding: **"Needs attention"**.
  - Any Medium finding: **"Check these items"**.
  - Otherwise: **"Nothing found by these checks"**, always followed by the list of what was not checked.

**AI explanation layer**

- Uses the Anthropic Messages API through the `anthropic` Python SDK. A fast model is enough, e.g. `claude-haiku-5-5` or `claude-sonnet-5-5`.
- **Data minimisation.** Send only device type, vendor name, evidence names, rule IDs and severity. Strip IPs, MACs, SSIDs and the user's location label.
- Prompt rules:
  - Write at a secondary-school reading level.
  - Never change or soften a severity, never say anything is "safe", never mention devices not in the input.
- **Structured output and validation.** Request JSON shaped like `{finding_id, explanation, why_it_matters}` through tool use. Validate it with Pydantic: every `finding_id` must exist, length capped at about 80 words, and a phrase list rejects "safe" and "no risk". On a validation failure, API error or 8 s timeout, use the template text in the rule YAML.
- Label every AI-written paragraph in the UI: "Explained by AI from the scan results. The risk level comes from fixed rules."
- Optional: Chinese, Malay and Tamil explanations, with English templates as the fallback.
- **Landlord / host message.** The AI drafts a polite message from the findings. The user edits and copies it. RoomCheck never sends anything itself.

**Handover report**

1. Render HTML with `Jinja2` and convert it to PDF with `WeasyPrint`.
2. Contents:
   - Scan date and time, plus an optional room label the user types.
   - Which checks ran and which didn't.
   - Findings with confidence and evidence, next steps, and known limits.
   - MACs masked to vendor plus the last 3 octets. Nothing about neighbours' devices.
3. **Tamper evidence.** Compute the SHA-256 of the PDF bytes (`hashlib`), then get an RFC 3161 timestamp token for that hash from a public timestamp authority (e.g. FreeTSA) using `rfc3161ng`. Save the `.tsr` token next to the PDF.
4. Be precise in the pitch. A hash alone proves the file hasn't changed, but not *when* it was made. The timestamp token proves the hash existed at that moment. It does not prove the findings are correct.
5. Offline fallback: with no internet, skip the token and tell the user to email the report to themselves and the landlord right away, which gives a weaker but practical dated record.
6. Add a "Verify a report" page: drop in the PDF and `.tsr`, and the app recomputes the hash and checks the token. The command-line equivalent is `openssl ts -verify`.

## Layer 6: handover assistant and move-in baseline

RoomCheck keeps working after the first scan. It turns findings into a tracked handover checklist, and remembers the room's state so a later re-scan shows what changed.

**Handover assistant**

- Each High or Medium finding creates a task with what to ask, who to ask (landlord, host or booking platform), a status (To do, Asked, Confirmed, Done) and a notes field.
- Tasks come from fixed templates per rule in YAML, at the level of device categories:
  - **Smart lock:** remove previous users, codes and fingerprints; confirm in writing.
  - **Router:** change the Wi-Fi password and the admin password.
  - **Cloud-linked device:** remove other accounts, or factory-reset and re-pair to the tenant's account.
  - **Camera:** where is it, what does it record, who can view it.
- For brand-specific steps, RoomCheck links to the maker's own support page. The AI may draft wording but never invents reset steps.
- The landlord message bundles all open tasks into one polite message. The user edits and sends it themselves.
- Task status and dates go into the PDF report.

**Move-in baseline and re-scan comparison**

- After the first scan, the user can save it as the move-in baseline. It's stored locally in SQLite, in the user's profile folder, and never leaves the laptop.
- What's stored:
  - **Per device on your network:** a matching key (the MAC; for randomised MACs, a soft key from hostname, services and vendor), type, open ports and findings.
  - **Nearby Wi-Fi and Bluetooth:** only flagged items, with BSSIDs and addresses kept as salted hashes.
- Encrypt the database with Windows DPAPI (`win32crypt` from `pywin32`), so other accounts on the laptop can't read it. There's a "Delete baseline" button.
- A re-scan, run any time, is compared against the baseline. Each item is marked New, Gone or Changed (e.g. a newly open port or a changed device type), and runs through the same rules.
  - A camera-like device that wasn't there at move-in becomes High: "A camera-like device appeared since your move-in scan on 3 Nov."
- Randomised MACs make matching imperfect. When only the soft key matches, show "possibly the same device", never a confident match.

## Frontend, UX and accessibility

A non-technical tenant can finish the first check in about 10 minutes, using seven screens that never assume they know what ARP or RTSP means. Technical detail stays one click away under "Why we think this", for judges and curious users.

**Stack**

| Part | Choice |
| --- | --- |
| Framework | React + TypeScript, built with Vite |
| Styling | Tailwind CSS with a small design-token file (colours, spacing, type scale) |
| Live data | Native WebSocket from FastAPI for scan progress and live locator readings; TanStack Query for REST calls |
| Charts | Recharts line chart of signal strength over the last 30 s for the locator |
| Strings | `i18next`, every user-facing sentence in one file, with optional translations |
| Audio cues | Browser `speechSynthesis` and a short tone for "warmer" or "colder" in the locator |
| Serving | FastAPI + Uvicorn bound to `127.0.0.1` only, so the dashboard isn't reachable from the network being scanned |

**Screens**

1. **Start.**
   - What RoomCheck checks, what it can't, and how long it takes.
   - One question: "Is this your network, or do you have permission to test it?" Yes unlocks the port checks. No or Not sure gives a passive-only scan.
2. **Scanning.** Step-by-step progress in plain words ("Listening for devices", "Checking the router", "Looking at nearby Wi-Fi") and a live device count.
3. **Results.**
   - A room summary banner, then device cards grouped by severity. Each card shows an icon, a text label, the confidence band, a "Why we think this" evidence list and one next-step button.
   - A "Network health" panel for the Layer 3 checks, and a permanent "What this scan can't see" panel.
4. **Nearby.** Wi-Fi and Bluetooth findings, each with a "Find it" button that opens the locator.
5. **Handover.** The task list with statuses, plus the landlord message draft.
6. **Compare.** Changes since the move-in baseline: New, Gone and Changed.
7. **Report.** A preview of the PDF, a download button and "Verify a report".

**Accessibility targets (WCAG 2.2 AA)**

- Text contrast at least 4.5:1. Severity is always shown as icon plus word, never colour alone.
- Full keyboard operation with visible focus. Progress and results are announced through `aria-live="polite"` regions.
- The locator's warmer/colder cue is given as text and sound, not only as a moving bar. Respect `prefers-reduced-motion` for animations.
- Plain language: sentences under 20 words and no unexplained acronyms. Every error message says what happened and what to do next.
- Check every screen with axe DevTools and a screen reader (NVDA on Windows) before submission.

## Trust, privacy and legal safeguards

RoomCheck is passive by default, processes everything locally, never logs in to anything, and never says a room is safe. Each safeguard below answers a question a judge could ask.

| Risk RoomCheck could create | Safeguard |
| --- | --- |
| Probing devices without permission | Consent gate before any port or banner check. Passive-only mode when the user isn't sure. A fixed port list, `-T3` timing and one retry. No credential attempts, no exploits, no changes to any device. |
| Collecting neighbours' data | Layer 4 reads only public broadcasts (network names, security settings, Bluetooth advertisements) and never connects. Only flagged items are kept, with BSSIDs and Bluetooth addresses stored as salted hashes. Everything else is discarded when the scan ends. |
| Leaking the user's data | Everything runs on the user's laptop. The baseline database is DPAPI-encrypted, with "Delete this scan" and "Delete baseline" buttons. Only three things go out, each optional: the AI call (no IPs, MACs, SSIDs or location), NVD queries (product names only) and the timestamp request (a hash only). No telemetry, no accounts. |
| False reassurance | No "safe" wording anywhere, enforced in the AI validator too. The summary reads "Nothing found by these checks", always with the "What this scan can't see" list. |
| False accusation of a landlord or host | Confidence bands and evidence on every finding. Lookalike-network and tracker findings say "possible". The message template asks questions ("Could you confirm what this device is?") rather than making claims. |
| Misuse to track or locate other people's devices | The locator only works on items RoomCheck has flagged as a possible risk in the user's own space. It shows signal strength, never stores locations, and keeps no history after the session. |
| The tool itself being attacked | Separate scanner worker with a fixed job allowlist. Dashboard bound to `127.0.0.1`. `defusedxml` for device XML. Timeouts and size caps on every network read. Subprocess calls with argument lists (never `shell=True`). Pinned dependencies. |
| AI overreach | AI never sets severity or verdicts, and never writes reset instructions. Output is schema-validated, with a template fallback. AI text is labelled. |

**Legal framing (not legal advice).** Singapore's Computer Misuse Act makes unauthorised access to computer material an offence. RoomCheck stays clear of it by design:

- It never logs in to anything.
- Active checks run only on networks the user owns or has permission to test.
- The nearby Wi-Fi and Bluetooth checks only read what devices already broadcast publicly.

Say this in the pitch, and add a line in the README advising users outside Singapore to check their local law.

**If a hidden camera is found, the app's guidance is:**

1. Don't destroy or unplug it yet. Photograph it where it is.
2. Leave the space if you feel unsafe.
3. Report it to the booking platform and the police. Secret recording in private spaces is a criminal offence in Singapore and many other countries.

## Error handling and failure modes

Each layer can fail on its own without stopping the scan. The UI says which checks ran, which were skipped and why, so a partial result is never shown as a complete one.

| Failure | Detection | What the user sees | Fallback |
| --- | --- | --- | --- |
| Npcap not installed | scapy can't open the interface | "RoomCheck needs a free network driver called Npcap. Install it, then try again." Includes the link. | Passive checks that don't need it (mDNS, SSDP) still run |
| Scanner worker can't start or lacks rights | IPC connect fails or the job returns a permission error | "The scanner couldn't start. Restart RoomCheck, or run it once as administrator." | Layers 4-6 unaffected |
| Not connected to any network | No default route | "Connect to the room's Wi-Fi first, or run only the nearby check." | Layer 4 only |
| Client isolation | Sweep finds only the gateway after 60 s | "This network hides devices from each other, so this check can't see them." | Recommend the nearby check |
| Subnet too large (above /22) | Netmask check | "This is a large shared network. We'll only listen, not sweep." | Passive-only Layer 1 |
| Nmap missing | `shutil.which("nmap")` is `None` | Setup check fails early, with the install link | Skip port checks and mark them "not run" |
| A device hangs or sends junk | Per-request timeouts (3 s HTTP, 30 s per nmap host), size caps, XML parse errors caught | The device card shows "Partly identified" | Score from whatever evidence was gathered |
| Location services off | The Wi-Fi network list comes back empty or access is denied | "Windows needs Location turned on to list nearby Wi-Fi. Open Settings, then Privacy & security, then Location." | Bluetooth scan still runs |
| Wi-Fi radio off or no wireless adapter | No WLAN interface found | "Turn on Wi-Fi to check nearby networks." | Wired-network checks still run |
| Bluetooth off or unsupported | `bleak` raises on start | "Turn on Bluetooth to check for nearby trackers." | Wi-Fi checks still run |
| Locator signal too unstable | Rolling spread above a set number of dB | "The signal is jumping around. Move more slowly and hold the laptop still." | Show the raw bar, with the "warmer/colder" words switched off |
| Baseline can't be decrypted (another Windows account, or a reinstall) | DPAPI error | "This saved scan belongs to another account or install. Start a new baseline." | New baseline |
| AI API down, slow or output invalid | Exception, an 8 s timeout or a Pydantic validation error | Nothing visible, apart from the explanation label switching to "Standard explanation" | YAML template text |
| NVD rate-limited (HTTP 403 / 503) | Status code | "Vulnerability lookup skipped for now." | SQLite cache and pre-cached demo data |
| Timestamp authority unreachable | Request error | "Couldn't get a trusted timestamp. Email the report to yourself now to keep a dated copy." | Hash still shown |

**Demo insurance.** Add a `--replay <session-folder>` mode that feeds a recorded real session through the same pipeline. If the live venue's Wi-Fi misbehaves, switch to replay and say so on camera. Being open about it scores better than a failed live demo.

## Testing and evidence plan

The Safety Benefit score depends on credible evidence, so RoomCheck ships with a small, honest measurement: how often each check caught a planted risk, how often it raised false alarms, and whether non-technical users understood the result.

**Automated tests**

- **Unit (pytest).**
  - Rules engine, noisy-OR scorer and DNS-check logic.
  - Information-element parsers (RSN, WPS) on byte fixtures.
  - Lookalike-network logic, with cases for mesh systems that share a name legitimately.
  - Baseline diff, including randomised-MAC soft matching.
- **Fixture tests.** Capture real `.pcap` files and Wi-Fi and Bluetooth scan results on your own network once, then replay them through every layer. These are deterministic, need no live network and double as the demo replay data.
- **Frontend.** TypeScript type-check, ESLint, and Playwright with `@axe-core/playwright` for automatic accessibility checks on every screen.
- **CI.** A GitHub Actions workflow on a Windows runner running `ruff`, `mypy`, `pytest`, the frontend build and the Playwright + axe suite on each push.

**Detection evaluation (on your own network and devices, at least 10 trials per row)**

| Scenario | Ground truth | What to measure |
| --- | --- | --- |
| Old phone running an IP-camera app on your Wi-Fi | Camera present | Layer 2 labels it "Likely" or "Possible camera" |
| Smart plug, laptop or TV only | No camera | False-alarm rate for the camera label |
| Phone hotspot named exactly like your Wi-Fi, with no password | Lookalike network | R-TWIN fires |
| Your real router plus a mesh node or extender, if you have one | Legitimate shared name | R-TWIN stays silent (false-alarm check) |
| Phone hotspot named like a camera setup hotspot | Camera-style hotspot | R-CAMHOT fires |
| Bluetooth tag or earbuds in a drawer | Tracker or Bluetooth device present | R-TRACKER or the correct Bluetooth device label, plus how close the locator gets (in metres) |
| Save a baseline, then add the camera phone and re-scan | New device | The Compare screen shows it as New and High |
| UPnP on and off in your router settings | Known state | R-UPNP matches the setting |

**Avoiding overfitting.** Tune the weights and thresholds using half the trials, then report results only on the other half. Publish the table in the README and on a demo slide as counts, e.g. "x of 10". Never claim a percentage you didn't measure.

**Usability check (3 to 5 people who don't work in tech)**

- Tasks: run a scan; explain in their own words what the top finding means; say what they would do next; find a Bluetooth device with the locator.
- Measure task completion, time taken and whether their explanation matches the finding.
- Fix the worst point of confusion before submission, and quote one participant (with consent) in the demo.

## Demo script

The demo runs about 3 minutes and covers the four things the Clarity criterion names: the problem, what was built during the event, credits and limitations. Change the timings if the event sets a different length.

| Time | Show | Say (key line) |
| --- | --- | --- |
| 0:00 to 0:20 | A rental-room set: the old phone propped on a shelf as a "camera", a laptop open on the bed | "You just moved in. What's connected here, who else controls it, and can you trust this Wi-Fi? Today you can't find out." |
| 0:20 to 0:35 | Start screen and the permission question | "It's my network, so I'll allow the full check. If I weren't sure, RoomCheck would only listen." |
| 0:35 to 1:05 | Live scan, then results: "Likely camera" card, then "Why we think this", then the Network health panel | "Three clues point to a camera. Fixed rules decide that. The AI only explains it in plain words." |
| 1:05 to 1:35 | Nearby screen: a phone hotspot copying the Wi-Fi name with no password is flagged; the locator finds a Bluetooth tag in a drawer | "This fake copy of the room's Wi-Fi could intercept everything you do. RoomCheck caught it with the laptop's own radios." |
| 1:35 to 2:00 | Handover screen: tasks and landlord message, then Compare: the baseline vs a re-scan with a new device | "Two weeks later, something new appeared. RoomCheck remembers what the room looked like when you moved in." |
| 2:00 to 2:15 | PDF report with hash and timestamp, then the Verify page | "A dated record I can show if there's a dispute." |
| 2:15 to 2:40 | "What this scan can't see" panel and the evaluation results table | "It can't see cameras on hidden networks or ones that record to an SD card. Here are our measured hit and false-alarm counts." |
| 2:40 to 3:00 | Credits and roadmap slide: built during the event vs reused; libraries; AirGuard, Lumos; future sensor version based on MotionCompass and SNOOPDOG | "Next version adds a small sensor for off-network cameras. Today's version needs nothing but the laptop you already own." |

**Recording tips**

- Record on your own home network.
- Keep a replay take ready. If you use it, say "this segment is a recorded session" on screen.
- Turn on captions in the video. Show the room summary with icon plus text so it reads in greyscale.

## Judging criteria mapping

The four criteria carry equal weight, and "complexity alone earns no bonus". So the technical stack is presented as the reason the result is reliable and trustworthy, not as the achievement itself.

| Criterion | What judges look for | Where RoomCheck earns it | Evidence to show |
| --- | --- | --- | --- |
| Safety Benefit | A clear problem for an identifiable user; credible evidence of a safer outcome | A named user (new tenant or short-stay guest); concrete risks (devices someone else controls, an untrustworthy network, lookalike Wi-Fi); tracked next steps | Detection evaluation table with real counts; usability-test result; sources on the problem |
| Practical Functionality | The core workflow works; reliability; sensible handling of errors | Everything runs on one laptop with no extra hardware; every layer fails independently with a plain message; replay mode | Live scan in the demo; one failure deliberately shown (e.g. turning Bluetooth off mid-demo) |
| Trust and Responsible Design | Privacy, appropriate data, uncertainty explained, no new risks, honest limitations | Passive by default; consent gate; public broadcasts only for nearby checks; hashed and encrypted local storage; confidence bands; "never safe" wording; AI explains only | The safeguards table; "What this scan can't see" panel; AI label in the UI |
| Clarity and User Experience | Intended user can understand and use it; accessibility; demo covers problem, contributions, credits and limits | Seven-screen flow; plain language; WCAG 2.2 AA targets; text-and-sound locator cues; landlord message draft | axe results; usability quote; the demo's credits and limits segments |

**Biggest risk to each score**

1. **Safety Benefit:** claiming more than you measured. Use counts and say "in our tests".
2. **Functionality:** the venue's Wi-Fi during a live demo. Use your own network and keep a replay ready.
3. **Trust:** a judge asking "couldn't the locator be used to track people?" Answer with the flagged-items-only rule and the no-history design.
4. **Clarity:** jargon creeping into the UI. Run the usability check before polishing visuals.

## Limitations, credits and references

**Limitations to state in the README and the demo**

- It can't see cameras that join a hidden or separate network as ordinary clients, or cameras that transmit nothing (SD-card only). Off-network detection needs sniffing hardware; that's future work.
- Device types, lookalike networks and tracker formats are probability-based hints from limited evidence. A determined attacker can change names, MAC addresses and transmit power.
- The locator gives a rough area, not an exact spot, and Wi-Fi readings update slowly on Windows.
- It can't identify who owns a cloud-linked account, and it can't confirm a device's exact firmware version without logging in, which it never does.
- Weights and thresholds were tuned on a small set of your own devices. Accuracy in crowded buildings (condos, hostels) will be lower.
- The timestamp proves when the report existed, not that its findings are correct.
- It's a prototype, not a certified inspection tool, and not legal advice.

**Credits (fill in before submission)**

- **Built during the event:** list every component built during the hackathon. Name anything brought in from before it, and confirm against the event's rules.
- **AI assistance:** if you use Claude Code or other AI tools to write code, say so here and in the demo, as the event's rules require.
- **Design principle carried over:** "AI explains, never decides", from the CyberCity project.
- **Open-source tools:** Scapy, Npcap, Nmap and python-nmap, zeroconf, ssdpy, WSDiscovery, mac-vendor-lookup, dnspython, httpx, defusedxml, bleak, pywin32, FastAPI, Pydantic, Jinja2, WeasyPrint, rfc3161ng, React, Vite, Tailwind CSS, Recharts, i18next, Playwright and axe-core.
- **Licences:** Scapy is GPL-2.0; Nmap and Npcap have their own licences that restrict redistribution. Check that the repo's licence is compatible, and link to Npcap rather than bundling it.
- **Data and services:** IEEE OUI registry, NIST NVD, FreeTSA (or another RFC 3161 authority), Anthropic API.
- **Research and prior work:** AirGuard (tracker signatures), Lumos (signal-strength location); MotionCompass and SNOOPDOG for the future sensor version.

**References**

- Sharma, Soltanaghaei, Rowe, Sekar. [Lumos: Identifying and Localizing Diverse Hidden IoT Devices in an Unfamiliar Environment](https://www.usenix.org/conference/usenixsecurity22/presentation/sharma-rahul). USENIX Security 2022.
- He, He, Fang, Liu. [MotionCompass: Pinpointing Wireless Camera via Motion-Activated Traffic](https://par.nsf.gov/servlets/purl/10289674). 2021.
- [I Always Feel Like Somebody's Sensing Me! A Framework to Detect, Identify, and Localize Clandestine Wireless Sensors (SNOOPDOG)](https://arxiv.org/pdf/2005.03068). arXiv 2005.03068.
- [Fing: How to find hidden cameras in an Airbnb or hotel](https://www.fing.com/?p=737).
- [nvdlib documentation: NVD API 2.0 usage and rate limits](https://nvdlib.readthedocs.io/en/latest/v2/CPEv2.html).