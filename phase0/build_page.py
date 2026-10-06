#!/usr/bin/env python3
"""Inject inspector_data.json into the page template. No values are transformed."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
data = json.loads((HERE / "inspector_data.json").read_text())
blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
page = (HERE / "inspector_template.html").read_text().replace("/*__DATA__*/", blob)
(HERE / "agreement_inspector.html").write_text(page)
print(f"agreement_inspector.html: {len(page) / 1024:.0f} KB")
