"""Generate artificial time capsules (like the mainline seed) via the API.

POSTs a handful of Berkeley-area capsules — real place names, real lat/lng, and a
photo from ui/photos/ — to the running backend on :8000, so they appear as pins
on the app's dig-up map. Each capsule also carries a short first-person note.

Run (backend must be up):  .venv/bin/python data/derek_handoff/gen_capsules.py
"""

from __future__ import annotations

import mimetypes
import sys
import urllib.request
import uuid
from pathlib import Path

API = "http://127.0.0.1:8000/api/capsules"
PHOTOS = Path(__file__).resolve().parents[2] / "ui" / "photos"

# (title/place, lat, lng, photo, note) — the 4 mainline capsules + a few more,
# spread across Berkeley Southside / campus on the real Cal Hacks timeline.
CAPSULES = [
    ("The room on Durant", 37.867839, -122.256194, "img_2298.jpg",
     "The morning of — half-dark room on Durant. I said yes to the team before I felt ready."),
    ("Quargo Coffee", 37.867930, -122.259000, "img_2303.jpg",
     "Quiet Telegraph, fog not burned off yet. The last calm before 24 hours of noise."),
    ("Opening ceremony", 37.871050, -122.259220, "img_2316.jpg",
     "In the dark before any code, I watched the sponsors' numbers climb and let myself believe."),
    ("The build", 37.869200, -122.259500, "img_2334.jpg",
     "Somewhere between the llama and the robots, the four of us stopped planning and started building."),
    ("Sather Tower", 37.872090, -122.257860, "img_2311.jpg",
     "Climbed up between commits. The whole bay laid out, and a clock that's older than all of us."),
    ("Memorial Glade", 37.873550, -122.258880, "img_2320.jpg",
     "Grass, sun, twenty minutes of not staring at a screen. Needed this more than I knew."),
    ("Doe Library steps", 37.872400, -122.259600, "img_2307.jpg",
     "Sat on the steps debugging. Strangers studying all around — a good kind of alone."),
    ("Bancroft & Telegraph", 37.868700, -122.258700, "img_2321.jpg",
     "Late-night food run. Everything closed except the one place that's always open."),
]


def post_capsule(title, lat, lng, photo, note):
    """Build a multipart/form-data POST with a photo + a note file."""
    boundary = "----recall" + uuid.uuid4().hex
    parts = []

    def field(name, value):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )

    def file_field(name, filename, content, ctype):
        parts.append(
            (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
             f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n').encode()
            + content + b"\r\n"
        )

    field("place_name", title)
    field("lat", str(lat))
    field("lng", str(lng))
    file_field("media", "note.txt", note.encode(), "text/plain")
    p = PHOTOS / photo
    if p.exists():
        ctype = mimetypes.guess_type(str(p))[0] or "image/jpeg"
        file_field("media", photo, p.read_bytes(), ctype)
    parts.append(f"--{boundary}--\r\n".encode())

    body = b"".join(parts)
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def main():
    if not PHOTOS.exists():
        print(f"photos dir missing: {PHOTOS}", file=sys.stderr)
        sys.exit(1)
    ok = 0
    for title, lat, lng, photo, note in CAPSULES:
        try:
            status = post_capsule(title, lat, lng, photo, note)
            print(f"  [{status}] {title}  ({lat:.5f}, {lng:.5f})  {photo}")
            ok += 1
        except Exception as e:
            print(f"  FAILED {title}: {e}", file=sys.stderr)
    print(f"\ncreated {ok}/{len(CAPSULES)} capsules")


if __name__ == "__main__":
    main()
