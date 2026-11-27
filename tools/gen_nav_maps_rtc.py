"""Regenerate GRP NAV maps: FIXES, FIXES + L, RNP, RNP + L, NDB, NDB + L.

FIXES/RNP names come from ASR/ESAA_TWR_APP.asr Fixes: entries
(already FIR-filtered). Classification:
  AA### -> RNP
  AAAAA in RNP_NAMED -> RNP (terminal/RNP procedure fixes)
  other AAAAA -> FIX

NDBs come from the EuroScope SCT [NDB] section; symbols outside ESAA FIR
+ 50 NM are kept but commented out.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.ops import transform

ESAA = Path(__file__).resolve().parents[1]
MAPS = ESAA / "Plugins" / "GRpluginMaps.txt"
ASR = ESAA / "ASR" / "ESAA_TWR_APP.asr"
TOPSKY = ESAA / "OTHER" / "TopSkyAreas.txt"
EUROSCOPE = Path.home() / "AppData" / "Roaming" / "EuroScope"

FIR_BUFFER_NM = 50.0
FIR_SIMPLIFY_NM = 8.0

FIX_RE = re.compile(r"^[A-Z]{5}$")
RNP_RE = re.compile(r"^[A-Z]{2}\d{3}$")

# Named fixes that belong on RNP (not FIXES). UVTUK = user "UTVUK".
RNP_NAMED = {
    "ABKIN",
    "AGDIS",
    "BAGLO",
    "BALEX",
    "BALNU",
    "BAMAX",
    "BYGDE",
    "DEMUS",
    "DIMGA",
    "DITVA",
    "DIXOT",
    "DOSIV",
    "DUXNO",
    "EKLOV",
    "EKMUN",
    "EMDOL",
    "ENOVI",
    "EPITA",
    "EXENA",
    "GATVI",
    "GESRI",
    "GIXAK",
    "GOKPU",
    "GOLAV",
    "GOPNI",
    "IBTOX",
    "IDMUK",
    "INDAK",
    "IXIBI",
    "LENGO",
    "LUVIX",
    "MENZO",
    "MOKMO",
    "NATVI",
    "NEKPO",
    "NOLGI",
    "OLGOL",
    "OSDOK",
    "OSRUK",
    "PASCA",
    "PELAB",
    "RETGU",
    "RILUG",
    "RUGIX",
    "RUWER",
    "SIRVA",
    "SOPAK",
    "SOVAS",
    "SULAX",
    "SUXEM",
    "TAKOT",
    "TESVI",
    "TUVIX",
    "ULGOT",
    "UPLAX",
    "UVTUK",
    "VAPUB",
    "VEPAX",
    "XENBU",
    "XIBTI",
}
COORD_RE = re.compile(
    r"([NS])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})\s+([EW])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})"
)
TOPS_COORD_RE = re.compile(
    r"([NS])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3}):([EW])(\d{3})\.(\d{2})\.(\d{2})\.(\d{3})"
)


def dms_to_deg(hemi: str, d: str | int, mi: str | int, s: str | int, f: str | int) -> float:
    val = int(d) + int(mi) / 60.0 + (int(s) + int(f) / 1000.0) / 3600.0
    return -val if hemi in ("S", "W") else val


def fmt_coord(lat: float, lon: float) -> tuple[str, str]:
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


def find_sct() -> Path:
    cands = list(EUROSCOPE.glob("ESAA-Sweden*.sct")) + list(ESAA.glob("ESAA-Sweden*.sct"))
    if not cands:
        raise FileNotFoundError("No ESAA-Sweden*.sct found")
    return max(cands, key=lambda p: p.stat().st_mtime)


def parse_esa_fir_buffer() -> Polygon:
    coords: list[tuple[float, float]] = []
    in_area = False
    for line in TOPSKY.read_text(encoding="latin-1", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("AREA:"):
            if in_area:
                break
            if s == "AREA:TCTA:ESAA FIR":
                in_area = True
            continue
        if not in_area or not s or s.startswith(("//", "LIMITS:", "TCTA_")):
            continue
        m = TOPS_COORD_RE.fullmatch(s)
        if not m:
            continue
        lat = dms_to_deg(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
        lon = dms_to_deg(m.group(6), m.group(7), m.group(8), m.group(9), m.group(10))
        coords.append((lon, lat))
    if len(coords) < 3:
        raise RuntimeError("ESAA FIR not found")
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)

    lat0 = poly.centroid.y
    cos_lat = max(0.2, math.cos(math.radians(lat0)))

    def to_nm(x, y, z=None):
        return (x * 60.0 * cos_lat, y * 60.0)

    def to_ll(x, y, z=None):
        return (x / (60.0 * cos_lat), y / 60.0)

    buf = transform(to_nm, poly).buffer(FIR_BUFFER_NM)
    buf = buf.simplify(FIR_SIMPLIFY_NM, preserve_topology=True)
    out = transform(to_ll, buf)
    if out.geom_type != "Polygon":
        out = max(out.geoms, key=lambda g: g.area)
    return out


def asr_fixes() -> list[str]:
    text = ASR.read_text(encoding="utf-8", errors="replace")
    return sorted(
        {m.group(1) for m in re.finditer(r"^Fixes:([A-Z0-9]+):symbol\s*$", text, re.M)}
    )


def parse_sct_ndbs(sct_text: str) -> list[tuple[str, float, float]]:
    m = re.search(r"\[NDB\](.*?)(?=\n\[|\Z)", sct_text, re.S)
    if not m:
        return []
    out: list[tuple[str, float, float]] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        mm = COORD_RE.search(line)
        if not mm:
            continue
        name = line.split()[0]
        lat = dms_to_deg(mm.group(1), mm.group(2), mm.group(3), mm.group(4), mm.group(5))
        lon = dms_to_deg(mm.group(6), mm.group(7), mm.group(8), mm.group(9), mm.group(10))
        out.append((name, lat, lon))
    out.sort(key=lambda r: r[0])
    return out


def map_span(maps: str, map_name: str) -> tuple[int, int]:
    """Return [start, end) covering optional leading // comments through end of map body."""
    marker = f"MAP:{map_name}:T"
    start = maps.find(marker)
    if start < 0:
        raise SystemExit(f"map {map_name!r} not found")
    next_map = maps.find("\nMAP:", start + len(marker))
    if next_map < 0:
        raise SystemExit(f"no following MAP after {map_name}")
    # Include preceding // comment / blank lines that belong to this map
    probe = start
    block_start = start
    while True:
        prev_nl = maps.rfind("\n", 0, probe)
        if prev_nl < 0:
            break
        prev_line = maps[prev_nl + 1 : probe]
        if prev_line.strip() == "" or prev_line.lstrip().startswith("//"):
            block_start = prev_nl + 1
            probe = prev_nl
            continue
        break
    return block_start, next_map + 1


