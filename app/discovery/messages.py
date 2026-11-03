"""Plain-language failure messages. Each says what happened and what to do next."""

NPCAP_URL = "https://npcap.com/#download"
NMAP_URL = "https://nmap.org/download.html"

MESSAGES: dict[str, str] = {
    "no_network": "Connect to the room's Wi-Fi first, or run only the nearby check.",
    "npcap_missing": (
        "RoomCheck needs a free network driver called Npcap. "
        f"Install it from {NPCAP_URL}, then try again."
    ),
    "scanner_unavailable": (
        "The scanner couldn't start. Restart RoomCheck, or run it once as administrator."
    ),
    "permission": "The scanner couldn't start. Restart RoomCheck, or run it once as administrator.",
    "subnet_too_large": "This is a large shared network. We'll only listen, not sweep.",
    "client_isolation": (
        "This network hides devices from each other, so this check can't see them. "
        "Try the nearby Wi-Fi and Bluetooth check instead."
    ),
    "passive_mode": "Skipped because you chose a listen-only check.",
    "nmap_missing": (
        "Not run: RoomCheck needs a free tool called Nmap to check which services devices "
        f"offer. Install it from {NMAP_URL}, then try again."
    ),
    "nmap_failed": (
        "The service check couldn't run. Restart RoomCheck, or run it once as administrator."
    ),
    "no_swept_hosts": "Not run: the network sweep found no devices to check.",
    "partly_identified": (
        "Partly identified: some devices didn't answer in time or sent replies we couldn't "
        "read. They were judged on what we could see."
    ),
    "not_wifi": (
        "Not run: you're not connected over Wi-Fi, so there's no Wi-Fi encryption to check."
    ),
    "wifi_unreadable": (
        "Couldn't read your Wi-Fi connection details. This check may not support this Windows "
        "language yet."
    ),
    "dns_unclear": (
        "The network's address lookups didn't answer clearly, so this check couldn't decide."
    ),
    "no_listener": "Not run: the network listener didn't run, so there was no traffic to check.",
    "no_dhcp_offer": "No device answered the address request, so this couldn't be checked.",
    "offline": "Skipped because you chose not to look anything up online.",
    "no_models": "No device shared a model name we could look up.",
    "nvd_unavailable": "Vulnerability lookup skipped for now.",
    # Layer 4: nearby Wi-Fi and Bluetooth (wording from PLAN.md, "Error handling")
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
        "Not run: RoomCheck doesn't know your Wi-Fi network's name. Connect to it, or type "
        "its name, then try again."
    ),
    "wps_unknown": (
        "Not run: WPS can only be read through the Windows Wi-Fi interface, which wasn't "
        "available this time."
    ),
    "nearby_wifi_failed": "Not run, because the list of nearby Wi-Fi networks couldn't be read.",
    "nearby_off": "Skipped because you chose not to run the nearby check.",
    "nearby_only": (
        "Not run: this was a nearby-only check, so devices on the network you joined weren't "
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
    "timeout": "This step took too long and was stopped. The other steps still ran.",
    "internal": "Something went wrong in this step. The other steps still ran.",
}

RANDOM_MAC_NOTE = "Private address, probably a phone or laptop."


def message_for(code: str) -> str:
    return MESSAGES.get(code, MESSAGES["internal"])
