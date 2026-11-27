"""Add ESNJ/ESMV airspace folders plus per-area R/D/PCA maps to GRpluginMaps."""

from __future__ import annotations

import re
from pathlib import Path

ESAA = Path(__file__).resolve().parents[1]
MAPS = ESAA / "Plugins" / "GRpluginMaps.txt"
AREAS = ESAA / "OTHER" / "TopSkyAreas.txt"

MARKER = "MAP:OBSTACLES:T"
BLOCK_START = "// ESNJ / ESMV airspace"


def parse_areas(text: str) -> list[dict]:
    lines = text.splitlines()
    areas: list[dict] = []
    i = 0
    in_tempo_rd = False
    while i < len(lines):
        line = lines[i]
        if "START OF TEMPO R AND D AREAS" in line:
            in_tempo_rd = True
        elif "END OF TEMPO R AND D AREAS" in line:
            in_tempo_rd = False
        if not line.startswith("AREA:"):
            i += 1
            continue
        m = re.match(r"^AREA:([^:]+):(.*)$", line)
        assert m
        typ, rawname = m.group(1), m.group(2)
        name = rawname.lstrip()
        lead = len(rawname) - len(name)
        tempo = in_tempo_rd
        i += 1
        coords: list[tuple[str, str]] = []
        always_active = False
        while i < len(lines) and not lines[i].startswith("AREA:"):
            if "START OF TEMPO R AND D AREAS" in lines[i]:
                in_tempo_rd = True
            elif "END OF TEMPO R AND D AREAS" in lines[i]:
                in_tempo_rd = False
            ll = lines[i].strip()
            if ll == "ACTIVE:1":
                always_active = True
            if re.match(r"^N\d{3}\.\d{2}\.\d{2}\.\d{3}\s+[EW]", ll):
                lat, lon = ll.split()[:2]
                coords.append((lat, lon))
            i += 1
        areas.append(
            {
                "typ": typ,
                "name": name,
                "lead": lead,
                "coords": coords,
                "always_active": always_active,
                "tempo": tempo,
            }
        )
    return areas


def region_fill_border(
    coords: list[tuple[str, str]], fill_color: str, border_color: str, border_style: str
) -> list[str]:
    out = [f"COLOR:{fill_color}", "COORDTYPE:OTHER:REGION"]
    for lat, lon in coords:
        out.append(f"{lat} {lon}")
    out.append(f"COLOR:{border_color}")
    out.append(f"STYLE:{border_style}")
    for i, a in enumerate(coords):
        b = coords[(i + 1) % len(coords)]
        out.append(f"LINE:{a[0]}:{a[1]}:{b[0]}:{b[1]}")
    return out


def one_map(
    name: str,
    folder: str,
    asrdata: str,
    coords: list[tuple[str, str]],
    fill: str,
    border: str,
    style: str,
    always_active: bool = False,
) -> list[str]:
    # GRP map names cannot be awkward; keep area id as-is
    header = [
        f"MAP:{name}:T",
        "AIRPORT:ESAA",
        f"FOLDER:{folder}",
        f"ASRDATA:{asrdata}",
    ]
    if always_active:
        header.append("ACTIVE:1")
    return [
        *header,
        *region_fill_border(coords, fill, border, style),
        "",
    ]


