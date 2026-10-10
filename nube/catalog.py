"""Finds save files on the console and classifies them as category / system / game.

classify() works from the path alone, so files listed from Drive can be grouped the same way
even when the local copy no longer exists.
"""
import fnmatch
import os
import re

CARDS = (("/mnt/sdcard", ""), ("/mnt/mmc", " (SD1)"))

RETROARCH = "RetroArch"
RA_STATES = "RetroArch (estados)"
STATE_SUFFIX = re.compile(r"\.state(\d+|\.auto)?$")
STANDALONE = "Emuladores independientes"
PORTS = "Ports"

# Ports: (display name, folder under Roms/PORTS, file pattern, one restore unit per file?)
PORT_SAVES = [
    ("GTA III", "gta3/userfiles", "GTA3sf*.b", True),
    ("GTA Vice City", "gtavc/userfiles", "GTAVCsf*.b", True),
    ("Zelda Ocarina of Time (SoH)", "soh/Save", "*.sav", False),
]

FLYCAST_FILES = ("vmu_save_*.bin", "dc_nvmem.bin")


def _system_and_game(rel):
    """saves_RA/Roms/GBA/Foo.srm -> ('GBA', 'Foo'); 2048/2048.srm -> ('2048', '2048')."""
    parts = rel.split("/")
    if parts[0] == "Roms" and len(parts) > 2:
        system = parts[1]
    elif len(parts) > 1:
        system = parts[0]
    else:
        system = "Otros"
    return system, os.path.splitext(parts[-1])[0]


def _slot_name(filename):
    digits = "".join(c for c in os.path.splitext(filename)[0][-2:] if c.isdigit())
    if digits == "9":
        return "Autoguardado (slot 9)"
    return f"Partida slot {digits}" if digits else filename


def classify(path):
    """Returns (category, system, game) for a save path, or None if it is not a save we handle."""
    for card, tag in CARDS:
        base = f"{card}/saves_RA/"
        if path.startswith(base):
            system, game = _system_and_game(path[len(base):])
            return RETROARCH, system + tag, game

        base = f"{card}/states_RA/"
        if path.startswith(base) and STATE_SUFFIX.search(path):
            # Foo.state / Foo.state1 / Foo.state.auto -> one game "Foo" with all its states
            system, _ = _system_and_game(path[len(base):])
            return RA_STATES, system + tag, STATE_SUFFIX.sub("", os.path.basename(path))

        base = f"{card}/save/"
        if path.startswith(base) and "/java/" not in path:
            system, game = _system_and_game(path[len(base):])
            return STANDALONE, f"{system} (independiente){tag}", game

        base = f"{card}/save_nds/backup/"
        if path.startswith(base) and path.lower().endswith(".dsv"):
            return STANDALONE, f"NDS (DraStic){tag}", os.path.splitext(os.path.basename(path))[0]

        base = f"{card}/save_flycast/.local/share/flycast/"
        if path.startswith(base) and any(fnmatch.fnmatch(os.path.basename(path), p) for p in FLYCAST_FILES):
            return STANDALONE, f"Dreamcast (Flycast){tag}", "Memorias VMU y NVRAM"

        for name, folder, pattern, per_file in PORT_SAVES:
            base = f"{card}/Roms/PORTS/{folder}/"
            fname = os.path.basename(path)
            if path.startswith(base) and "/" not in path[len(base):] and fnmatch.fnmatch(fname, pattern):
                return PORTS, name + tag, _slot_name(fname) if per_file else "Todas las partidas"
    return None


def _walk(root):
    for dirpath, _, files in os.walk(root):
        for f in files:
            yield os.path.join(dirpath, f)


def scan():
    """All save files currently on the console: list of (path, (category, system, game))."""
    roots = []
    for card, _ in CARDS:
        roots += [f"{card}/saves_RA", f"{card}/states_RA", f"{card}/save", f"{card}/save_nds/backup",
                  f"{card}/save_flycast/.local/share/flycast"]
        roots += [f"{card}/Roms/PORTS/{folder}" for _, folder, _, _ in PORT_SAVES]
    found = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        it = _walk(root) if "/PORTS/" not in root else (os.path.join(root, f) for f in os.listdir(root))
        for path in it:
            if os.path.isfile(path) and path not in found:
                info = classify(path)
                if info:
                    found[path] = info
    return sorted(found.items(), key=lambda kv: (kv[1], kv[0]))


def drive_folder(info):
    """Folder path on Drive for a save: ['RetroArch', 'GBA'], ['Ports', 'GTA III'], ..."""
    category, system, _ = info
    return [category, system]
