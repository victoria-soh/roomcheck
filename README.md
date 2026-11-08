# RoomCheck

A digital move-in inspection: find out what's watching or controlling your room before you unpack.

RoomCheck is a Windows laptop app with a local web dashboard. In about 2 minutes it checks the
network you've joined and the signals around you, then answers four plain questions: Is anything
watching? Can someone else control things here? Can you trust this Wi-Fi? What's changed since
move-in? Each finding has its evidence, a fixed priority and a next step, and you can keep a
timestamped PDF handover report.

## Who it's for

People moving into a rented room or flat, or checking into a short stay or hostel. They aren't
security specialists and have no admin access to the network. RoomCheck needs no extra hardware
and no account.

## Quick start

### Try it in 2 commands, no network access needed

Demo mode runs the whole dashboard on made-up data: a demo check with the progress screen,
Results, Nearby, Handover, Compare (with a demo move-in scan), Report and Verify. It runs no
scans, probes or outside calls, says "Demo data" on every page, and keeps nothing.

```
uv sync && npm --prefix web install && npm --prefix web run build && uv run playwright install chromium
uv run python -m app --demo
```

Then open http://127.0.0.1:8765. The first command downloads the dependencies once (it needs
[uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/) 22 or later); the demo itself
never touches the network. Every demo check is built by RoomCheck's own pipeline from made-up
inputs (192.0.2.x addresses, the network "Example-Home", made-up makers and CVE), the same ones
behind the [screenshots](docs/screenshots/design-pass/) and the
[demo report](tests/fixtures/report/demo_preview.pdf). AI explanations stay off unless you add
an Anthropic API key; reports are never timestamped in demo mode.

### A real check (Windows 11)

Only check a network you own or have permission to test.

