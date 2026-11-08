# Bugs from live tests

Found during the live test session of 4 Nov 2026 (feature freeze: fixes only). Not fixed
during the session; all fixed on 5 Nov 2026 (see each Status line). Rechecked live on 6 Nov 2026
([recheck-results.md](recheck-results.md)): B1-B8 and B11 passed; B9, B10 and B12 still await a
live recheck. Device and network names are described, never recorded.

## B1. Landlord message calls an unconfirmed device "the camera device" and says "we" (test 6)

- **Status (5 Nov 2026): Fixed.** **Passed live recheck 6 Nov (see recheck-results.md).** Prompt, validator (`camera_overclaim`, `not_first_person`) and a template guard (`hedge_camera`) keep an unconfirmed camera "the device that may be a camera"; tests in `tests/unit/test_live_fixes.py` (B1).

- **Steps:** laptop on the home Wi-Fi with the Tapo camera on it and an API key in `.env`;
  `uv run python -m app.cli report --consent --room-label "Home test"`.
- **Expected:** the AI-drafted landlord message refers to "the device that may be a camera"
  (R-CAM is Likely, not confirmed) and is written in the first person ("I"), since the user is
  the sender.
- **Actual:** "we found a device on the network that may be a camera… Could you confirm what
  **the camera device** is…". The second sentence states it's a camera, and "we" is wrong for
  a single sender.
- **Fix to make:** prompt asks for first person and "the device that may be a camera"; add a
  validator rule (`app/explain/validator.py`) rejecting "the camera" / "the camera device" when
  the finding isn't confirmed; guard the standard (non-AI) template the same way. Tests for both.

## B2. PDF Limitations uses old wording, not the shared vocabulary (test 6)

- **Status (5 Nov 2026): Fixed.** **Passed live recheck 6 Nov (see recheck-results.md).** Report Limitations and the all-devices list use `CLUES_NOT_PROOF` ("unconfirmed: clues, not proof"); "from limited evidence" is now an old phrase and the vocabulary test covers both (`test_c1_followup.py`).

- **Steps:** as B1; open the PDF, Limitations section.
- **Expected:** the shared vocabulary: "…are unconfirmed: clues, not proof", the same as the CLI's
  "What this scan can't see".
- **Actual:** "Device types, lookalike networks and tracker formats are hints from limited
  evidence." (`app/report/render.py:53`).
- **Fix to make:** use the shared vocabulary there, and extend the vocabulary test to cover the
  report's Limitations and "What was checked" text. The dashboard's **View all discovered
  devices** has the same old phrasing: "Types are clues from limited evidence, not proof." (test 10).

## B3. "What was checked" describes UPnP as opening ports (test 6)

- **Status (5 Nov 2026): Fixed.** **Passed live recheck 6 Nov (see recheck-results.md).** Now "Checking whether the router advertises UPnP controls"; five other labels reworded the same way (DNS, WPS, lookalike, ONVIF, SSDP); tested in `test_c1_followup.py`.

- **Steps:** as B1; CLI "Checks:" list and the PDF's "What was checked".
- **Expected:** "Checking whether the router advertises UPnP controls".
- **Actual:** "Checking whether the router lets devices open internet ports"
  (`app/checks/runner.py:35`). It describes what UPnP could do, not what RoomCheck checks.

## B4. WPS next step repeats the explanation's PIN sentence (test 6)

- **Status (5 Nov 2026): Fixed.** **Passed live recheck 6 Nov (see recheck-results.md).** The WPS next step is only "Ask the host whether WPS can be switched off."; the PIN risk stays in why-it-matters (`test_live_fixes.py`, B4).

- **Steps:** as B1; read the R-WPS finding and its explanation.
- **Expected:** the PIN-guessing point said once.
- **Actual:** "If PIN-based WPS is enabled, the PIN could be guessed by trying many codes"
  appears in the next step and again in the explanation / why-it-matters
  (`app/rules/rules.yaml:246-248`).
- **Fix to make:** keep it in one place; the next step says only what to ask.

## B5. Dashboard full check: the address sweep times out (test 7)

