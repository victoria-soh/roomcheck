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
    "timeout": "This step took too long and was stopped. The other steps still ran.",
    "internal": "Something went wrong in this step. The other steps still ran.",
}

RANDOM_MAC_NOTE = "Private address, probably a phone or laptop."


def message_for(code: str) -> str:
    return MESSAGES.get(code, MESSAGES["internal"])
