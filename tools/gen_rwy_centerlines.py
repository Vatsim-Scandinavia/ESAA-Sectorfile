"""Generate GRP RWY CENTERLINE maps from AppPath + SCT runway data.

Civil: 15 NM line, ticks at 2/4/6/8/10 NM.
MIL: 15 NM line, ticks every 1 NM to 6, then every 2 NM;
     6 NM and 10 NM ticks are slightly longer.

Skips ESSA and ESGG (manual / excluded).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

ESAA = Path(__file__).resolve().parents[1]
SETTINGS = ESAA / "Plugins" / "GRpluginSettings.txt"
MAPS = ESAA / "Plugins" / "GRpluginMaps.txt"
# Sector SCT lives next to the EuroScope ESAA symlink (AppData), not the git checkout root.
EUROSCOPE_APPDATA = Path.home() / "AppData" / "Roaming" / "EuroScope"

SKIP_AIRPORTS = {"ESSA", "ESGG"}
LOGIN_PROFILES = ESAA / "Settings" / "LoginProfiles.txt"
MIL_AIRPORTS = {
    "ESPE",
    "ESNJ",
    "ESPA",
    "ESCM",
    "ESIB",
    "ESIA",
    "ESCF",
    "ESSL",
    "ESMV",
    "ESDF",
}

LINE_NM = 15.0
CIVIL_TICK_NMS = (2, 4, 6, 8, 10)
MIL_TICK_NMS = (1, 2, 3, 4, 5, 6, 8, 10, 12, 14)
MIL_LONG_TICK_NMS = {6, 10}

TICK_HALF_NM = 0.2
TICK_HALF_NM_LONG = 0.3
EARTH_NM = 3440.065

MARKER = "; --- AUTO RWY CENTERLINES START ---"
MARKER_END = "; --- AUTO RWY CENTERLINES END ---"

SCT_RWY_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+"
    r"(N\d{3}\.\d{2}\.\d{2}\.\d{3})\s+([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})\s+"
    r"(N\d{3}\.\d{2}\.\d{2}\.\d{3})\s+([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})\s+"
    r"(ES\w+)\s*$"
)


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


def parse_dms(token: str) -> float:
    hemi = token[0]
    deg_s, min_s, sec_s, frac_s = token[1:].split(".")
    val = int(deg_s) + int(min_s) / 60.0 + (int(sec_s) + int(frac_s) / 1000.0) / 3600.0
    if hemi in ("S", "W"):
        val = -val
    return val


def find_sct() -> Path:
    search_roots = [EUROSCOPE_APPDATA, ESAA, ESAA.parent]
    candidates: list[Path] = []
    for root in search_roots:
        if root.is_dir():
            candidates.extend(root.glob("ESAA-Sweden*.sct"))
    if not candidates:
        raise FileNotFoundError(f"No ESAA-Sweden*.sct under {search_roots}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def parse_apppaths(text: str) -> dict[tuple[str, str], tuple[float, float, float]]:
    """Return {(icao, rwy): (lat, lon, inbound_hdg)} preferring AppPath precision."""
    rows: dict[tuple[str, str], tuple[float, float, float]] = {}
    for line in text.splitlines():
        if not line.startswith("AppPath="):
            continue
        parts = line.split("=", 1)[1].split(":")
        icao, rwy = parts[0], parts[1]
        lat, lon, hdg = float(parts[2]), float(parts[3]), float(parts[4])
        rows[(icao, rwy)] = (lat, lon, hdg)
    return rows


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Initial true bearing from a → b (degrees)."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def parse_sct_runways(sct_text: str) -> dict[tuple[str, str], tuple[float, float, float]]:
    """Threshold + true inbound heading from [RUNWAY] for ES* airports.

    SCT stores magnetic headings; dest() draws geographic bearings, so use the
    true runway-axis bearing (this threshold → opposite threshold) instead.
    """
    m = re.search(r"\[RUNWAY\](.*?)(?=\n\[|\Z)", sct_text, re.S)
    if not m:
        return {}
    rows: dict[tuple[str, str], tuple[float, float, float]] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        mm = SCT_RWY_RE.match(line)
        if not mm:
            continue
        rwy1, rwy2, _hdg1, _hdg2, lat1, lon1, lat2, lon2, icao = mm.groups()
        a = (parse_dms(lat1), parse_dms(lon1))
        b = (parse_dms(lat2), parse_dms(lon2))
        # Inbound track for each end ≈ direction along the runway toward the other end
        rows[(icao, rwy1)] = (*a, bearing_deg(a, b))
        rows[(icao, rwy2)] = (*b, bearing_deg(b, a))
    return rows


def atc_airports() -> set[str]:
    """Airports with TWR/GND/APP/DEL login profiles (excl. FIR/sector CTR)."""
    text = LOGIN_PROFILES.read_text(encoding="utf-8", errors="replace")
    out: set[str] = set()
    for m in re.finditer(r"^PROFILE:(ES[A-Z]{2})_(.+)$", text, re.M):
        icao, rest = m.group(1), m.group(2)
        if icao in ("ESAA", "ESOS", "ESMM", "ESSR"):
            continue
        if any(x in rest for x in ("TWR", "GND", "APP", "DEL")):
            out.add(icao)
    return out


def merge_sources(
    apppath: dict[tuple[str, str], tuple[float, float, float]],
    sct: dict[tuple[str, str], tuple[float, float, float]],
    allow: set[str],
) -> list[tuple[str, str, float, float, float]]:
    """AppPath wins on overlap; only airports with ATC login profiles."""
    merged = dict(sct)
    merged.update(apppath)  # AppPath overrides SCT
    rows = []
    for (icao, rwy), (lat, lon, hdg) in merged.items():
        if icao in SKIP_AIRPORTS:
            continue
        if icao not in allow:
            continue
        if not icao.startswith("ES"):
            continue
        rows.append((icao, rwy, lat, lon, hdg))
    rows.sort(key=lambda r: (r[0], r[1]))
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
        "AIRPORT:ESAA",
        "FOLDER:RWY LINES",
        f"ACTIVE:RWY:ARR:{icao}{rwy}:DEP:*",
        "COLOR:LINE",
        "STYLE:SOLID:2",
        "ASRDATA:RTC",
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
    return "\n".join(map_block(*row) for row in rows)


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
    sct_path = find_sct()
    sct_text = sct_path.read_text(encoding="utf-8", errors="replace")

    allow = atc_airports()
    apppath = parse_apppaths(settings)
    sct = parse_sct_runways(sct_text)
    rows = merge_sources(apppath, sct, allow)

    mil_rows = [r for r in rows if r[0] in MIL_AIRPORTS]
    civ_rows = [r for r in rows if r[0] not in MIL_AIRPORTS]
    print(f"SCT: {sct_path.name}")
    print(f"ATC airports from LoginProfiles: {len(allow)}")
    print(f"Generating {len(rows)} centerlines "
          f"(MIL {len(mil_rows)}, CIV {len(civ_rows)}; skipped {sorted(SKIP_AIRPORTS)})")
    for icao, rwy, _, _, hdg in mil_rows:
        src = "AppPath" if (icao, rwy) in apppath else "SCT"
        ticks, long_t = tick_plan(icao)
        print(f"  {icao} {rwy:3} [MIL/{src}] hdg {hdg:6.2f} ticks={ticks} long={sorted(long_t)}")

    missing_mil = MIL_AIRPORTS - {r[0] for r in rows}
    if missing_mil:
        print(f"WARNING: no runways found for MIL airports: {sorted(missing_mil)}")

    generated = build_maps(rows)
    maps = MAPS.read_bytes().decode("cp1252")
    MAPS.write_bytes(upsert_maps(maps, generated).encode("cp1252"))
    print(f"Updated {MAPS}")


if __name__ == "__main__":
    main()