1. Install [Npcap](https://npcap.com/#download) (free; its licence doesn't allow bundling it).
   Optional: [Nmap](https://nmap.org/download) for the service check in a full check.
2. Install [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/) 22 or later.
3. `uv sync`, `npm --prefix web install`, `npm --prefix web run build`, and once
   `uv run playwright install chromium` (it makes the PDF report).
4. Optional: copy `.env.example` to `.env` and add an Anthropic API key for AI-worded
   explanations.
5. `uv run python -m app`, then open http://127.0.0.1:8765. The server listens on this laptop
   only.
6. Answer the permission question. "Yes, I have permission" runs the full check; "No, or I'm not
   sure" only listens for what devices already announce.

The same checks run from the command line:

- `uv run python -m app.cli discover`: a listening-only check. Add `--consent` for the full check.
- `uv run python -m app.cli nearby`: nearby Wi-Fi and Bluetooth only (about 30 s).
- `uv run python -m app.cli report [--consent] [--room-label "Room 4B"]`: a full check and the
  PDF handover report, with its SHA-256 (`.sha256`) and an RFC 3161 timestamp (`.tsr`).
- `uv run python -m app.cli verify REPORT.pdf`: check a report's hash and timestamp.

## How it works

Six layers, each with its own tests:

1. **Finding devices:** listens to the network (ARP, DHCP, mDNS), and with permission also asks
   every address to answer, plus UPnP and ONVIF discovery.
2. **Identifying them:** makers from the IEEE OUI list, names and services, scored into device
   types with an identification confidence (Likely, Possible, Unclear).
3. **Checking the network:** Wi-Fi encryption, address lookups (DNS), who answers for the router,
   a second address server, UPnP and known issues for identified models (NIST NVD).
4. **Nearby signals:** copies of your Wi-Fi's name, camera-style setup hotspots, hidden networks,
   WPS and Bluetooth trackers, with a warmer/colder locator.
5. **Findings and the report:** fixed rules (`app/rules/rules.yaml`) set every priority. AI, when
   turned on, only words the explanations and never changes a priority. The PDF report gets a
   SHA-256 fingerprint and a trusted timestamp.
6. **Handover:** tasks and a message to your host, a move-in scan saved on this laptop, and a
   comparison with later checks.

A separate scanner worker (`scannerd`) does the raw network work, and accepts only named jobs
with checked parameters. The architecture and the reasoning behind each layer are in
[docs/original-plan.md](docs/original-plan.md#system-architecture-and-repo-layout).

## What's sent

Everything runs on this laptop. Only these optional calls go out:

- AI explanations (off unless you add an Anthropic API key): send each finding's rule and wording, with the device type and maker. Never addresses, device names or network names.
- Known-issue lookups (on in a full check): product names are sent to NIST's vulnerability database.
- Trusted timestamps (on by default when you make a report; you can turn them off): only the report's fingerprint (hash) is sent to freetsa.org.

## Your data

The move-in scan, your answers, task notes and a random matching key are stored only on this
laptop, in `%LOCALAPPDATA%\RoomCheck\baseline.db`, encrypted with Windows DPAPI for your account.
Reports are saved in `%LOCALAPPDATA%\RoomCheck\reports`. Help → Your data deletes the move-in scan
or everything RoomCheck keeps (report files stay until you delete them).

## Limitations

- It can't see cameras that join a hidden or separate network as ordinary clients, or that only
  record to a memory card and send nothing. Devices that stay silent for the whole check aren't
  seen either.
- Device types, makers, lookalike networks and tracker formats are clues, not proof. Names and
  addresses can be changed by whoever set a device up.
- The locator gives a rough area, not an exact spot.
- It can't tell who owns a cloud-linked account, or a device's exact firmware version: that would
  need logging in, which RoomCheck never does.
- Weights and thresholds were tuned on a small set of home devices; crowded buildings will be
  harder.
- The timestamp shows when the report existed, not that its findings are correct.
- Windows 11 only. It's a prototype, not a certified inspection, and not legal advice.

## Built during the event, and before it

- **Built during SafeSpace Hacks (from 2 Nov 2026):** everything in this repository: the scanner
  worker, the checks and rules, the API, the dashboard, the PDF report, the tests and these docs.
- **From before the event:** the design principle "AI explains, never decides", carried over from
  the CyberCity project, and the third-party tools, data and fonts credited below.

## Development

- `uv run pytest`, `uv run ruff check .`, `uv run mypy app scannerd`: Python tests, lint and types.
- `npm --prefix web test`, `npm --prefix web run typecheck`, `npm --prefix web run lint`: dashboard
  component tests, types and lint.
- `npm --prefix web run test:e2e`: browser and accessibility tests (Playwright and axe) against
  mocked data.
- `npm --prefix web run test:demo`: demo mode end to end against the real `--demo` server,
  including that the page makes no request outside 127.0.0.1 (uses port 8765).
- `uv run python -m app` and `npm --prefix web run dev`: the dashboard with live reload on
  http://127.0.0.1:5173 (Vite proxies `/api` to the backend).
- [docs/README.md](docs/README.md) lists the design system, live-test evidence and the original
  plan.

## Credits

- **Libraries:** Scapy, python-nmap, zeroconf, dnspython, bleak, psutil, defusedxml, httpx,
  FastAPI, Uvicorn, Pydantic, Jinja2, rfc3161ng, Playwright, PyYAML, websockets, pywin32 and the
  Anthropic Python SDK; React, TanStack Query, i18next, lucide-react, Recharts, Vite, Tailwind CSS,
  Vitest, Testing Library and axe-core.
- **Tools:** Npcap and Nmap (installed separately, not bundled).
- **Data and services:** the IEEE OUI registry, the NIST National Vulnerability Database, FreeTSA
  and the Anthropic API.
- **Fonts:** all bundled (no font is fetched from the internet) and under the SIL Open Font
  License 1.1: Plus Jakarta Sans (headings, and digits in body text), Atkinson Hyperlegible Next
  (body text), JetBrains Mono (fingerprints and other machine values) and Saira (the wordmark).
  See [FONT-LICENSES.md](FONT-LICENSES.md).
- **Research:** Sharma et al.,
  [Lumos](https://www.usenix.org/conference/usenixsecurity22/presentation/sharma-rahul) (USENIX
  Security 2022), for locating hidden IoT devices by signal strength;
  [MotionCompass](https://par.nsf.gov/servlets/purl/10289674) and
  [SNOOPDOG](https://arxiv.org/pdf/2005.03068) for finding wireless cameras and sensors;
  AirGuard for tracker signatures; and
  [Fing's guidance](https://www.fing.com/?p=737) on finding hidden cameras.
- **AI assistance:** RoomCheck was built with help from Claude Code (Anthropic) for code, tests and
  docs, and Claude for planning and review. Inside the app, Claude only words explanations, and
  only when you add an API key.

## Licence

[MIT](LICENSE). Third-party components keep their own licences: Scapy is GPL-2.0, and Npcap and
Nmap have their own terms and aren't bundled.

## Legal note

RoomCheck never logs in to devices or tries passwords, and runs active checks only after you
confirm you have permission. Checking devices on a network without permission may be against the
law in many places, so check your local law. This is not legal advice.
