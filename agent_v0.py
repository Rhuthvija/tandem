import os, json
from datetime import date
from openai import OpenAI

client = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"])

events = []  # Tandem's calendar (just a list for now)

def add_event(title, date, kind):
    events.append({"title": title, "date": date, "kind": kind})
    return f"✅ Added: {title} on {date}"

tools = [{
    "type": "function",
    "function": {
        "name": "add_event",
        "description": "Add an event the user mentions (exam, deadline, birthday, trip) to their calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "kind": {"type": "string", "enum": ["exam", "deadline", "personal", "work", "other"]},
            },
            "required": ["title", "date", "kind"],
        },
    },
}]

today = date.today()
messages = [
    {"role": "system", "content": f"You are Tandem, a warm planning partner. Today is {today:%A, %Y-%m-%d}. When the user mentions an event, call add_event for each one."},
    {"role": "user", "content": "I have my DBMS exam this Saturday and my MLP milestone is due Friday"},
]

resp = client.chat.completions.create(model="muse-spark-1.3", messages=messages, tools=tools)

for call in resp.choices[0].message.tool_calls or []:
    print(add_event(**json.loads(call.function.arguments)))

print(events)