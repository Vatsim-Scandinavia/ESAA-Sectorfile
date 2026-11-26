"""Tag centerlines: ESSA -> ESSATWR, all other (non-ESGG) -> RTC.

ESGG centerlines are intentionally not in GRpluginMaps (use ESAA_TWR_APP).
"""

from __future__ import annotations

from pathlib import Path

MAPS = Path(__file__).resolve().parents[1] / "Plugins" / "GRpluginMaps.txt"

ESSA_CL = {
    "MAP:CENTERLINE 01L:AT",
    "MAP:CENTERLINE 01R:AT",
    "MAP:CENTERLINE 08:AT",
    "MAP:CENTERLINE 19L:AT",
    "MAP:CENTERLINE 19R:AT",
    "MAP:CENTERLINE 26:AT",
}


def classify(name: str) -> str | None:
    if not name.startswith("MAP:CENTERLINE "):
        return None
    if name.startswith("MAP:CENTERLINE ESGG"):
        return None  # should not exist; skip if present
    if name in ESSA_CL:
        return "TWR,ESSATWR"
    return "RTC"


def main() -> None:
    lines = MAPS.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    counts = {"ESSATWR": 0, "RTC": 0, "removed_esgg": 0, "other": 0}
    i = 0
    while i < len(lines):
        if not lines[i].startswith("MAP:"):
            out.append(lines[i])
            i += 1
            continue
        name = lines[i]
        block = [lines[i]]
        i += 1
        while i < len(lines) and not lines[i].startswith("MAP:"):
            block.append(lines[i])
            i += 1

        if name.startswith("MAP:CENTERLINE ESGG"):
            counts["removed_esgg"] += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue

        tags = classify(name)
        if tags is None:
            out.extend(block)
            counts["other"] += 1
            continue

        new_block: list[str] = []
        done = False
        for line in block:
            if line.startswith("ASRDATA:"):
                new_block.append(f"ASRDATA:{tags}")
                done = True
            else:
                new_block.append(line)
        if not done:
            insert_at = 1
            while insert_at < len(new_block) and new_block[insert_at].startswith(
                ("FOLDER:", "ACTIVE:", "COLOR:", "STYLE:", "AIRPORT:", "HIDDEN")
            ):
                insert_at += 1
            new_block.insert(insert_at, f"ASRDATA:{tags}")
        out.extend(new_block)
        if "ESSATWR" in tags:
            counts["ESSATWR"] += 1
        else:
            counts["RTC"] += 1

    MAPS.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"updated {MAPS}: {counts}")


if __name__ == "__main__":
    main()