def replace_map(maps: str, map_name: str, body: str) -> str:
    start, end = map_span(maps, map_name)
    return maps[:start] + body.rstrip() + "\n\n\n" + maps[end:]


def build_named_map(
    title: str,
    asrdata: str,
    symbol: str,
    names: list[str],
    *,
    labels: bool,
    active: bool,
    comment: str | None = None,
) -> str:
    rows: list[str] = []
    if comment:
        rows.append(comment)
        rows.append("")
    rows.append(f"MAP:{title}:T")
    rows.append("AIRPORT:ESAA")
    rows.append("FOLDER:NAV")
    rows.append(f"ASRDATA:{asrdata}")
    rows.append("COLOR:WHITE")
    if active:
        rows.append("ACTIVE:1")
    if labels:
        for n in names:
            rows.append(f"SYMBOL/LB:{symbol}:{n}:{n}:6:-6")
    else:
        for n in names:
            rows.append(f"SYMBOL:{symbol}:{n}")
    return "\n".join(rows) + "\n"


def build_ndb_maps(ndbs: list[tuple[str, float, float, bool]]) -> tuple[str, str]:
    sym_rows = [
        "// NDBs from SCT (FIX symbol); hidden on ESSA TWR",
        "",
        "MAP:NDB:T",
        "AIRPORT:ESAA",
        "FOLDER:NAV",
        "ASRDATA:NDB,RTC",
        "COLOR:WHITE",
        "ACTIVE:1",
    ]
    lab_rows = [
        "MAP:NDB + L:T",
        "AIRPORT:ESAA",
        "FOLDER:NAV",
        "ASRDATA:NDB,RTC",
        "COLOR:WHITE",
    ]
    for name, lat, lon, inside in ndbs:
        la, lo = fmt_coord(lat, lon)
        if inside:
            sym_rows.append(f"SYMBOL:FIX:{la}:{lo}")
            lab_rows.append(f"SYMBOL/LB:FIX:{la}:{lo}:{name}:6:-6")
        else:
            sym_rows.append(f"//SYMBOL:FIX:{la}:{lo}")
            lab_rows.append(f"//SYMBOL:FIX:{la}:{lo}")
    return "\n".join(sym_rows) + "\n", "\n".join(lab_rows) + "\n"