- **Status (5 Nov 2026): Fixed.** **Passed live recheck 6 Nov (see recheck-results.md).** Cause: the app gave up on the sweep at a fixed 50 s and threw away all it had heard, while the dashboard's long-lived scanner worker kept running abandoned sweeps into the next check (the CLI's worker is new each run). The sweep now ends by its own budget and returns what it heard, the app waits longer than that budget, a worker left with abandoned jobs is restarted before the next check, and the worker logs each job's time (`test_live_fixes.py`, B5).

- **Steps:** fresh `uv run python -m app`; open the dashboard; answer "Yes"; start the check on
  the home Wi-Fi (a /22 network).
- **Expected:** "Asking every address on this network to answer" completes, as it did twice the
  same day from the CLI (`discover --consent`, `report --consent`: 24 replies).
- **Actual:** the step failed with "This step took too long and was stopped. The other steps
  still ran." The "Listening for devices" step shows as failed. 10 devices found (CLI: 11);
  same findings (R-CAM, R-WPS, R-CVE).
- **How often:** at least 4 of the 9 full dashboard checks that day (not every run's coverage
  was read); it didn't happen in the 2 CLI runs.
  When it happens, Results honestly says "Partial check: 5 checked · 1 not checked".
- **Likely area:** the step time limit in the dashboard's job runner is shorter than the sweep
  needs on a /22, or the sweep runs slower there than from the CLI.

## B6. A check started right after another says "The scanner couldn't start" (test 7)

- **Status (5 Nov 2026): Fixed.** **Passed live recheck 6 Nov (see recheck-results.md).** A worker left busy or stopped is restarted before the next check, with "Finishing the previous check…"; the admin advice is now only for a worker that never started or a real permission error (`test_live_fixes.py`, B6).

- **Steps:** finish a full check in the dashboard; within about 2 minutes, start another full check.
- **Expected:** the second check's listening step runs normally (or waits for the scanner).
- **Actual:** "The scanner couldn't start. Restart RoomCheck, or run it once as administrator."
  It's misleading: RoomCheck had just run fine, and admin rights aren't the cause.

## B7. Cancel takes about 20 s, and a new check is refused meanwhile (test 7)

- **Status (5 Nov 2026): Fixed.** **Passed live recheck 6 Nov (see recheck-results.md).** Cancel answers at once; the check stops within about a second (every wait checks for a cancel) and the worker restarts in the background. The page says "Stopping…" until then, and a new check can start straight after (`test_live_fixes.py`, B7; `Scanning.test.tsx`).

- **Steps:** start a check; press **Cancel check** and confirm; straight away, start a
  "Not sure" check.
- **Expected:** the cancel finishes within a few seconds, so a new check can start.
- **Actual:** "Last check is still stopping. Try again in a few seconds." The server refused
  new checks (HTTP 409) for about 20 s after the cancel.

## B8. Untimestamped report still says "since it was timestamped" (test 10)

- **Status (5 Nov 2026): Fixed.** **Passed live recheck 6 Nov (see recheck-results.md).** A report without a timestamp now says "Without a timestamp, nothing shows when this report was made…" (`LiveFixes.test.tsx`).

- **Steps:** Report page, untick **Trusted timestamp**, **Create report**; read the result.
- **Expected:** text that fits a report with no timestamp.
- **Actual:** "This report has no trusted timestamp." is followed by "Verifying shows the report
  hasn't changed since it was timestamped. It doesn't prove the findings are correct."
- **Severity:** minor wording, but it's on the trust/tamper-evidence screen.

## B9. Report with Wi-Fi off hangs instead of saying "Unavailable" (tests 10 and 11)

- **Status (5 Nov 2026): Fixed.** **Awaiting live recheck.** The timestamp request has one 10 s deadline (including the name lookup) and fails at once with no network, with the reason shown; the PDF browser has time limits; the result offers Try again; each report logs its stage times. The 84 s before rendering couldn't be traced from the logs, so it needs a live recheck (`test_live_fixes.py`, B9; `LiveFixes.test.tsx`).

