# Live recheck results

Run on 6 Nov 2026 on the tester's own home Wi-Fi ("Example-Home"), with the owner's permission
for a full check. Procedure: [live-tests.md, Recheck procedure](live-tests.md#recheck-procedure). Before every check a script confirmed
the laptop was on that network. The app ran as `uv run python -m app` (code from 5 Nov 2026,
dashboard built 6 Nov 2026) with its terminal output captured; the dashboard was driven with
Playwright (headless Chromium on 127.0.0.1). Addresses below are masked (192.0.2.x), MACs and
network names too. Nothing was fixed during the run.

| # | Item | Result |
|---|------|--------|
| 1 | Live test 3: camera-style setup hotspot | Pending (needs the iPhone) |
| 2 | Live test 4: Wi-Fi locator | Pending (needs the iPhone) |
| 3 | B1: host message "I", "the device that may be a camera" | Pass |
| 4 | B2: PDF Limitations vocabulary | Pass |
| 5 | B3: UPnP label | Pass |
| 6 | B4: WPS next step | Pass |
| 7 | B5: address sweep in dashboard full checks | Pass (4 of 4, and 6 of 6 valid checks) |
| 8 | B6: a check started right after another | Pass |
| 9 | B7: cancel, then start again at once | Pass |
| 10 | B8: report without a timestamp | Pass (log proof missing, see "Log notes") |
| 11 | B9: Create report with Wi-Fi off | Pending (needs Wi-Fi off) |
| 12 | B10: after Wi-Fi drops and rejoins | Pending (needs Wi-Fi off/on) |
| 13 | B11: host message follows the offered tasks | Pass |
| 14 | B12: delete all data clears the room label | Pending (asks to delete saved data) |

## 3. B1: host message — Pass

`uv run python -m app.cli report --consent --room-label "Home test"` (AI: used). The AI draft:
"Hello, I am staying in the room and ran a quick check of the Wi-Fi and connected devices. Could
you confirm what the device that may be a camera is, and whether it is in use? Could you also
tell me who has access to it? I would also like to ask whether the Wi-Fi router has WPS turned
on, and if so whether the PIN option is disabled. Thank you." First person throughout; no "we",
"our", "the camera" or "the camera device".

Log: `scannerd: arp_sweep: 10 hosts in 28.6 s`, `scannerd: job passive_listen finished in 60.2 s`,
`scannerd: job port_scan finished in 11.8 s`, `scannerd: job dhcp_probe finished in 5.3 s`.

## 4. B2: PDF Limitations — Pass

The CLI report's PDF, Limitations: "Device types, lookalike networks and tracker formats are
unconfirmed: clues, not proof." No "from limited evidence" anywhere in the PDF.

## 5. B3: UPnP label — Pass

CLI "Checks:" and the PDF's Coverage and limits table: "Checking whether the router advertises
UPnP controls". Also seen in the dashboard's Coverage and limits.

## 6. B4: WPS next step — Pass

PDF and CLI: "Next step: Ask the host whether WPS can be switched off." The PIN sentence appears
only in the explanation / why it matters.

Also seen in this PDF: priority icon + word ("Priority: Medium"), no "[!!]" markers; banner
"Findings by priority: High 0 · Medium 2 · Low 0 · Info 1 · Nearby signals …"; "Coverage and
limits: 18 checked · 0 not checked"; "Network checked 192.0.2.x/22".

## 7. B5: address sweep — Pass

Four full dashboard checks back to back (checks 1-4), then two more (checks 5 and 7) during
other items. Every valid check: "Asking every address on this network to answer" Checked, all
five tasks Done, "All 18 parts of the check ran", Coverage and limits "18 checked · 0 not
checked".

| Check | Sweep log line | Other worker jobs |
|---|---|---|
| 1 | `scannerd: arp_sweep: 10 hosts in 32.0 s` | passive_listen 60.3 s, port_scan 14.7 s, dhcp_probe 5.3 s |
| 2 | `scannerd: arp_sweep: 9 hosts in 30.5 s` | passive_listen 60.4 s, port_scan 3.9 s, dhcp_probe 5.2 s |
| 3 | `scannerd: arp_sweep: 9 hosts in 30.1 s` | passive_listen 60.4 s, port_scan 4.0 s, dhcp_probe 5.3 s |
| 4 | `scannerd: arp_sweep: 10 hosts in 30.9 s` | passive_listen 60.4 s, port_scan 8.1 s, dhcp_probe 5.3 s |
| 5 (after cancel) | `scannerd: arp_sweep: 9 hosts in 30.8 s` | passive_listen 60.2 s, port_scan 4.1 s, dhcp_probe 5.3 s |
| 7 | `scannerd: arp_sweep: 9 hosts in 29.9 s` | passive_listen 60.4 s, port_scan 6.0 s, dhcp_probe 5.3 s |

None said "stopped at its limit". Devices found: 7-8 per check; findings each time: Likely
camera (High), WPS (Medium), known issues (Info).

**Check 6 is excluded (not a RoomCheck result):** the laptop went into Modern Standby about a
minute into it (Windows System log, Kernel-Power 506 at 19:00:28; out at 19:07:51; in again
19:07:51-19:11:20, network "Disconnected" in standby). The log shows
`scannerd: job passive_listen finished in 485.4 s` and `scannerd: job dhcp_probe finished in
205.5 s`; the check ended "done" after 721 s with "Partly identified…" and "The network's address
lookups didn't answer clearly…". A keep-awake helper was started after this, but its output shows
it failed at once (a number-type error in the Windows call), so it never held the laptop awake;
the laptop simply didn't sleep again during the later items.

## 8. B6: a check right after another — Pass

Check 2 started about 2 s after check 1 finished, check 4 likewise after 3: each `POST /api/scans`
answered `202 Accepted`, the first task line was "Scanning devices and nearby signals" at once,
and no "The scanner couldn't start… run it once as administrator". "Finishing the previous
check…" never appeared because no worker job was left running.

## 9. B7: cancel — Pass

Cancel 12 s into a full check: "Stopping…" shown, then "Check cancelled" 2.0 s after confirming
("You cancelled this check. Nothing from it was kept."). **Start again** → Yes → Start full check
straight away: accepted, and that check (5) ran in full.

Log: `"POST /api/scans/<id>/cancel HTTP/1.1" 200 OK`, then `"POST /api/scans HTTP/1.1" 202
Accepted` (no 409), then a normal `scannerd: arp_sweep: 9 hosts in 30.8 s`.

## 10. B8: report without a timestamp — Pass

Report → room label "Home test" → Trusted timestamp unticked → Create report; answered in
6.6 s. What happened: "AI explanations: Added", "Trusted timestamp: Not requested". Tamper
evidence: "This report has no trusted timestamp." then "Without a timestamp, nothing shows when
this report was made. Its fingerprint only shows whether the PDF changes after this, and neither
proves the findings are correct." No "since it was timestamped". Label kept.

Log: `"POST /api/report HTTP/1.1" 200 OK`. **No `report: PDF in … s, timestamp in … s` line was
printed** (see Log notes).

## 13. B11: host message follows the offered tasks — Pass

Results → Likely camera card → **Mine** ("Answer changed to Mine", next step "You said this is
yours, so there's nothing to ask the host about it…"). Handover: 1 open task (WPS); Draft message
to host: "Asks about 1 open task". The message:

> Hello,
>
> I checked the devices and Wi-Fi where I'm staying and have a question:
>
> 1. The Wi-Fi router advertises WPS. Could you turn it off in the router's settings?
>
> Thank you for your help.

No camera, first person, numbered. Log: `"POST /api/answers HTTP/1.1" 200 OK`, no errors.

## Log notes

- **`report:` lines never appear.** `app/report/render.py` logs "report: PDF in … s, timestamp in
  … s" at INFO through the `app.report.render` logger, but nothing configures Python logging in
  the app process (`app/__main__.py` only starts uvicorn, which sets up its own `uvicorn.*`
  loggers), so INFO from `app.*` is dropped. The `scannerd:` lines show because the worker
  process calls `logging.basicConfig` itself. Suspected fix area: configure logging for `app.*`
  at startup.
- One `ConnectionResetError: [WinError 10054]` traceback from asyncio's Proactor transport
  (`_call_connection_lost`) during check 6, when the laptop slept with the dashboard's
  WebSocket open. Harmless, but noisy.
- The cancelled check left no `scannerd:` lines (its worker was restarted), as expected.
- The camera's identification varied between runs: "Likely" in the dashboard checks, "Possible"
  in the CLI run (where the camera showed no open ports and was matched by its ONVIF answer).
