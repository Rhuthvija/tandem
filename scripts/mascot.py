import os, base64, urllib.request
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI

client = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"])

STYLE = ("A handmade paper cut-out character for a stop-motion animation: a small, chubby purple "
         "sea otter made of layered cut construction paper, with a cream paper belly and a tiny "
         "warm-orange paper scarf. Visible paper grain and torn, slightly uneven edges, subtle "
         "drop shadows between paper layers, simple dot eyes. Flat lay on a soft lilac paper "
         "background, centered, no text.")

os.makedirs("static/mascot", exist_ok=True)
for i in range(1, 4):
    result = client.images.generate(model="muse-image-1.0", prompt=STYLE + " Waving hello with one paw, big smile.")
    img = result.data[0]
    path = f"static/mascot/option{i}.png"
    if getattr(img, "b64_json", None):
        with open(path, "wb") as f:
            f.write(base64.b64decode(img.b64_json))
    else:
        urllib.request.urlretrieve(img.url, path)
    print("saved", path)