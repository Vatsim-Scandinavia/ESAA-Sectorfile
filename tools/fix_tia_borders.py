"""TMA/CTR/TIA/TIZ borders via SCTFILEDATA (no inline LINE coords)."""

from __future__ import annotations

import re
from pathlib import Path

SCT_PATH = Path(
    r"C:\Users\maxlk\AppData\Roaming\EuroScope\ESAA-Sweden_20261029211836-261101-0001.sct"
)
GRP_PATH = Path(__file__).resolve().parents[1] / "Plugins" / "GRpluginMaps.txt"

coord_re = re.compile(
    r"([NS]\d{3}\.\d{2}\.\d{2}\.\d{3})\s+([EW]\d{3}\.\d{2}\.\d{2}\.\d{3})"
)


def section(text: list[str], name: str) -> list[str]:
    start = next(i for i, l in enumerate(text) if l.strip() == name) + 1
    end = next(
        (
            j
            for j in range(start, len(text))
            if text[j].startswith("[") and text[j].strip().endswith("]")
        ),
        len(text),
    )
    return text[start:end]


def artcc_names(lines: list[str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for l in lines:
        if not l.strip():
            continue
        coords = coord_re.findall(l)
        if not coords:
            continue
        before = l[: l.index(coords[0][0])].strip()
        if before and not before.startswith("COLOR") and before not in seen:
            seen.add(before)
            names.append(before)
    return names


def sct_refs(section_name: str, names: list[str]) -> list[str]:
    return [f"SCTFILEDATA/MONO:{section_name}\\{n}" for n in names]


def main() -> None:
    text = SCT_PATH.read_bytes().decode("latin-1", errors="replace").splitlines()
    high = artcc_names(section(text, "[ARTCC HIGH]"))
    low = artcc_names(section(text, "[ARTCC LOW]"))

    tia = [n for n in high if n.split()[-1] == "TIA"]
    tma = [n for n in high if n.split()[-1] != "TIA"]
    tiz = [n for n in low if n.split()[-1] == "TIZ"]
    ctr = [n for n in low if n.split()[-1] != "TIZ"]

    borders = [
        "// Common TMA (dashed) + CTR (dotted) from SCT; TIA/TIZ Alternate softer",
        "MAP:TMA CTR BORDERS:T",
        "HIDDEN",
        "FOLDER:AIRSPACE",
        "ASRDATA:TWR,COMMON",
        "COLOR:WHITE",
        "ACTIVE:1",
        "STYLE:DASH:1",
        *sct_refs("ARTCC HIGH", tma),
        "STYLE:DOT:1",
        *sct_refs("ARTCC LOW", ctr),
        "",
        "// TIA/TIZ borders from SCT — Alternate stroke, softer than TMA/CTR",
        "MAP:TIA TIZ BORDERS:T",
        "HIDDEN",
        "FOLDER:AIRSPACE",
        "ASRDATA:TWR,COMMON",
        "COLOR:WHITE/50",
        "ACTIVE:1",
        "STYLE:Alternate:1",
        *sct_refs("ARTCC HIGH", tia),
        *sct_refs("ARTCC LOW", tiz),
        "",
    ]

    grp = GRP_PATH.read_text(encoding="utf-8")
    start_markers = [
        "// Common dashed TMA (ARTCC HIGH) + inner-TMA/CTR (ARTCC LOW) borders for all TWR ASRs except ESSA",
        "// Common TMA borders (dashed) + TIZ/CTR (dotted); TIA dotted separately",
        "// Common TMA (dashed) + CTR (dotted); TIA/TIZ Alternate softer borders",
        "// Common TMA (dashed) + CTR (dotted) from SCT; TIA/TIZ Alternate softer",
    ]
    start = None
    for m in start_markers:
        if m in grp:
            start = grp.index(m)
            break
    if start is None:
        raise SystemExit("TMA CTR BORDERS block not found")

    end = grp.index("MAP:ESAA ACC LOW LEVEL:T")
    GRP_PATH.write_text(grp[:start] + "\n".join(borders) + grp[end:], encoding="utf-8")
    print(
        f"SCTFILEDATA refs: TMA {len(tma)}, CTR {len(ctr)}, TIA {len(tia)}, TIZ {len(tiz)}"
    )


if __name__ == "__main__":
    main()
