"""Add TopSky RNP AR approach maps to GRP (FOLDER:RNP APP).

ESNZ only (ESSA dedicated; ESGG/ESMS use TopSky ASRs).
RWYdist points become //DISTANCE LINE ticks like ESSA RNP APP.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

ESAA = Path(__file__).resolve().parents[1]
MAPS = ESAA / "Plugins" / "GRpluginMaps.txt"
TOPSKY = ESAA / "OTHER" / "TopSkyMaps.txt"
EUROSCOPE = Path.home() / "AppData" / "Roaming" / "EuroScope"

SKIP_PREFIXES = ("ESSA", "ESGG", "ESMS")
BLOCK_START = "// RNP AR from TopSky (ESNZ only; ESSA/ESGG/ESMS via TopSky or dedicated maps)"
BLOCK_END_ANCHOR = "//----------------------------------------------------------------------------ESSA TWR TMA"

TICK_HALF_NM = 0.2
EARTH_NM = 3440.065

COORD_RE = re.compile(
    r"(N\d{3}\.\d{2}\.\d{2}\.\d{3})\s+([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})"
)
RWYDIST_RE = re.compile(
    r"^SYMBOL:RWYdist:(N\d{3}\.\d{2}\.\d{2}\.\d{3}):([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})\s*$"
)
SCTDATA_RE = re.compile(r"^SCTDATA:STAR\\(.+)$")


def find_sct() -> Path:
    cands = list(EUROSCOPE.glob("ESAA-Sweden*.sct")) + list(ESAA.glob("ESAA-Sweden*.sct"))
    if not cands:
        raise FileNotFoundError("No ESAA-Sweden*.sct found")
    return max(cands, key=lambda p: p.stat().st_mtime)


def parse_dms(tok: str) -> float:
    hemi = tok[0]
    deg, mn, sec, frc = tok[1:].split(".")
    val = int(deg) + int(mn) / 60.0 + (int(sec) + int(frc) / 1000.0) / 3600.0
    return -val if hemi in "SW" else val


def fmt_coord(lat: float, lon: float) -> str:
    def one(val: float, pos: str, neg: str) -> str:
        hemi = pos if val >= 0 else neg
        v = abs(val)
        deg = int(v)
        mn_f = (v - deg) * 60.0
        mn = int(mn_f)
        sec_f = (mn_f - mn) * 60.0
        sec = int(sec_f)
        frc = int(round((sec_f - sec) * 1000.0))
        if frc >= 1000:
            frc -= 1000
            sec += 1
        if sec >= 60:
            sec -= 60
            mn += 1
        if mn >= 60:
            mn -= 60
            deg += 1
        return f"{hemi}{deg:03d}.{mn:02d}.{sec:02d}.{frc:03d}"

    return f"{one(lat, 'N', 'S')}:{one(lon, 'E', 'W')}"


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


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def dist_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(h)))


def parse_star_segments(
    sct_text: str, star_name: str
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    m = re.search(r"\[STAR\](.*?)(?=\n\[|\Z)", sct_text, re.S)
    if not m:
        return []
    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for line in m.group(1).splitlines():
        if not line.startswith(star_name):
            continue
        pts = COORD_RE.findall(line)
        if len(pts) >= 2:
            a = (parse_dms(pts[0][0]), parse_dms(pts[0][1]))
            b = (parse_dms(pts[1][0]), parse_dms(pts[1][1]))
            segs.append((a, b))
    return segs


def _to_xy(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Local NM tangent-plane coords (east, north)."""
    return ((lon - lon0) * 60.0 * math.cos(math.radians(lat0)), (lat - lat0) * 60.0)


def _from_xy(x: float, y: float, lat0: float, lon0: float) -> tuple[float, float]:
    return (lat0 + y / 60.0, lon0 + x / (60.0 * math.cos(math.radians(lat0))))


def _circumcenter_xy(
    p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float]
) -> tuple[float, float] | None:
    """Circumcenter of triangle in 2D; None if nearly collinear."""
    (x1, y1), (x2, y2), (x3, y3) = p1, p2, p3
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        return None
    ux = (
        (x1 * x1 + y1 * y1) * (y2 - y3)
        + (x2 * x2 + y2 * y2) * (y3 - y1)
        + (x3 * x3 + y3 * y3) * (y1 - y2)
    ) / d
    uy = (
        (x1 * x1 + y1 * y1) * (x3 - x2)
        + (x2 * x2 + y2 * y2) * (x1 - x3)
        + (x3 * x3 + y3 * y3) * (x2 - x1)
    ) / d
    return (ux, uy)


