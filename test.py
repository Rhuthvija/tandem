import os
from openai import OpenAI

client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=os.environ["MODEL_API_KEY"],
)

response = client.chat.completions.create(
    model="muse-spark-1.3",
    messages=[{"role": "user", "content": "I have an exam on Saturday. Plan my next 3 days in 3 short bullet points."}],
)
print(response.choices[0].message.content)