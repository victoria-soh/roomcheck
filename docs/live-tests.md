# Pending live tests

Live tests run on your own network and devices, after the layers are built. Each one says
exactly how to set up, what to run, and what should happen. Add to this file whenever a step
leaves a live test pending; move a test to "Done" with the date and result when it has run.

## Before every live run

- Laptop on your home Wi-Fi ("Example-Home"), Windows 11.
- Settings → Privacy & security → Location: **on** (Windows needs it to list nearby Wi-Fi).
- Bluetooth: **on**.
- iPhone: Settings → Personal Hotspot → **Maximise Compatibility on**, and keep that screen
  open and the phone awake during the run (iOS stops broadcasting a hotspot nothing is
  connected to). The hotspot's name is always the phone's own name
  (Settings → General → About → Name).

## Rechecks after the 5 Nov fixes (bugs B1-B12, docs/bugs-from-live-tests.md)

Pending. Restart RoomCheck after `uv sync` and `npm --prefix web run build` first. "Example-Home"
stands for your own Wi-Fi's name everywhere in this file.

- **Test 6 (B1-B4):** `report --consent --room-label "Home test"`. The host message says "I",
  never "we" or "our", and "the device that may be a camera", never "the camera" (an AI draft
  that breaks this falls back to the standard one: "AI: rejected", reason `not_first_person`,
  `camera_overclaim` or `mentions_excluded`). The PDF's Limitations say "unconfirmed: clues, not
  proof"; "What was checked" says "Checking whether the router advertises UPnP controls"; the
  WPS next step is only "Ask the host whether WPS can be switched off."