- **Steps:** run a check; on Report, type a room label, tick Handover notes, leave **Trusted
  timestamp** on; turn the laptop's Wi-Fi off; press **Create report**; turn Wi-Fi on after
  about a minute.
- **Expected:** within about 10 s (`TSA_TIMEOUT_SECONDS`), the report is made with "Trusted
  timestamp: Unavailable" and the reason, and no timestamp promised (test 10). Or, in test 11's
  wording, the error appears with **Try again** and the label and choices are kept.
- **Actual:** "Creating the report and getting its trusted timestamp…" stayed up for 84 s while
  Wi-Fi was off. The request only finished after Wi-Fi came back, as "Trusted timestamp: Added"
  (signed after reconnecting). No "Unavailable", no error and no **Try again**. The label and
  choices were kept.
- **Clue:** the PDF's file name time is the moment Wi-Fi returned, so the wait is before the PDF
  is rendered, not in the 10 s timestamp call.

## B10. After the laptop rejoins Wi-Fi with a new address, RoomCheck says it isn't connected (test 11)

- **Status (5 Nov 2026): Fixed.** **Awaiting live recheck.** scapy's interfaces and routes are re-read on every network read (each check, each `/api/setup`, each worker job), never cached (`test_live_fixes.py`, B10).

- **Steps:** start `uv run python -m app` and run a check (fine). Let the laptop drop and rejoin
  the same Wi-Fi so it gets a different address (it happened by itself mid-session, at lower signal).
  Run another check without restarting RoomCheck.
- **Expected:** the check runs on the network the laptop is now on.
- **Actual:** "Connect to the room's Wi-Fi first, or run only the nearby check." 0 devices,
  every network step skipped. `GET /api/setup` says `"network": {"kind": "none"}`, while
  `connected_network()` in a fresh Python process returns `kind: wifi` at the same moment.
  Happened on 2 checks in a row; a restart fixes it.
- **Likely area:** network info cached in the server process (for example a route or interface
  table read once at start) and not refreshed when the address changes.

## B11. Dashboard's AI host message ignores which tasks are offered and ticked (test 11)

- **Status (5 Nov 2026): Fixed.** **Passed live recheck 6 Nov (see recheck-results.md).** The message covers exactly the open, ticked tasks (never Mine, Resolved or Host-confirmed ones); an AI draft is used only if written for exactly those findings and it mentions nothing else, in the first person, else the numbered template (`test_live_fixes.py`, B11).

- **Steps:** with an API key set, run a full check; on Results answer **Mine** on the camera
  card (so only the WPS task is open); Handover → **Draft message to host**.
- **Expected:** a message about the offered, ticked tasks only, written as the sender ("I"),
  numbered like the standard draft.
- **Actual:** the first draft (AI) asked about the camera although its task wasn't offered:
  "It found a device on the network that may be a camera… Could you confirm what this device
  is…". With both tasks ticked the AI draft says "we found…", calls the host's router "our Wi-Fi
  router", isn't numbered, and adds a firmware question from no task. After unticking one task,
  the message switches to the standard numbered draft, which is correct.
- **Related:** B1 (same wording problems in the CLI report's landlord message).

## B12. After "Delete all saved RoomCheck data", Report still shows the old room label (test 11)

- **Status (5 Nov 2026): Fixed.** **Awaiting live recheck.** Deleting all data clears and re-fetches the report defaults, so an open Report page drops the old label and its hint (`LiveFixes.test.tsx`).

- **Steps:** make a report with a room label; run a check; open Report (label filled in, "Filled
  in from your last report"); Help → **Delete all saved RoomCheck data** → **Yes, delete all of
  it** → **Back to Report**.
- **Expected:** the label is empty and the "Filled in from your last report" hint is gone.
- **Actual:** the old label and the hint are still shown. The server has cleared it
  (`GET /api/report/defaults` → `{"room_label": null}`), so a page reload would be empty. The
  page keeps its own copy (the "Help keeps work" behaviour) and isn't told the data was deleted.
  Making a report from there would write the "deleted" label back.