def _local_chord_bearing(pts: list[tuple[float, float]], idx: int) -> float:
    """Fallback tangent from neighbouring distance points along the curve."""
    n = len(pts)
    if n == 1:
        return 0.0
    if idx == 0:
        return bearing(pts[0], pts[1])
    if idx == n - 1:
        return bearing(pts[n - 2], pts[n - 1])
    # central: average of in/out bearings
    b1 = bearing(pts[idx - 1], pts[idx])
    b2 = bearing(pts[idx], pts[idx + 1])
    # mean of angles
    s = math.sin(math.radians(b1)) + math.sin(math.radians(b2))
    c = math.cos(math.radians(b1)) + math.cos(math.radians(b2))
    return (math.degrees(math.atan2(s, c)) + 360.0) % 360.0


def _tick_bearings_curved(pts: list[tuple[float, float]]) -> list[float]:
    """Per-point tick bearing (⊥ track) for a curved RF-style path.

    Prefer circle through the distance points (tick = radial = ⊥ tangent).
    Fall back to chord tangents if points are nearly collinear.
    """
    n = len(pts)
    if n == 0:
        return []
    if n == 1:
        return [0.0]
    if n == 2:
        brg = bearing(pts[0], pts[1])
        return [(brg + 90.0) % 360.0, (brg + 90.0) % 360.0]

    lat0 = sum(p[0] for p in pts) / n
    lon0 = sum(p[1] for p in pts) / n
    xy = [_to_xy(p[0], p[1], lat0, lon0) for p in pts]

    # Use first/mid/last for a stable RF arc through the marks
    mid = n // 2
    center_xy = _circumcenter_xy(xy[0], xy[mid], xy[-1])
    if center_xy is None:
        return [(_local_chord_bearing(pts, i) + 90.0) % 360.0 for i in range(n)]

    cx, cy = center_xy
    center_ll = _from_xy(cx, cy, lat0, lon0)
    # Radial bearing center→point is perpendicular to the arc tangent
    return [bearing(center_ll, p) for p in pts]


def distance_tick_lines(
    pts: list[tuple[str, str]],
    segs: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[str]:
    if not pts:
        return []
    ll = [(parse_dms(lat_s), parse_dms(lon_s)) for lat_s, lon_s in pts]
    tick_brgs = _tick_bearings_curved(ll)

    # If only one mark, orient from nearest STAR segment
    if len(ll) == 1 and segs:
        best_d = 1e9
        best_brg = 0.0
        pt = ll[0]
        for a, b in segs:
            for cand in (a, b, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)):
                d = dist_nm(pt, cand)
                if d < best_d:
                    best_d = d
                    best_brg = bearing(a, b)
        tick_brgs = [(best_brg + 90.0) % 360.0]

    rows = ["//DISTANCE (perpendicular to curved path)"]
    for pt, perp in zip(ll, tick_brgs):
        p1 = dest(pt[0], pt[1], perp, TICK_HALF_NM)
        p2 = dest(pt[0], pt[1], (perp + 180.0) % 360.0, TICK_HALF_NM)
        rows.append(f"LINE:{fmt_coord(*p1)}:{fmt_coord(*p2)}")
    return rows


def parse_topsky_rnp_ar(text: str) -> list[tuple[str, list[str]]]:
    lines = text.splitlines()
    start = next(
        (i for i, l in enumerate(lines) if l.strip() in ("//RNP APP", "//RNP AR")),
        None,
    )
    if start is None:
        start = next(i for i, l in enumerate(lines) if l.strip() == "FOLDER:RNP AR")
        while start > 0 and not lines[start].startswith("MAP:"):
            start -= 1

    maps: list[tuple[str, list[str]]] = []
    i = start
    while i < len(lines):
        l = lines[i]
        if l.startswith("MAP:"):
            title = l[4:].strip()
            body: list[str] = []
            j = i + 1
            folder_ok = False
            while j < len(lines) and not lines[j].startswith("MAP:"):
                if lines[j].startswith("FOLDER:"):
                    folder_ok = lines[j].strip() == "FOLDER:RNP AR"
                body.append(lines[j])
                j += 1
            if folder_ok:
                maps.append((title, body))
            elif maps and not folder_ok:
                break
            i = j
            continue
        if maps and l.startswith("//") and "RNP" not in l.upper() and l.strip() != "":
            if not l.strip().startswith("//RNP"):
                break
        i += 1
    return maps


def convert_line(line: str) -> str | None:
    """Convert TopSky content line; RWYdist handled separately."""
    s = line.strip()
    if not s:
        return ""
    if s.startswith("FOLDER:") or s.startswith("COLOR:") or s.startswith("STYLE:"):
        return None
    if s.startswith("ZOOM:"):
        return None
    if RWYDIST_RE.match(s):
        return None  # handled as distance ticks
    if s.startswith("SCTDATA:"):
        return s
    if s.startswith("//"):
        return s

    m = re.match(r"^(SYMBOL(/[A-Z]+)?):([A-Za-z0-9_]+):(.*)$", s)
    if m:
        cmd, _flags, stype, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        if stype in ("REPFix", "RNPAPP"):
            return f"{cmd}:RNP:{rest}"
        return f"{cmd}:{stype}:{rest}"

    if s.startswith("TEXT") or s.startswith("LINE:"):
        return s
    return s


