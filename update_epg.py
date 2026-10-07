import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "channels.json").read_text(encoding="utf-8"))
EPG_SOURCE = CFG["epg_source"]

req = urllib.request.Request(EPG_SOURCE, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=60) as r:
    data = r.read()

root = ET.fromstring(data)
wanted = {ch["epg_id"]: ch["id"] for ch in CFG["channels"] if ch.get("epg_id")}

out = ET.Element("tv", {
    "generator-info-name": "fatihkartl/turk-tv-playlist",
    "source-info-url": EPG_SOURCE
})

seen = set()
for elem in root:
    if elem.tag == "channel":
        old = elem.attrib.get("id", "")
        if old in wanted and wanted[old] not in seen:
            elem.attrib["id"] = wanted[old]
            out.append(elem)
            seen.add(wanted[old])

for elem in root:
    if elem.tag == "programme":
        old = elem.attrib.get("channel", "")
        if old in wanted:
            elem.attrib["channel"] = wanted[old]
            out.append(elem)

ET.ElementTree(out).write(ROOT / "epg_turkiye.xml", encoding="utf-8", xml_declaration=True)
print(f"{len(seen)} kanal için EPG oluşturuldu.")
