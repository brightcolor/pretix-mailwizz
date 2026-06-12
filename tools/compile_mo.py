"""
Minimal .po → .mo compiler so translations can be built without the
gettext binaries (e.g. on Windows dev machines).

Usage: python tools/compile_mo.py
Compiles every django.po below pretix_mailwizz/locale/.
"""
import struct
from pathlib import Path


def parse_po(path: Path) -> dict:
    catalog = {}
    msgid, msgstr, section = [], [], None
    for raw in path.read_text(encoding="utf-8").splitlines() + [""]:
        line = raw.strip()
        if line.startswith("#") or not line:
            if msgid or msgstr:
                catalog["".join(msgid)] = "".join(msgstr)
                msgid, msgstr, section = [], [], None
            continue
        if line.startswith("msgid "):
            if msgid or msgstr:
                catalog["".join(msgid)] = "".join(msgstr)
                msgid, msgstr = [], []
            section = "id"
            line = line[6:]
        elif line.startswith("msgstr "):
            section = "str"
            line = line[7:]
        if line.startswith('"') and line.endswith('"'):
            text = line[1:-1]
            # unescape the subset gettext uses
            text = (
                text.replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace("\\\\", "\\")
            )
            (msgid if section == "id" else msgstr).append(text)
    return catalog


def write_mo(catalog: dict, path: Path) -> None:
    items = sorted(catalog.items())
    ids = b""
    strs = b""
    offsets = []
    for k, v in items:
        kb, vb = k.encode("utf-8"), v.encode("utf-8")
        offsets.append((len(ids), len(kb), len(strs), len(vb)))
        ids += kb + b"\x00"
        strs += vb + b"\x00"
    n = len(items)
    keystart = 7 * 4 + 16 * n
    valuestart = keystart + len(ids)
    koffsets, voffsets = [], []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    output = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    output += struct.pack(f"{2 * n}i", *koffsets)
    output += struct.pack(f"{2 * n}i", *voffsets)
    output += ids + strs
    path.write_bytes(output)


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent / "pretix_mailwizz" / "locale"
    for po in base.rglob("django.po"):
        mo = po.with_suffix(".mo")
        write_mo(parse_po(po), mo)
        print(f"compiled {po} -> {mo}")