def build_grp_map(
    title: str,
    body: list[str],
    sct_text: str,
) -> str:
    star_names: list[str] = []
    rwy_dists: list[tuple[str, str]] = []
    for line in body:
        s = line.strip()
        m = SCTDATA_RE.match(s)
        if m:
            star_names.append(m.group(1))
        m = RWYDIST_RE.match(s)
        if m:
            rwy_dists.append((m.group(1), m.group(2)))

    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for name in star_names:
        segs.extend(parse_star_segments(sct_text, name))

    rows = [
        f"MAP:{title}:T",
        "AIRPORT:ESAA",
        "FOLDER:RNP APP",
        "ASRDATA:RTC",
        "COLOR:LINE",
        "STYLE:SOLID:2",
        "ACTIVE:0",
        "FONTSIZE:=:12",
    ]
    for line in body:
        conv = convert_line(line)
        if conv is None:
            continue
        rows.append(conv)
    rows.extend(distance_tick_lines(rwy_dists, segs))
    return "\n".join(rows) + "\n"


def build_block(
    maps: list[tuple[str, list[str]]], sct_text: str
) -> tuple[str, int]:
    parts = [BLOCK_START, ""]
    kept = 0
    for title, body in maps:
        if title.upper().startswith(SKIP_PREFIXES):
            continue
        parts.append(build_grp_map(title, body, sct_text))
        kept += 1
    parts.append("")
    return "\n".join(parts), kept


def upsert_block(maps_text: str, block: str) -> str:
    markers = (
        BLOCK_START,
        "// RNP AR from TopSky (excl. ESSA/ESGG)",
        "// RNP APP from SCT STAR (excl. ESSA/ESGG)",
    )
    changed = True
    while changed:
        changed = False
        for marker in markers:
            start = maps_text.find(marker)
            if start < 0:
                continue
            while start > 0 and maps_text[start - 1] == "\n":
                start -= 1
            end = maps_text.find(BLOCK_END_ANCHOR, start)
            if end < 0:
                end = maps_text.find(
                    "\n//----------------------------------------------------------------------------", start + 5
                )
                if end < 0:
                    end = len(maps_text)
                else:
                    end += 1
            maps_text = maps_text[:start].rstrip("\n") + "\n\n" + maps_text[end:]
            changed = True
            break

    for title in ("ESMS 17", "ESMS 35", "ESNZ 12"):
        marker = f"MAP:{title}:T"
        while marker in maps_text:
            start = maps_text.find(marker)
            rnp = maps_text.rfind("//----------------------------------------------------------------------------RNP APP", 0, start)
            twr = maps_text.find(BLOCK_END_ANCHOR)
            if rnp < 0 or twr < 0 or not (rnp < start < twr):
                break
            block_start = start
            probe = start
            while True:
                prev_nl = maps_text.rfind("\n", 0, probe)
                if prev_nl < 0:
                    break
                prev = maps_text[prev_nl + 1 : probe]
                if prev.strip() == "" or prev.lstrip().startswith("//"):
                    block_start = prev_nl + 1
                    probe = prev_nl
                    continue
                break
            nxt = maps_text.find("\nMAP:", start + 1)
            if nxt < 0:
                nxt = twr
            else:
                nxt += 1
            maps_text = maps_text[:block_start] + maps_text[nxt:]

    anchor = maps_text.find(BLOCK_END_ANCHOR)
    if anchor < 0:
        raise SystemExit("anchor ESSA TWR TMA section not found")
    return maps_text[:anchor].rstrip("\n") + "\n\n" + block + maps_text[anchor:]


def main() -> None:
    topsky = TOPSKY.read_bytes().decode("cp1252")
    sct_path = find_sct()
    sct_text = sct_path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_topsky_rnp_ar(topsky)
    block, kept = build_block(parsed, sct_text)

    maps = MAPS.read_bytes().decode("cp1252")
    maps = upsert_block(maps, block)
    MAPS.write_bytes(maps.encode("cp1252"))

    skipped = [t for t, _ in parsed if t.upper().startswith(SKIP_PREFIXES)]
    print(f"SCT: {sct_path.name}")
    print(f"TopSky RNP AR maps: {len(parsed)}")
    print(f"Added to GRP: {kept}")
    print(f"Skipped: {', '.join(skipped)}")
    for title, _ in parsed:
        if not title.upper().startswith(SKIP_PREFIXES):
            print(f"  + {title}")
    print(f"Updated {MAPS}")


if __name__ == "__main__":
    main()
