"""Sleeping-otter art for the goodnight screen: edit the mascot reference into
the same otter curled up asleep on a paper moon, then cut the white background."""
import base64
import os
import urllib.request
from collections import deque

from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI
from PIL import Image

client = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"])

REF = "static/mascot/otter_base.png"
OUT = "static/mascot/otter_sleep.png"

PROMPT = (
    "Handmade paper cut-out illustration made of layered torn construction paper, "
    "visible paper grain, subtle drop shadows between paper layers, no text. "
    "The same small, chubby purple sea otter from the reference image (cream paper "
    "belly, tiny orange paper scarf), curled up asleep on a paper crescent moon, "
    "eyes closed, peaceful smile, scarf tucked around it like a tiny blanket. "
    "Plain white background, centered, side view."
)

with open(REF, "rb") as f:
    ref_bytes = f.read()
mime = "image/webp" if ref_bytes[:4] == b"RIFF" else "image/png"
result = client.images.edit(
    model="muse-image-1.0",
    image=("otter_base" + (".webp" if mime.endswith("webp") else ".png"), ref_bytes, mime),
    prompt=PROMPT,
)
img = result.data[0]
os.makedirs("static/mascot", exist_ok=True)
if getattr(img, "b64_json", None):
    with open(OUT, "wb") as f:
        f.write(base64.b64decode(img.b64_json))
else:
    urllib.request.urlretrieve(img.url, OUT)
print("saved", OUT)


def cut_white_to_transparent(path, tolerance=235):
    """Flood-fill the white background from the edges so interior light paper
    tones (belly, moon) stay opaque."""
    rgba = Image.open(path).convert("RGBA")
    w, h = rgba.size
    px = rgba.load()

    def near_white(x, y):
        r, g, b, _ = px[x, y]
        return min(r, g, b) >= tolerance

    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.append((x, 0))
        q.append((x, h - 1))
    for y in range(h):
        q.append((0, y))
        q.append((w - 1, y))
    cleared = 0
    while q:
        x, y = q.popleft()
        if not (0 <= x < w and 0 <= y < h):
            continue
        i = y * w + x
        if seen[i] or not near_white(x, y):
            continue
        seen[i] = 1
        r, g, b, _ = px[x, y]
        px[x, y] = (r, g, b, 0)
        cleared += 1
        q.append((x + 1, y))
        q.append((x - 1, y))
        q.append((x, y + 1))
        q.append((x, y - 1))
    rgba.save(path)
    print(f"cut background: {cleared} px transparent, size {w}x{h}")


cut_white_to_transparent(OUT)
