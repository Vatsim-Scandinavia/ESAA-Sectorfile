"""Generate RTC MVA line map excluding segments that coincide with CTR/TMA borders."""

from __future__ import annotations

import math
import re
from pathlib import Path

ESAA = Path(__file__).resolve().parents[1]
MAPS = ESAA / "Plugins" / "GRpluginMaps.txt"
TOPSKY = ESAA / "OTHER" / "TopSkyMaps.txt"
EUROSCOPE = Path.home() / "AppData" / "Roaming" / "EuroScope"

# ~25 m at mid latitudes — points closer than this are treated as the same
TOL_NM = 0.02
EARTH_NM = 3440.065
# Obstacle rings in MVA are ~3 NM (same as OBSTACLE CIRCLES)
OBS_CIRCLE_NM = 3.0
OBS_CIRCLE_TOL_NM = 0.35

MARKER_BEFORE = "MAP:MVA:T"  # insert MVA LINES just before label map
MAP_NAME = "MAP:MVA LINES:T"


def parse_dms(tok: str) -> float:
    hemi = tok[0]
    deg, mn, sec, frc = tok[1:].split(".")
    val = int(deg) + int(mn) / 60.0 + (int(sec) + int(frc) / 1000.0) / 3600.0
    return -val if hemi in "SW" else val


def dist_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(h)))