def main() -> None:
    sct_path = find_sct()
    sct_text = sct_path.read_text(encoding="utf-8", errors="replace")
    fir = parse_esa_fir_buffer()

    fixes = asr_fixes()
    rnp_names = sorted(
        n for n in fixes if RNP_RE.fullmatch(n) or n in RNP_NAMED
    )
    fix_names = sorted(
        n for n in fixes if FIX_RE.fullmatch(n) and n not in RNP_NAMED
    )
    classified = set(fix_names) | set(rnp_names)
    other = [n for n in fixes if n not in classified]
    if other:
        raise SystemExit(f"unclassified Fixes entries: {other}")
    missing_named = sorted(n for n in RNP_NAMED if n not in fixes)
    if missing_named:
        print(f"WARNING: RNP_NAMED not in ASR Fixes: {', '.join(missing_named)}")

    ndbs = [
        (name, lat, lon, fir.contains(Point(lon, lat)) or fir.touches(Point(lon, lat)))
        for name, lat, lon in parse_sct_ndbs(sct_text)
    ]
    ndb_sym, ndb_lab = build_ndb_maps(ndbs)

    maps = MAPS.read_bytes().decode("cp1252")
    maps = replace_map(maps, "NDB", ndb_sym)
    maps = replace_map(maps, "NDB + L", ndb_lab)
    maps = replace_map(
        maps,
        "FIXES",
        build_named_map("FIXES", "FIX,RTC", "FIX", fix_names, labels=False, active=True),
    )
    maps = replace_map(
        maps,
        "FIXES + L",
        build_named_map("FIXES + L", "FIX,RTC", "FIX", fix_names, labels=True, active=False),
    )
    maps = replace_map(
        maps,
        "RNP",
        build_named_map(
            "RNP",
            "RNP,RTC",
            "RNP",
            rnp_names,
            labels=False,
            active=True,
            comment="// RNP: XX### + named terminal/RNP fixes from ESAA_TWR_APP.asr",
        ),
    )
    maps = replace_map(
        maps,
        "RNP + L",
        build_named_map("RNP + L", "RNP,RTC", "RNP", rnp_names, labels=True, active=False),
    )

    MAPS.write_bytes(maps.encode("cp1252"))
    inside = sum(1 for *_, i in ndbs if i)
    print(f"SCT: {sct_path.name}")
    print(f"FIXES: {len(fix_names)}  RNP: {len(rnp_names)}")
    print(f"NDB: {len(ndbs)} total, {inside} inside FIR+{FIR_BUFFER_NM:.0f} NM")
    print(f"Updated {MAPS}")


if __name__ == "__main__":
    main()
