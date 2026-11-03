"""Duolingo-style otter expressions, one per moment in the app.

Uses Muse Image edit mode with the mascot (static/mascot/otter_base.png) as the
reference, then cuts the white background to transparent.

    python scripts/otter_moods.py            # make all of them (~$0.06)
    python scripts/otter_moods.py proud oops # remake just these

Scene props (sun, cloud, cloud2, boat) are painted too: python scripts/otter_moods.py sun cloud cloud2 boat

Where each one shows up:
  bed_sleep  morning intro: fast asleep in its little paper bed
  bed_yawn   morning intro: sitting up in bed, stretching and yawning
  hello      morning intro: out of bed, waving "good morning!"
  proud    yesterday's card when you finished everything; completion pop-up
  hug      yesterday's card on a lighter day; "running low" mornings
  curious  "how are you feeling?" question
  thumbs   today's plan is ready
  oops     something went wrong
"""
import base64
import os
import sys
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI
from PIL import Image

client = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"])
REF = "static/mascot/otter_base.png"

STYLE = ("Handmade paper cut-out illustration made of layered torn construction paper, visible paper "
         "grain, subtle drop shadows between paper layers. The exact same small, chubby purple sea otter "
         "character from the reference image: same purple paper body, same cream paper face and belly, "
         "same little orange paper scarf, same paper whiskers. Expressive cartoon mascot, like an app "
         "mascot sticker. Only the otter, no other objects unless named, no text, no letters. "
         "Plain pure white background, centered, full body visible. Pose and expression: ")

MOODS = {
    "bed_sleep": "fast asleep in a small cosy paper bed with a wooden paper headboard, a lilac paper "
                 "blanket pulled up to its chin and a round white paper pillow, eyes closed as two gentle "
                 "curved lines, peaceful little smile. Side-front view of the bed. The bed is the only object.",
    "bed_yawn": "in the same small cosy paper bed with a wooden paper headboard, lilac paper blanket and "
                "white paper pillow, now sitting up with the blanket slipping down to its lap, stretching "
                "both paws high above its head, mouth wide open in a big cute yawn, eyes squeezed shut. "
                "The bed is the only object.",
    "hello": "standing on its toes and leaning forward, both paws cupped around its open mouth like it is "
             "calling out a big cheerful 'good morning!' across a field, eyes squeezed happily shut, tail "
             "flicked up, scarf flying. Both paws must be at its mouth, not waving.",
    "proud": "jumping for joy with both paws thrown up in the air, eyes closed in two happy upside-down "
             "curves, huge open-mouth grin, tail flicked up, pure celebration.",
    "hug": "hugging a small red paper heart to its chest with both paws, soft gentle smile, eyes "
           "half closed, warm and kind, head tilted slightly.",
    "curious": "head tilted to one side, one paw on its chin, eyes wide and bright, little curious "
               "smile, like it's asking a friendly question.",
    "thumbs": "giving a confident thumbs-up with one paw, winking one eye, big confident smile, "
              "other paw on its hip.",
    "oops": "sheepish embarrassed smile showing teeth, one paw scratching the back of its head, "
            "eyebrows raised, small paper sweat drop near its head.",
}


def cut_white_to_transparent(path, tolerance=232):
    """Flood-fill white from the edges so the cream belly/face stay opaque; trim and shrink."""
    rgba = Image.open(path).convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    seen = bytearray(w * h)
    q = deque([(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
              + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)])
    while q:
        x, y = q.popleft()
        if not (0 <= x < w and 0 <= y < h):
            continue
        i = y * w + x
        if seen[i]:
            continue
        seen[i] = 1
        r, g, b, _ = px[x, y]
        if min(r, g, b) < tolerance:
            continue
        px[x, y] = (r, g, b, 0)
        q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    if rgba.getbbox():
        rgba = rgba.crop(rgba.getbbox())
    rgba.thumbnail((640, 640))
    rgba.save(path, optimize=True)


# Scene props (no otter): painted from scratch in the same torn-paper style.
PROP_STYLE = ("Handmade paper cut-out craft made of layered torn construction paper, visible paper grain and "
              "fibres, crinkled paper texture, soft drop shadows between layers, white torn paper edges, "
              "same style as a cosy children's picture book papercraft. Only this one object, no text, no "
              "letters, no faces. Plain pure white background, centered, whole object visible: ")
PROPS = {
    "sun": "a bright warm sun: a round golden-yellow paper circle with a lighter yellow inner circle, "
           "surrounded by twelve pointed orange-yellow paper rays evenly spaced around it.",
    "cloud": "one fluffy soft white paper cloud with a light blue-grey paper layer underneath for shading, "
             "wide and puffy, side view.",
    "cloud2": "one small rounded white paper cloud with three puffs and a pale lilac paper shadow layer "
              "underneath.",
    "boat": "a small classic folded origami paper boat made of white and pale lilac paper, side view, "
            "empty, no water.",
}


def make_prop(name):
    try:
        res = client.images.generate(model="muse-image-1.0", prompt=PROP_STYLE + PROPS[name])
        img = res.data[0]
        out = f"static/mascot/prop_{name}.png"
        if getattr(img, "b64_json", None):
            with open(out, "wb") as f:
                f.write(base64.b64decode(img.b64_json))
        else:
            urllib.request.urlretrieve(img.url, out)
        cut_white_to_transparent(out)
        return f"✅ {name}  ->  {out}"
    except Exception as e:
        return f"❌ {name}: {e}"


def make(name):
    if name in PROPS:
        return make_prop(name)
    with open(REF, "rb") as f:
        ref = f.read()
    mime = "image/webp" if ref[:4] == b"RIFF" else "image/png"
    try:
        res = client.images.edit(model="muse-image-1.0",
                                 image=("otter_base" + (".webp" if mime.endswith("webp") else ".png"), ref, mime),
                                 prompt=STYLE + MOODS[name])
        img = res.data[0]
        out = f"static/mascot/otter_{name}.png"
        if getattr(img, "b64_json", None):
            with open(out, "wb") as f:
                f.write(base64.b64decode(img.b64_json))
        else:
            urllib.request.urlretrieve(img.url, out)
        cut_white_to_transparent(out)
        return f"✅ {name}  ->  {out}"
    except Exception as e:
        return f"❌ {name}: {e}"


if __name__ == "__main__":
    names = [n for n in sys.argv[1:] if n in MOODS or n in PROPS] or list(MOODS) + list(PROPS)
    print(f"Painting {len(names)} pictures with Muse Image… (about a minute)")
    with ThreadPoolExecutor(max_workers=len(names)) as ex:
        for line in ex.map(make, names):
            print(line)
    print("Done. Refresh Tandem in Chrome. Don't like one? Run: python scripts/otter_moods.py <name>")
