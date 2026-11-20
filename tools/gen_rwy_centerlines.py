"""Generate GRP RWY CENTERLINE maps from AppPath data.

Civil: 15 NM line, ticks at 2/4/6/8/10 NM.
MIL (e.g. ESPA): 15 NM line, ticks every 1 NM to 6, then every 2 NM;
                 6 NM and 10 NM ticks are slightly longer.
"""

from __future__ import annotations

import math
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / "Plugins" / "GRpluginSettings.txt"
MAPS = Path(__file__).resolve().parents[1] / "Plugins" / "GRpluginMaps.txt"

SKIP_AIRPORTS = {"ESSA"}
MIL_AIRPORTS = {"ESPA", "ESIB"}  # dual-use / military AppPath airports

LINE_NM = 15.0
CIVIL_TICK_NMS = (2, 4, 6, 8, 10)
# 1..6 every NM, then every 2 NM out to the line end
MIL_TICK_NMS = (1, 2, 3, 4, 5, 6, 8, 10, 12, 14)
MIL_LONG_TICK_NMS = {6, 10}

TICK_HALF_NM = 0.2
TICK_HALF_NM_LONG = 0.3  # slightly longer for 6 / 10 NM
EARTH_NM = 3440.065

MARKER = "; --- AUTO RWY CENTERLINES START ---"
MARKER_END = "; --- AUTO RWY CENTERLINES END ---"


def dest(lat: float, lon: float, bearing_deg: float, dist_nm: float) -> tuple[float, float]:
    brng = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    ang = dist_nm / EARTH_NM
    lat2 = math.asin(
        math.sin(lat1) * math.cos(ang) + math.cos(lat1) * math.sin(ang) * math.cos(brng)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(ang) * math.cos(lat1),
        math.cos(ang) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def fmt_coord(lat: float, lon: float) -> str:
    def one(val: float, pos: str, neg: str) -> str:
        hemi = pos if val >= 0 else neg
        val = abs(val)
        deg = int(val)
        rem = (val - deg) * 60
        minutes = int(rem)
        sec = (rem - minutes) * 60
        whole = int(sec)
        frac = int(round((sec - whole) * 1000))
        if frac == 1000:
            frac = 0
            whole += 1
        if whole == 60:
            whole = 0
            minutes += 1
        if minutes == 60:
            minutes = 0
            deg += 1
        return f"{hemi}{deg:03d}.{minutes:02d}.{whole:02d}.{frac:03d}"

    return f"{one(lat, 'N', 'S')}:{one(lon, 'E', 'W')}"


def parse_apppaths(text: str) -> list[tuple[str, str, float, float, float]]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("AppPath="):
            continue
        parts = line.split("=", 1)[1].split(":")
        icao, rwy = parts[0], parts[1]
        lat, lon, hdg = float(parts[2]), float(parts[3]), float(parts[4])
        rows.append((icao, rwy, lat, lon, hdg))
    return rows


def tick_plan(icao: str) -> tuple[tuple[int, ...], set[int]]:
    if icao in MIL_AIRPORTS:
        return MIL_TICK_NMS, MIL_LONG_TICK_NMS
    return CIVIL_TICK_NMS, set()


def map_block(icao: str, rwy: str, lat: float, lon: float, inbound_true: float) -> str:
    ext = (inbound_true + 180.0) % 360.0
    end = dest(lat, lon, ext, LINE_NM)
    tick_nms, long_nms = tick_plan(icao)
    lines = [
        f"MAP:CENTERLINE {icao} {rwy}:AT",
        f"AIRPORT:{icao}",
        "FOLDER:RWY LINES",
        f"ACTIVE:RWY:ARR:{icao}{rwy}:DEP:*",
        "COLOR:LINE",
        "STYLE:SOLID:2",
        "ASRDATA:TWR",
        f"LINE:{fmt_coord(lat, lon)}:{fmt_coord(*end)}",
    ]
    for nm in tick_nms:
        half = TICK_HALF_NM_LONG if nm in long_nms else TICK_HALF_NM
        clat, clon = dest(lat, lon, ext, float(nm))
        p1 = dest(clat, clon, (inbound_true + 90.0) % 360.0, half)
        p2 = dest(clat, clon, (inbound_true - 90.0) % 360.0, half)
        lines.append(f"LINE:{fmt_coord(*p1)}:{fmt_coord(*p2)}")
    return "\n".join(lines) + "\n"


def build_maps(rows: list[tuple[str, str, float, float, float]]) -> str:
    blocks = []
    for icao, rwy, lat, lon, hdg in rows:
        if icao in SKIP_AIRPORTS:
            continue
        blocks.append(map_block(icao, rwy, lat, lon, hdg))
    return "\n".join(blocks)


def upsert_maps(maps_text: str, generated: str) -> str:
    block = f"{MARKER}\n{generated}{MARKER_END}\n"
    if MARKER in maps_text and MARKER_END in maps_text:
        pre, rest = maps_text.split(MARKER, 1)
        _, post = rest.split(MARKER_END, 1)
        return pre + block + post.lstrip("\n")

    anchor = "MAP:CENTERLINE 26:AT"
    idx = maps_text.find(anchor)
    if idx < 0:
        return maps_text.rstrip() + "\n\n" + block
    after = maps_text.find("\nMAP:", idx + 1)
    if after < 0:
        after = len(maps_text)
    return maps_text[:after].rstrip() + "\n\n\n" + block + "\n" + maps_text[after:].lstrip("\n")


def main() -> None:
    settings = SETTINGS.read_text(encoding="utf-8", errors="replace")
    rows = parse_apppaths(settings)
    generated = build_maps(rows)
    keep = [r for r in rows if r[0] not in SKIP_AIRPORTS]
    print(f"Generating {len(keep)} centerlines (skipped {sorted(SKIP_AIRPORTS)})")
    for icao, rwy, _, _, hdg in keep:
        kind = "MIL" if icao in MIL_AIRPORTS else "CIV"
        ticks, long_t = tick_plan(icao)
        print(f"  {icao} {rwy} [{kind}] hdg {hdg} ticks={ticks} long={sorted(long_t)}")

    maps = MAPS.read_text(encoding="utf-8", errors="replace")
    MAPS.write_text(upsert_maps(maps, generated), encoding="utf-8", newline="\n")
    print(f"Updated {MAPS}")


if __name__ == "__main__":
    main()
