"""Build GRP MAP:TMA ALTITUDES from TopSky, altitudes as MVA-style (1500 -> 1.5).

FOLDER:OTHER. Idempotent replace of MAP:TMA ALTITUDES:T.
"""

from __future__ import annotations

import re
from pathlib import Path

ESAA = Path(__file__).resolve().parents[1]
MAPS = ESAA / "Plugins" / "GRpluginMaps.txt"
TOPSKY = ESAA / "OTHER" / "TopSkyMaps.txt"

MAP_NAME = "MAP:TMA ALTITUDES:T"


def convert_feet_token(tok: str) -> str:
    tok = tok.strip()
    if not tok:
        return tok
    # FL65 -> 65 (same numeric style as MVA flight levels)
    m = re.fullmatch(r"FL(\d+)", tok, re.I)
    if m:
        return m.group(1)
    m = re.fullmatch(r"(\d+)", tok)
    if m:
        return f"{int(m.group(1)) / 1000:.1f}"
    return tok


def convert_label(lab: str) -> str:
    """1500 -> 1.5; 4500 / 1500 -> 4.5 / 1.5; FL65 / 1700 -> FL65 / 1.7."""
    return " / ".join(convert_feet_token(p) for p in lab.split(" / "))


def pad_coord(tok: str) -> str:
    """Normalize N/E/W/S ddd.mm.ss.sss (TopSky sometimes omits leading zeros)."""
    m = re.fullmatch(r"([NSEW])(\d+)\.(\d+)\.(\d+)\.(\d+)", tok)
    if not m:
        return tok
    hemi, deg, mn, sec, frc = m.groups()
    return f"{hemi}{int(deg):03d}.{int(mn):02d}.{int(sec):02d}.{int(frc):03d}"


def parse_topsky_tma_altitudes(text: str) -> list[str]:
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("MAP:TMA ALTITUDES"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("MAP:"))
    out: list[str] = []
    for l in lines[start + 1 : end]:
        s = l.strip()
        if not s:
            continue
        if s.startswith("FOLDER:") or s.startswith("COLOR:"):
            continue
        if s.startswith("//"):
            out.append(s)
            continue
        if s.startswith("TEXT:"):
            p = s.split(":")
            # TEXT:lat:lon:label...  (label may contain :)
            if len(p) >= 4:
                lat, lon = pad_coord(p[1]), pad_coord(p[2])
                lab = convert_label(":".join(p[3:]))
                out.append(f"TEXT:{lat}:{lon}:{lab}")
    return out


def remove_map(maps_text: str, map_name: str) -> str:
    if map_name not in maps_text:
        return maps_text
    start = maps_text.find(map_name)
    probe = start
    block_start = start
    while True:
        prev_nl = maps_text.rfind("\n", 0, probe)
        if prev_nl < 0:
            break
        prev_line = maps_text[prev_nl + 1 : probe]
        if prev_line.strip() == "" or prev_line.lstrip().startswith("//"):
            block_start = prev_nl + 1
            probe = prev_nl
            continue
        break
    rest = maps_text.find("\nMAP:", start + 1)
    if rest < 0:
        rest = len(maps_text)
    return maps_text[:block_start] + maps_text[rest:].lstrip("\n")


def build_map(body: list[str]) -> str:
    rows = [
        "// TMA altitudes from TopSky; feet -> MVA-style (1500 -> 1.5)",
        MAP_NAME,
        "AIRPORT:ESAA",
        "FOLDER:OTHER",
        "ASRDATA:RTC",
        "COLOR:WHITE",
        "ACTIVE:0",
        "FONTSIZE:=:15",
    ]
    rows.extend(body)
    return "\n".join(rows) + "\n\n"


def main() -> None:
    topsky = TOPSKY.read_bytes().decode("cp1252")
    body = parse_topsky_tma_altitudes(topsky)
    maps = MAPS.read_bytes().decode("cp1252")
    maps = remove_map(maps, MAP_NAME)

    block = build_map(body)
    anchor = maps.find("MAP:AIRPORTS:T")
    if anchor < 0:
        anchor = maps.find("MAP:AMA/MVA:T")
        if anchor >= 0:
            nxt = maps.find("\nMAP:", anchor + 1)
            anchor = nxt + 1 if nxt >= 0 else len(maps)
        else:
            raise SystemExit("no insert anchor found")
    maps = maps[:anchor] + block + maps[anchor:]

    MAPS.write_bytes(maps.encode("cp1252"))
    n_text = sum(1 for l in body if l.startswith("TEXT:"))
    print(f"TMA ALTITUDES: {n_text} texts")
    print(f"Updated {MAPS}")


if __name__ == "__main__":
    main()
