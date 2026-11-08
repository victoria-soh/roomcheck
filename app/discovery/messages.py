"""Plain-language failure messages. Each says what happened and what to do next."""

NPCAP_URL = "https://npcap.com/#download"
NMAP_URL = "https://nmap.org/download.html"

MESSAGES: dict[str, str] = {
    "no_network": "Connect to the room's Wi-Fi first, or run only the nearby check.",
    "npcap_missing": (
        "RoomCheck needs a free network driver called Npcap. "
        f"Install it from {NPCAP_URL}, then try again."
    ),
    # The worker never started: Npcap or permissions, so the admin advice applies.
    "scanner_not_started": (
        "The scanner couldn't start. Restart RoomCheck, or run it once as administrator."
    ),
    # The worker was running but stopped answering mid-step (e.g. it was restarted).
    "scanner_unavailable": (
        "The scanner stopped during this step. RoomCheck restarts it for the next check, "
        "so run the check again."
    ),
    "permission": "The scanner couldn't start. Restart RoomCheck, or run it once as administrator.",
    "subnet_too_large": "This is a large shared network. We'll only listen, not sweep.",
    "client_isolation": (
        "This network hides devices from each other, so this check can't see them. "
        "Try the nearby Wi-Fi and Bluetooth check instead."
    ),
    "passive_mode": "Not checked, because you chose a listen-only check.",
    "nmap_missing": (
        "Not checked: RoomCheck needs a free tool called Nmap to check which services devices "
        f"offer. Install it from {NMAP_URL}, then try again."
    ),
    "nmap_failed": (
        "The service check couldn't run. Restart RoomCheck, or run it once as administrator."
    ),
    "no_swept_hosts": "Not checked: the network sweep found no devices to check.",
    "partly_identified": (
        "Partly identified: some devices didn't answer in time or sent replies we couldn't "
        "read. They were judged on what we could see."
    ),
    "not_wifi": (
        "Not checked: you're not connected over Wi-Fi, so there's no Wi-Fi encryption to check."
    ),
    "wifi_unreadable": (
        "Couldn't read your Wi-Fi connection details. This check may not support this Windows "
        "language yet."
    ),
    "dns_unclear": (
        "The network's address lookups didn't answer clearly, so this check couldn't decide."
    ),
    "no_listener": (
        "Not checked: the network listener wasn't running, so there was no traffic to check."
    ),
    "no_dhcp_offer": "Not checked: no device answered the address request.",
    "offline": "Not checked, because you chose not to look anything up online.",
    "no_models": "No device shared a model name we could look up.",
    "nvd_unavailable": "Not checked: the vulnerability database didn't answer this time.",
    # Layer 4: nearby Wi-Fi and Bluetooth (wording from docs/original-plan.md, "Error handling")
    "location_off": (
        "Windows needs Location turned on to list nearby Wi-Fi. Open Settings, then "
        "Privacy & security, then Location."
    ),
    "no_wifi": "Turn on Wi-Fi to check nearby networks.",
    "bluetooth_off": "Turn on Bluetooth to check for nearby trackers.",
    "signal_unstable": "The signal is jumping around. Move more slowly and hold the laptop still.",
    "nearby_unreadable": (
        "Couldn't read the list of nearby Wi-Fi networks. This check may not support this "
        "Windows language yet."
    ),
    "no_room_network": (
        "Not checked: RoomCheck doesn't know your Wi-Fi network's name. Connect to it, or type "
        "its name, then try again."
    ),
    "wps_unknown": (
        "Not checked: WPS can only be read through the Windows Wi-Fi interface, which wasn't "
        "available this time."
    ),
    "nearby_wifi_failed": (
        "Not checked, because the list of nearby Wi-Fi networks couldn't be read."
    ),
    "nearby_off": "Not checked, because you chose not to run the nearby check.",
    "nearby_only": (
        "Not checked: this was a nearby-only check, so devices on the network you joined weren't "
        "checked."
    ),
    "locator_starting": "Getting a steady reading. Hold the laptop the same way throughout.",
    "locator_lost": (
        "Can't hear it right now. Keep moving slowly, or go back to where it was stronger."
    ),
    "locator_wifi_slow": (
        "Wi-Fi readings update every few seconds, so move slowly and pause at each spot."
    ),
    "locator_wifi_unavailable": (
        "The Wi-Fi locator needs the Windows Wi-Fi interface, which isn't available right now. "
        "Turn on Wi-Fi and Location, then try again."
    ),
    "locator_unknown_item": (
        "That item isn't in the latest nearby check. Run the nearby check again, then pick it "
        "from the list."
    ),
    # Layer 5: report
    "report_no_scan": "Run a check first, then make the report from its results.",
    "pdf_unavailable": (
        'Couldn\'t make the PDF on this computer. Run "uv run playwright install chromium" '
        "once, then try again. The check results are still available."
    ),
    "file_too_large": "That file is too large to be a RoomCheck report.",
    # Demo mode (python -m app --demo): nothing is sent or scanned
    "demo_no_timestamp": "Demo mode: nothing is sent, so the report has no trusted timestamp.",
    "demo_unavailable": "Demo mode doesn't listen to the radios. Run RoomCheck without --demo.",
    # Scan jobs (the dashboard's scanning screen)
    "scan_running": "A check is already running. Wait for it to finish, then try again.",
    "scan_unknown": "That check isn't available any more. Start a new check.",
    # Layer 6: the move-in baseline (wording from docs/original-plan.md, "Error handling")
    "baseline_unreadable": (
        "This saved scan belongs to another account or install. Start a new move-in scan."
    ),
    "baseline_none": "There's no move-in scan saved yet.",
    "baseline_needs_check": "Run a check first, then save it as your move-in scan.",
    "task_unknown": "That task isn't in the latest check any more.",
    "name_invalid": "Use up to 40 characters of plain text, without < or >.",
    "note_invalid": "Use up to 200 characters of plain text, without < or >.",
    "handover_not_saved": (
        "RoomCheck couldn't write to its folder in your user profile. Check there's free space, "
        "then try again."
    ),
    "handover_unreadable": (
        "The data saved on this laptop belongs to another Windows account or install, so new "
        "changes can't be added to it. Start a new move-in scan on the Compare page to save again."
    ),
    "recheck_unavailable": (
        "This task can be rechecked once it's marked Done or Host confirmed, and only where "
        "RoomCheck can see the fix."
    ),
    "scan_stopping": "The last check is still stopping. Try again in a few seconds.",
    "scan_preparing": "Finishing the previous check…",
    "scan_cancelled": "You cancelled this check. Nothing from it was kept.",
    "scan_failed": (
        "The check stopped because of an unexpected problem. Restart RoomCheck, then try again."
    ),
    "timeout": "This step took too long and was stopped. The other steps still ran.",
    "internal": "Something went wrong in this step. The other steps still ran.",
}

RANDOM_MAC_NOTE = "Private address, probably a phone or laptop."


def message_for(code: str) -> str:
    return MESSAGES.get(code, MESSAGES["internal"])