def build_insert(areas: list[dict]) -> str:
    def is_rd(a: dict, letter: str) -> bool:
        return (
            not a["tempo"]
            and a["lead"] == 2
            and a["name"].startswith(letter)
            and len(a["name"]) > 1
            and a["name"][1].isdigit()
            and bool(a["coords"])
        )

    r_areas = [a for a in areas if is_rd(a, "R")]
    d_areas = [a for a in areas if is_rd(a, "D")]
    pca_areas = [a for a in areas if a["lead"] == 1 and a["typ"] == "T" and a["coords"]]

    esnj_esmv = f"""
{BLOCK_START} (GEO in SCT; toggle via folder)
MAP:ESNJ TMA CTR:T
AIRPORT:ESAA
FOLDER:ESNJ
ASRDATA:RTC
COLOR:WHITE
STYLE:DASH:1
SCTFILEDATA/MONO:GEO\\ESNJ TMA
STYLE:DOT:1
SCTFILEDATA/MONO:GEO\\ESNJ CTR

MAP:ESMV TMA CTR:T
AIRPORT:ESAA
FOLDER:ESMV
ASRDATA:RTC
COLOR:WHITE
STYLE:DASH:1
SCTFILEDATA/MONO:GEO\\ESMV TMA
STYLE:DOT:1
SCTFILEDATA/MONO:GEO\\ESMV CTR
""".strip(
        "\n"
    )

    parts: list[str] = [
        esnj_esmv,
        "",
        "// AIP R-areas from TopSkyAreas (excl. tempo; ACTIVE:1 when always-on)",
    ]
    for a in r_areas:
        parts.extend(
            one_map(
                a["name"],
                "R/D-Areas",
                "RAREAS,RTC",
                a["coords"],
                "RED/40",
                "RED",
                "SOLID:1",
                a["always_active"],
            )
        )

    parts.append("// AIP D-areas from TopSkyAreas (excl. tempo; ACTIVE:1 when always-on)")
    for a in d_areas:
        parts.extend(
            one_map(
                a["name"],
                "R/D-Areas",
                "RAREAS,RTC",
                a["coords"],
                "RED/40",
                "RED",
                "SOLID:1",
                a["always_active"],
            )
        )

    folder_pca = "PCA/CBA/TRA"
    parts.append("// PCA from TopSkyAreas (one map each; ACTIVE:1 when always-on in TopSky)")
    for a in pca_areas:
        parts.extend(
            one_map(
                a["name"],
                folder_pca,
                "PCA,RTC",
                a["coords"],
                "WHITE/12",
                "WHITE/70",
                "DASH:1",
                a["always_active"],
            )
        )

    def is_tra_cba(a: dict) -> bool:
        return (
            not a["tempo"]
            and a["lead"] == 2
            and bool(a["coords"])
            and (
                (a["name"].startswith("TRA") and len(a["name"]) > 3 and a["name"][3:].isdigit())
                or (a["name"].startswith("CBA") and len(a["name"]) > 3 and a["name"][3:].isdigit())
            )
        )

    # File order (with Window_Maps_Sorting=2): all PCAs, then CBA, TRA last
    cba_areas = sorted(
        [a for a in areas if is_tra_cba(a) and a["name"].startswith("CBA")],
        key=lambda a: a["name"],
    )
    tra_areas = sorted(
        [a for a in areas if is_tra_cba(a) and a["name"].startswith("TRA")],
        key=lambda a: a["name"],
    )
    parts.append("// CBA from TopSkyAreas (below PCAs, above TRA)")
    for a in cba_areas:
        parts.extend(
            one_map(
                a["name"],
                folder_pca,
                "PCA,RTC",
                a["coords"],
                "WHITE/12",
                "WHITE/70",
                "DASH:1",
                a["always_active"],
            )
        )
    parts.append("// TRA from TopSkyAreas (bottom of PCA/CBA/TRA)")
    for a in tra_areas:
        parts.extend(
            one_map(
                a["name"],
                folder_pca,
                "PCA,RTC",
                a["coords"],
                "WHITE/12",
                "WHITE/70",
                "DASH:1",
                a["always_active"],
            )
        )

    return "\n".join(parts).rstrip() + "\n\n"


def main() -> None:
    text = MAPS.read_bytes().decode("cp1252")
    areas = parse_areas(AREAS.read_bytes().decode("cp1252"))
    insert = build_insert(areas)

    if MARKER not in text:
        raise SystemExit(f"marker {MARKER!r} not found")

    start = text.find(BLOCK_START)
    if start < 0:
        start = text.find("MAP:ESNJ TMA CTR:T")
    obst = text.find(MARKER)
    if start >= 0 and obst > start:
        text = text[:start] + text[obst:]
        obst = text.find(MARKER)

    text = text[:obst] + insert + text[obst:]
    MAPS.write_bytes(text.encode("cp1252"))

    def is_r(a: dict) -> bool:
        return (
            not a["tempo"]
            and a["lead"] == 2
            and a["name"].startswith("R")
            and len(a["name"]) > 1
            and a["name"][1].isdigit()
            and bool(a["coords"])
        )

    def is_d(a: dict) -> bool:
        return (
            not a["tempo"]
            and a["lead"] == 2
            and a["name"].startswith("D")
            and len(a["name"]) > 1
            and a["name"][1].isdigit()
            and bool(a["coords"])
        )

    def is_pca(a: dict) -> bool:
        return a["lead"] == 1 and a["typ"] == "T" and bool(a["coords"])

    def is_tra_cba(a: dict) -> bool:
        return (
            not a["tempo"]
            and a["lead"] == 2
            and bool(a["coords"])
            and (
                (a["name"].startswith("TRA") and len(a["name"]) > 3 and a["name"][3:].isdigit())
                or (a["name"].startswith("CBA") and len(a["name"]) > 3 and a["name"][3:].isdigit())
            )
        )

    r_n = sum(1 for a in areas if is_r(a))
    d_n = sum(1 for a in areas if is_d(a))
    pca_n = sum(1 for a in areas if is_pca(a))
    tra_n = sum(1 for a in areas if is_tra_cba(a))
    tempo_n = sum(
        1
        for a in areas
        if a["tempo"]
        and a["lead"] == 2
        and a["name"][:1] in "RD"
        and len(a["name"]) > 1
        and a["name"][1].isdigit()
    )
    always = [
        a["name"]
        for a in areas
        if a["always_active"] and (is_r(a) or is_d(a) or is_pca(a) or is_tra_cba(a))
    ]
    print(f"Updated {MAPS}")
    print(
        f"Maps: R={r_n}, D={d_n}, PCA={pca_n}, CBA/TRA={tra_n} "
        f"(plus ESNJ/ESMV); skipped tempo R/D={tempo_n}"
    )
    print(f"ACTIVE:1 ({len(always)}): {', '.join(always)}")


if __name__ == "__main__":
    main()