- **Test 7 (B5-B7):** run four full checks back to back from the dashboard. Each time,
  "Asking every address on this network to answer" is Done (not "took too long"), and the
  terminal shows `scannerd: arp_sweep: N hosts in X s` (send that line if one says "stopped at
  its limit"). Start one right after another: at most "Finishing the previous check…", never
  "run it once as administrator". Cancel a check: "Stopping…" for a second or two, then "Check
  cancelled", and **Start again** works straight away.
- **Test 10 (B8, B9):** a report with Trusted timestamp off says "Without a timestamp, nothing
  shows when this report was made…". With Wi-Fi off, **Create report** finishes within about
  15 s with "Unavailable: …this laptop isn't connected to a network…" and **Try again**; turn
  Wi-Fi on and Try again gives "Added". The terminal's `report: PDF in … s, timestamp in … s`
  line shows where any wait went.
- **Test 11 (B10-B12):** turn Wi-Fi off and on (or let it rejoin with a new address) without
  restarting RoomCheck: Start shows the network again, and a check finds devices. On Handover,
  with the camera answered **Mine**, **Draft message to host** never mentions a camera, and is
  numbered, in the first person. Help → **Delete all saved RoomCheck data** → back to Report:
  the room label is empty, with no "Filled in from your last report".

## Recheck procedure

How the fixes for B1-B12 ([bugs-from-live-tests.md](bugs-from-live-tests.md)) are rechecked
live; the results of the 6 Nov 2026 run are in [recheck-results.md](recheck-results.md).

- Only on your own home Wi-Fi ("Example-Home" stands for its name). Confirm the laptop is on it
  before every check; if not, stop. Answer the permission question "Yes" only for that network.
- Mask MACs, IP addresses (192.0.2.x) and network names in anything written down.
- Run `uv run python -m app` (dashboard on http://127.0.0.1:8765) with its terminal output
  captured to a log. Log prefixes: `scannerd:` (the scanner worker), `report:` (report stage
  times).

| # | Item | How | Expected (and log proof) |
|---|---|---|---|
| 1 | Test 3: camera-style setup hotspot | Phone renamed `IPCAM-7F3A21`, hotspot on and awake within 1-2 m; Start → Yes → results → Nearby (or `app.cli nearby`) | A Medium "Possible camera setup hotspot" card with **Locate signal**; no `scannerd:` errors |
| 2 | Test 4: Wi-Fi locator | Someone hides the phone; **Locate signal**, walk slowly, pause about 4 s per spot | Warmer near the phone, colder away; note how close you got; locator requests answered 200 |
| 3 | B1: host message | `app.cli report --consent --room-label "Home test"` with an AI key | First person, "the device that may be a camera"; a draft that breaks this falls back ("AI: rejected") |
| 4 | B2: PDF Limitations | The PDF from item 3 | "unconfirmed: clues, not proof" |
| 5 | B3: UPnP label | The CLI "Checks:" list and the PDF from item 3 | "Checking whether the router advertises UPnP controls" |
| 6 | B4: WPS next step | The R-WPS finding in the PDF and on Results | Only "Ask the host whether WPS can be switched off." |
| 7 | B5: address sweep | Four full checks back to back from the dashboard | The sweep is Done each time; one `scannerd: arp_sweep: N hosts in X s` per check |
| 8 | B6: a check right after another | New check → Yes → Start within seconds | At most "Finishing the previous check…", no scanner start error |
| 9 | B7: cancel | Cancel a full check, then Start again at once | "Check cancelled" within a second or two; no HTTP 409 |
| 10 | B8: report without a timestamp | Report → untick Trusted timestamp → Create report | "This report has no trusted timestamp." |
| 11 | B9: Wi-Fi off during Create report | Wi-Fi off → Create report; Wi-Fi on → Try again | "Unavailable" within about 15 s with choices kept; then "Added" |
| 12 | B10: Wi-Fi drops and rejoins | Wi-Fi off and on without restarting RoomCheck; reload Start → check | The network shows again and devices are found (`arp_sweep` N > 0) |
| 13 | B11: host message follows the tasks | Camera answered **Mine** → Handover → Draft message to host | No camera mentioned; first person; numbered |
| 14 | B12: delete clears the room label | **Deletes all saved data: ask first.** Report with a label → Help → Delete all saved RoomCheck data → Report | The label is empty and its hint gone (`DELETE /api/data` 200) |

## 1. R-TWIN-DOWNGRADE: WPA2-only copy of your Wi-Fi (Layer 4)

- **Result (4 Nov 2026): Pass.** Medium R-TWIN-DOWNGRADE for the iPhone hotspot named like the
  home Wi-Fi: maker unknown (private address), WPA2, 2.4 GHz, -56 dBm. R-TWIN and R-TWIN-VENDOR
  silent; mesh nodes not flagged as lookalikes; R-WPS fired for them.

- **Setup:** rename the iPhone to exactly `Example-Home` (same letters and case, no spaces).
  Personal Hotspot on, screen open. Phone within 1-2 m of the laptop.
- **Run:** `uv run python -m app.cli nearby`
- **Expect:** a Medium **"Possible downgrade lookalike of your Wi-Fi"** [R-TWIN-DOWNGRADE]
  pointing at a `"Example-Home"` network with maker unknown (private address), WPA2, 2.4 GHz,
  stronger than -60 dBm. R-TWIN and R-TWIN-VENDOR should stay silent, and your TP-Link mesh
  nodes should not be flagged. R-WPS will still fire for the TP-Link nodes.
- **Why pending:** on 3 Nov the phone was still named "iPhone", so the hotspot was heard
  (WPA2, -44 dBm) but didn't share the name.

## 2. AirPods Pro proximity-pairing label (Layer 4)

- **Result (4 Nov 2026): Pass.** Case open next to the laptop: "Also heard, then discarded" counted
  3 earbuds, headphones or speakers; no R-TRACKER.

- **Setup:** AirPods Pro **in their case**, case lid **open**, next to the laptop (not in your
  ears). Can be done in the same run as test 1.
- **Run:** `uv run python -m app.cli nearby`
- **Expect:** the "Also heard, then discarded" line counts at least 1 of
  "earbuds, headphones or speakers". No R-TRACKER (their format says the owner is near).
- **Why pending:** on 3 Nov no Apple 0x07 (proximity pairing) record was heard at all,
  most likely because the case was closed.

## 3. Run 2: camera-style setup hotspot (Layer 4)

- **Status (4 Nov 2026): Not run, still pending.** Postponed by the tester. Also check here, while
  the R-CAMHOT item is flagged: on Nearby, the flagged card's Help identify this panel offers
  **Locate signal**, and unflagged items don't (left over from test 9).

- **Setup:** rename the iPhone to exactly `IPCAM-7F3A21`. Personal Hotspot on, screen open.
- **Run:** `uv run python -m app.cli nearby`
- **Expect:** a Medium **"Possible camera setup hotspot"** [R-CAMHOT] for
  `"IPCAM-7F3A21"`, with the evidence "matches the name mentions a camera" and
  "Names and makers are hints, not proof".

## 4. Run 3: Wi-Fi locator on the camera-style hotspot (Layer 4)

- **Status (4 Nov 2026): Not run, still pending.** Postponed with test 3.

- **Setup:** same as test 3. Put the phone somewhere in the room (e.g. in a drawer) without
  telling the person holding the laptop where.
- **Run:** `uv run python -m app.cli locate`, then pick the R-CAMHOT item.
- **Do:** walk slowly round the room holding the laptop the same way throughout. Each reading
  takes about 4 s; pause at each spot.
- **Expect:** the bar rises and says WARMER near the phone, "colder" walking away; "The signal
  is jumping around..." if you move too fast. Record how close (in metres) you got to the
  phone, for the evaluation table. Ctrl+C to stop; nothing is saved.
- **Not tested live, by decision:** the Bluetooth locator (flagged-items-only rule kept; unit
  tests cover it).

## 5. DHCP client-ID check (Layer 3)

- **Result (4 Nov 2026): Pass.** One offer, from the router, of the laptop's current lease
  (the lease had changed since 3 Nov, so the new one was used); no R-DHCP; lease unchanged after.

Addresses here are masked (192.0.2.x); use your own laptop's and router's.

Checks that the router offers the laptop's current lease (192.0.2.60) back, not a new
address, because the probe sends the laptop's own client ID (option 61).

- **Setup:** laptop on your home Wi-Fi, which you're allowed to test. Confirm its current
  lease is still 192.0.2.60 (`ipconfig`, "IPv4 Address" under the Wi-Fi adapter); if it
  has changed, use the new address below.
- **Run:** `uv run python -m app.cli discover --consent --json` (the DHCP probe needs consent).
- **Expect:** under `network_facts.dhcp_offers`, exactly one server (your router,
  `server_id` 192.0.2.1) with `offered_ip` **192.0.2.60**, the current lease. Any other
  address means the router treated the probe as a new client: that's a failure. R-DHCP should
  not fire. Afterwards, `ipconfig` still shows 192.0.2.60.

## 6. AI explanations live (Layer 5)

- **Result (4 Nov 2026): Partial.** All 3 explanations and the host message "AI: used",
  severities unchanged, R-CAM says "on this network"; 3 Nov and new PDFs mask addresses and show
  only the home network's name. Host message wording fails (B1); B2-B4 also logged.

- **Setup:** `ANTHROPIC_API_KEY` set in `.env`; internet access; laptop on your home Wi-Fi.
- **Run:** `uv run python -m app.cli report --consent --room-label "Home test"`
- **Expect:** "Explanations (AI: used)", each finding labelled "Explained by AI from the scan
  results. The risk level comes from fixed rules.", and a host message labelled "Drafted by
  AI...". Read them: plain words, questions not accusations, severities unchanged.
- **Since then:** rechecked live on 6 Nov 2026 (AI used, host message wording passes); see
  [recheck-results.md](recheck-results.md), items 3-6.

## 7. Dashboard, Part A: Start, Scanning, Results (frontend)

- **Result (4 Nov 2026): Partial.** Steps, live updates (one connection, no drops), results,
  Cancel, "Not sure", keyboard and 200% zoom all fine; NVDA skipped. Address sweep timed out
  (B5), "scanner couldn't start" on a back-to-back check (B6), cancel took ~20 s (B7).

- **Setup:** `npm --prefix web install` and `npm --prefix web run build` once; then
  `uv run python -m app`; open http://127.0.0.1:8765 in Edge or Chrome.
- **Do:** answer "Yes" (your own network), start the check, watch the steps, then read the
  results. Repeat once with "Not sure". Try it with the keyboard only, at 200% zoom
  (Ctrl and +), and with NVDA.
- **Expect:** steps in plain words, a rising device count, failures listed inline while the
  scan carries on; results with the summary banner, cards by severity (icon and word), "Why
  we think this", the explanation label, Network health and "What this scan can't see".
  "Not sure" shows "Listening only".
- **Since then:** rechecked live on 6 Nov 2026 (six full dashboard checks, back to back, with
  a cancel); see [recheck-results.md](recheck-results.md), items 7-9.

## 8. Move-in baseline, re-scan comparison and handover (Layer 6)

- **Result (4 Nov 2026): Partial.** Steps 1-3, 5-7 pass: answers, task status and note survive
  a restart; baseline.db has no readable addresses, device or network names (76 strings
  checked); the iPhone rejoining with a different address shows as New, not a confident match;
  PDF lists tasks with statuses and dates; Delete move-in scan keeps tasks, notes and answers.
  Step 4 not tested (no physical access to the camera). DPAPI other-account path not tested.

- **Setup:** laptop on your home Wi-Fi; RoomCheck restarted after `uv sync` (it now needs
  pywin32 for DPAPI). The Tapo camera and your phone on the Wi-Fi.
- **Do:**
  1. Run a check, answer "Do you recognise this device?" on a few cards (e.g. the camera:
     "Mine"; the router: "The host's"), change one task to "Asked" with a note,
     then on Results choose **Save as my move-in scan**.
  2. Check the file exists: `%LOCALAPPDATA%\RoomCheck\baseline.db`. Open it in a text editor:
     no MAC, IP, device or network names should be readable.
  3. Close and restart RoomCheck, run a second check: the answers and the task status and
     note should still be there (Handover page), and Compare should show the move-in date.
  4. Unplug the camera (or turn its Wi-Fi off), run a check: Compare shows it under **Gone**.
     Plug it back in and run again: it's matched again (not New).
  5. Turn the phone's "private Wi-Fi address" setting on for this network so it rejoins with a
     new MAC, then run a check: it should be "Possibly the same device" or New, never a
     confident match.
  6. Make a report: the PDF should list the handover tasks with their statuses and dates.
  7. Compare → **Delete move-in scan** → confirm: Compare offers "Save a starting point" again,
     and the Handover tasks and notes are still there (only the move-in scan is deleted).
- **Not tested live:** a camera that's new since the move-in scan (R-NEW-CAMERA) needs a second
  camera-like device; unit tests cover it. The DPAPI failure path (another Windows account)
  needs a second account: copy `baseline.db` into that account's
  `%LOCALAPPDATA%\RoomCheck\`, start RoomCheck there, and expect "This saved scan belongs to
  another account or install. Start a new move-in scan."

## 9. Recheck a fix, Help identify this, and the new logo

- **Result (4 Nov 2026): Partial.** Recheck with WPS on: "WPS is still on.", no "Observed by
  RoomCheck" (twice). Help identify this (on the camera card after answering Unknown), PDF
  Handover table (Host confirmed + recheck sentences), teal mark and Saira in the PDF, favicon,
  fonts local with no outside requests: all pass. Not tested: WPS off and camera unplug (no access
  to the router app or the camera); R-LOCK/R-CLOUD didn't fire. Nearby's **Locate signal** is
  checked in test 3.

- **Setup:** laptop on your home Wi-Fi ("Example-Home"), which you're allowed to test; RoomCheck
  restarted after `npm --prefix web install` and `npm --prefix web run build` (the Saira font
  and the favicon set are new). Run one check with **"Yes"** (rechecking Telnet or UPnP needs a
  check with permission).
- **Recheck WPS (Wi-Fi survey only):** R-WPS fires for your TP-Link mesh. On Handover, set
  "Ask for WPS to be turned off on the router" to **Done**, choose **Recheck this** (about 30 s):
  with WPS still on, expect "WPS is still on." and no "Observed by RoomCheck" label. Then turn
  WPS off in the TP-Link app or router page, recheck again, and expect "WPS is now off on that
  router." with **Observed by RoomCheck**. Turn WPS back on afterwards if you want it.
- **Recheck a camera gone (device discovery):** set the Tapo camera's task ("Ask about the
  device that looks like a camera") to **Host confirmed**, unplug the camera, then **Recheck
  this** (about a minute): expect "The device wasn't seen this time. A quiet device can be
  missed, so look in the room too." and **Observed by RoomCheck** next to **Host confirmed**.
  Plug it back in and recheck: "The device is still on this network."
- **Can't check:** if R-LOCK or R-CLOUD fires, their tasks should say "RoomCheck can't check
  this. It relies on the host's confirmation." and offer no recheck button.
- **Report:** make a report and check the Handover tasks table shows both labels and the
  recheck sentences, and the header shows the teal mark with "RoomCheck" in Saira.
- **Help identify this:** it appears on a *finding card* whose device has no maker and no type,
  or once you answer **Unknown** to "Do you recognise this device?" (devices with no findings, such
  as most phones, have no card). Answer **Unknown** on the camera card, then open **Help identify
  this**: its clues, why it can't be located, name and note, then Mine / Host's / Unknown. On
  Nearby, the panel's step 2 offers **Locate signal** for the flagged item only.
- **Logo:** the Edge tab shows the new favicon (the house-cut shield); F12 → Network shows
  `saira-latin-600-normal…woff2` loaded from 127.0.0.1:8765 and nothing from Google Fonts.

## 10. Trust fixes: counts, scope, saving, status vs evidence, Compare, Report, Verify

- **Result (4 Nov 2026): Partial.** Scope, counts, all devices, saving and restart, Compare
  (no baseline, then after a listening-only check), Report with timestamp on/off, and all 4
  Verify cases pass. Migration not applicable (nothing saved under old statuses). Report with
  Wi-Fi off hung, then timestamped once Wi-Fi returned (B9). Minor wording logged (B8).

- **Setup:** laptop on "Example-Home"; RoomCheck restarted after `uv sync` and
  `npm --prefix web run build`. Run a check with **"Yes"**.
- **Scope and counts:** R-WPS ("Router advertises WPS") should be on Results under
  **This network**, not on Nearby. "Findings by priority" should count every finding, with
  "· on Nearby" or "N on Nearby" where they live elsewhere, and **All findings** selected (tick
  and "Showing"). Nearby's subtitle: "Wi-Fi and Bluetooth signals detected around you…".
- **All devices:** open **View all discovered devices**: every device RoomCheck heard,
  including ones with no findings (e.g. phones), with type, identification confidence and maker.
- **Saving without a move-in scan:** with no baseline saved, set a Handover task to **Asked**,
  tick **Host confirmed**, and type a note. Expect "Saving…" then "Saved on this laptop". Close
  and restart RoomCheck, run a check: the status, evidence and note are still there.
- **Migration:** if you saved tasks as "Done" or "Confirmed" before this update, they now show
  **Resolved**, or **Asked** with the **Host confirmed** evidence.
- **Compare:** with no baseline, one card: "Save a starting point to compare future checks" with
  the latest check's date, "Network: Example-Home" and the mode. Save it, run a **listening-only**
  check, then open Compare: the top says "These checks ran differently, so some differences may
  come from that.", items read "Not seen this time", and no port is shown as "No longer open"
  just because it wasn't checked.
- **Report:** with no API key, only **Trusted timestamp** is offered. Make one report with it on
  (expect "Trusted timestamp: Added") and one with it off ("Not requested", and "This report
  has no trusted timestamp."). Turn Wi-Fi off and make one with it on: "Unavailable" with the
  reason, and no timestamp promised.
- **Verify:** check the timestamped report and its .tsr ("Verified"); a copy with one byte
  changed ("Files don't match"); the untimestamped PDF alone ("Not timestamped"); and a .txt
  renamed to .pdf ("Couldn't verify: This file isn't a PDF…").
- **Since then:** B8 (report without a timestamp) rechecked live on 6 Nov 2026; B9 (Wi-Fi off)
  still awaits a recheck. See [recheck-results.md](recheck-results.md), items 10-11.

## 11. Final UI polish: things only the real laptop can show

- **Result (4 Nov 2026): Partial.** Drag and drop (aqua, Received x3, Verified; untimestamped
  PDF alone; photo rejected), bundle (same names and bytes, verified from the ZIP), last room
  label, report progress text, host message (untick, copy: only ticked task, numbered from 1),
  Help keeps work: pass. Wi-Fi-off error and Try again never appeared (B9). Delete all data left
  the old label on the open Report page (B12). AI host draft ignores task choice (B11). "Possibly
  the same device" not reproduced: the rejoined iPhone showed as New. B10 found mid-test.

- **Setup:** laptop on "Example-Home"; RoomCheck restarted after `uv sync` and
  `npm --prefix web run build`. Run a check with **"Yes"**.
- **Verify, drag and drop:** in File Explorer, select a report's PDF, .tsr and .sha256 together
  and drag them onto **Choose report files**. The area turns aqua while you drag; the checklist
  says "Received" for all three; **Check the report** says "Verified". Then **Verify another
  report**, and drop only the PDF of an untimestamped report: the .tsr row says "Not added.
  Optional…", and the result is "Not timestamped". Drop a photo: "…isn't a report file."
- **Report bundle:** make a report with a room label, then **Download report bundle**. Open the
  ZIP in Explorer: the PDF, the .tsr and the .sha256, with the same names as the separate
  downloads. Verify the files from the ZIP on the Verify page ("Verified").
- **Last room label:** close and restart RoomCheck, run a check, open Report: the room label
  is filled in, with "Filled in from your last report". Help → **Delete all saved RoomCheck
  data**, then Report again: the label is empty.
- **Report progress:** with Trusted timestamp on, **Create report** shows "Creating the report
  and getting its trusted timestamp…" until it's done. With Wi-Fi off, the error appears with
  **Try again**, and your label and choices are unchanged; turn Wi-Fi on and Try again works.
- **Possibly the same device:** save a move-in scan, then turn your phone's Wi-Fi off and on
  (iPhone: a private address per network can change it after "Forget This Network"), rejoin,
  and run another check. If Compare lists the phone under **Possibly the same device**, answer
  **Different devices**: it moves to New and Not seen this time. Restart RoomCheck: the
  answer is kept. Answer **Same device**: it's counted as one device again. No finding or
  priority changes either way.
- **Host message:** on Handover, open **Draft message to host**, untick one task, then **Copy
  message** and paste into Notepad: only the ticked tasks' questions, numbered from 1.
- **Help keeps work:** on Report, type a room label and tick Handover notes; open Help from the
  header, then **Back to Report**: both are as you left them.

## Done

- 2 Nov, nearby check (Layer 4): WLAN API worked, no Location/radio/Bluetooth errors;
  R-WPS fired on the TP-Link mesh; no lookalike rule fired on the 8 "Example-Home" mesh nodes.
- 3 Nov, Layer 5 end-to-end report (`report --consent --room-label "Home test"`): R-CAM High
  (the Tapo TC70 at .58), R-WPS Medium, R-CVE Info; standard explanations (AI fell back, see
  test 6); standard host message with 2 questions; PDF, .sha256 and a FreeTSA .tsr saved.
  `verify` said OK (timestamp 03 Nov 2026, 05:25:12 UTC, pinned FreeTSA). A copy with one
  byte flipped said NOT VERIFIED (hash and timestamp mismatch).