def near(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return dist_nm(a, b) <= TOL_NM


def find_sct() -> Path:
    cands = list(EUROSCOPE.glob("ESAA-Sweden*.sct")) + list(ESAA.glob("ESAA-Sweden*.sct"))
    if not cands:
        raise FileNotFoundError("No ESAA-Sweden*.sct found")
    return max(cands, key=lambda p: p.stat().st_mtime)


def parse_mva_lines(text: str) -> list[tuple[str, str, str, str]]:
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("MAP:AMA/MVA"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("MAP:"))
    out: list[tuple[str, str, str, str]] = []
    for l in lines[start:end]:
        if not l.startswith("LINE:"):
            continue
        p = l.split(":")
        if len(p) >= 5:
            out.append((p[1], p[2], p[3], p[4]))
    return out


def parse_sct_segments(sct_text: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    coord_re = re.compile(
        r"(N\d{3}\.\d{2}\.\d{2}\.\d{3})\s+([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})"
    )

    def add_from_block(block: str, name_prefixes: list[str] | None = None) -> None:
        for l in block.splitlines():
            if name_prefixes is not None:
                name = l[:40].strip() if l[:1].isalnum() else ""
                # continuation lines are indented; only filter by prefix on named lines
                if name and not any(name.startswith(p) for p in name_prefixes):
                    continue
            pts = coord_re.findall(l)
            if len(pts) >= 2:
                a = (parse_dms(pts[0][0]), parse_dms(pts[0][1]))
                b = (parse_dms(pts[1][0]), parse_dms(pts[1][1]))
                segs.append((a, b))

    for sect in ("ARTCC HIGH", "ARTCC LOW", "ARTCC"):
        m = re.search(rf"\[{re.escape(sect)}\](.*?)(\n\[|\Z)", sct_text, re.S | re.I)
        if m:
            # Include all ARTCC segments — TMA/CTR/borders used for coincidence
            add_from_block(m.group(1))

    m = re.search(r"\[GEO\](.*?)(\n\[|\Z)", sct_text, re.S | re.I)
    if m:
        add_from_block(
            m.group(1),
            ["ESNJ TMA", "ESNJ CTR", "ESMV TMA", "ESMV CTR"],
        )
    return segs


def quantize(pt: tuple[float, float]) -> tuple[int, int]:
    """Bucket points to ~TOL_NM cells (lat/lon degrees ≈ NM/60)."""
    cell = TOL_NM / 60.0
    return (int(round(pt[0] / cell)), int(round(pt[1] / cell)))


def border_keys(
    borders: list[tuple[tuple[float, float], tuple[float, float]]],
) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    keys: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for c, d in borders:
        keys.add(tuple(sorted((quantize(c), quantize(d)))))  # type: ignore[arg-type]
    return keys


def coincides(
    mva: tuple[tuple[float, float], tuple[float, float]],
    keys: set[tuple[tuple[int, int], tuple[int, int]]],
) -> bool:
    a, b = mva
    return tuple(sorted((quantize(a), quantize(b)))) in keys  # type: ignore[arg-type]


def parse_obs_centers(maps_text: str) -> list[tuple[float, float]]:
    """Obstacle positions from SYMBOL:OBS / COORD_CIRCLE in GRpluginMaps."""
    centers: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for m in re.finditer(
        r"(?:SYMBOL:OBS:|COORD_CIRCLE:)(N\d{3}\.\d{2}\.\d{2}\.\d{3}):([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})",
        maps_text,
    ):
        pt = (parse_dms(m.group(1)), parse_dms(m.group(2)))
        key = (round(pt[0], 5), round(pt[1], 5))
        if key not in seen:
            seen.add(key)
            centers.append(pt)
    return centers


def _on_obs_ring(
    pt: tuple[float, float],
    centers: list[tuple[float, float]],
) -> tuple[float, float] | None:
    """Return obstacle center if pt lies on its ~3 NM ring."""
    for c in centers:
        if abs(dist_nm(pt, c) - OBS_CIRCLE_NM) <= OBS_CIRCLE_TOL_NM:
            return c
    return None


def is_obs_circle_segment(
    a: tuple[float, float],
    b: tuple[float, float],
    centers: list[tuple[float, float]],
) -> bool:
    """True if both endpoints lie on an ~3 NM ring around the same obstacle."""
    ca, cb = _on_obs_ring(a, centers), _on_obs_ring(b, centers)
    return ca is not None and ca == cb


# Local stubs that only feed into a circle (outer end still near the same OBS)
OBS_STUB_MAX_NM = 6.0
# Trim long volume lines to stop clearly outside the ring (past detection tol)
OBS_TRIM_OUT_NM = OBS_CIRCLE_NM + OBS_CIRCLE_TOL_NM + 0.05


def _point_at_radius(
    inner: tuple[float, float],
    outer: tuple[float, float],
    center: tuple[float, float],
    radius_nm: float,
) -> tuple[float, float] | None:
    """Interpolate along outer→inner for the point at radius_nm from center."""
    # Binary search in lat/lon space along the segment (adequate at these ranges)
    lo, hi = 0.0, 1.0
    d_outer = dist_nm(outer, center)
    d_inner = dist_nm(inner, center)
    if d_outer < radius_nm:
        return None  # entire segment inside/on target radius
    if d_inner >= radius_nm:
        return inner  # already outside
    for _ in range(30):
        t = (lo + hi) / 2.0
        p = (outer[0] + t * (inner[0] - outer[0]), outer[1] + t * (inner[1] - outer[1]))
        if dist_nm(p, center) >= radius_nm:
            lo = t
        else:
            hi = t
    t = lo
    return (outer[0] + t * (inner[0] - outer[0]), outer[1] + t * (inner[1] - outer[1]))


def format_dms(lat: float, lon: float) -> tuple[str, str]:
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

    return one(lat, "N", "S"), one(lon, "E", "W")


def filter_obs_circle(
    lat1: str,
    lon1: str,
    lat2: str,
    lon2: str,
    centers: list[tuple[float, float]],
) -> tuple[str, str, str, str] | None:
    """Drop circle arcs/stubs; trim long lines that end on a ring. None = drop."""
    a = (parse_dms(lat1), parse_dms(lon1))
    b = (parse_dms(lat2), parse_dms(lon2))
    ca, cb = _on_obs_ring(a, centers), _on_obs_ring(b, centers)

    if ca is not None and cb is not None:
        return None  # arc or chord on the ring

    if ca is None and cb is None:
        return (lat1, lon1, lat2, lon2)

    # Exactly one endpoint on a ring
    if ca is not None:
        on_pt, off_pt, on_c = a, b, ca
        off_lat, off_lon = lat2, lon2
        on_first = True
    else:
        on_pt, off_pt, on_c = b, a, cb  # type: ignore[assignment]
        off_lat, off_lon = lat1, lon1
        on_first = False

    d_off = dist_nm(off_pt, on_c)
    if d_off <= OBS_STUB_MAX_NM:
        return None  # short stub into the circle

    trimmed = _point_at_radius(on_pt, off_pt, on_c, OBS_TRIM_OUT_NM)
    if trimmed is None or dist_nm(off_pt, trimmed) < TOL_NM:
        return None
    t_lat, t_lon = format_dms(trimmed[0], trimmed[1])
    if on_first:
        return (t_lat, t_lon, off_lat, off_lon)
    return (off_lat, off_lon, t_lat, t_lon)


def build_map(kept: list[tuple[str, str, str, str]]) -> str:
    rows = [
        MAP_NAME,
        "AIRPORT:ESAA",
        "FOLDER:MVA/OBST",
        "ASRDATA:MVA,RTC",
        "COLOR:WHITE/50",
        "STYLE:SOLID:1",
        "ACTIVE:1",
        "// MVA volume lines excl. CTR/TMA borders and obstacle circle rings",
    ]
    for lat1, lon1, lat2, lon2 in kept:
        rows.append(f"LINE:{lat1}:{lon1}:{lat2}:{lon2}")
    return "\n".join(rows) + "\n\n"


def upsert(maps_text: str, block: str) -> str:
    # Remove existing MVA LINES map if present
    if MAP_NAME in maps_text:
        start = maps_text.find(MAP_NAME)
        # end at next MAP: after start
        rest = maps_text.find("\nMAP:", start + 1)
        if rest < 0:
            rest = len(maps_text)
        maps_text = maps_text[:start] + maps_text[rest:].lstrip("\n")

    anchor = maps_text.find(MARKER_BEFORE)
    if anchor < 0:
        raise SystemExit(f"anchor {MARKER_BEFORE!r} not found")
    return maps_text[:anchor] + block + maps_text[anchor:]


def main() -> None:
    mva_raw = parse_mva_lines(TOPSKY.read_bytes().decode("cp1252"))
    maps = MAPS.read_bytes().decode("cp1252")
    sct_path = find_sct()
    borders = parse_sct_segments(sct_path.read_text(encoding="cp1252", errors="replace"))
    keys = border_keys(borders)
    obs = parse_obs_centers(maps)

    kept: list[tuple[str, str, str, str]] = []
    dropped_border = 0
    dropped_circle = 0
    trimmed_circle = 0
    for lat1, lon1, lat2, lon2 in mva_raw:
        a = (parse_dms(lat1), parse_dms(lon1))
        b = (parse_dms(lat2), parse_dms(lon2))
        if coincides((a, b), keys):
            dropped_border += 1
            continue
        filtered = filter_obs_circle(lat1, lon1, lat2, lon2, obs)
        if filtered is None:
            dropped_circle += 1
            continue
        if filtered != (lat1, lon1, lat2, lon2):
            trimmed_circle += 1
        kept.append(filtered)

    block = build_map(kept)
    MAPS.write_bytes(upsert(maps, block).encode("cp1252"))

    print(f"SCT: {sct_path.name}")
    print(f"Obstacles: {len(obs)}")
    print(f"CTR/TMA border segments: {len(borders)} ({len(keys)} unique keys)")
    print(
        f"MVA lines: {len(mva_raw)} total, kept {len(kept)}, "
        f"dropped border={dropped_border} circle={dropped_circle} "
        f"trimmed={trimmed_circle}"
    )
    print(f"Updated {MAPS}")


if __name__ == "__main__":
    main()
