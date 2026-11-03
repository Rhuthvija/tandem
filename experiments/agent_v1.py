import os, json
from datetime import date
from openai import OpenAI

client = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"])
MEMORY = "memory.json"

mem = json.load(open(MEMORY)) if os.path.exists(MEMORY) else {"events": [], "tasks": []}

def add_event(title, date, kind):
    mem["events"].append({"title": title, "date": date, "kind": kind})
    return f"📅 Event: {title} on {date}"

def add_tasks(tasks):
    for t in tasks:
        t["done"] = False
        mem["tasks"].append(t)
    return f"📝 Added {len(tasks)} tasks"

tools = [
    {"type": "function", "function": {
        "name": "add_event",
        "description": "Add an event the user mentions to their calendar.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "kind": {"type": "string", "enum": ["exam", "deadline", "work", "personal", "other"]}},
            "required": ["title", "date", "kind"]}}},
    {"type": "function", "function": {
        "name": "add_tasks",
        "description": "Break events into small, doable tasks spread across the days before them.",
        "parameters": {"type": "object", "properties": {
            "tasks": {"type": "array", "items": {"type": "object", "properties": {
                "title": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "HH:MM, 24h"},
                "for_event": {"type": "string"}},
                "required": ["title", "date", "for_event"]}}},
            "required": ["tasks"]}}},
]

today = date.today()
system = f"""You are Tandem, a warm planning partner. Today is {today:%A, %Y-%m-%d}.
Existing events: {json.dumps(mem['events'])}
When the user mentions events: call add_event for each, then call add_tasks to break each one
into small tasks (under 90 min) spread from today until the event. Max 3 tasks per day. Be realistic."""

first_today = mem.get("last_nudge") != str(today)
system += "\nAfter planning, reply in 1-2 warm sentences."
system += (" Then ask ONE gentle question to help them remember anything else coming up."
           if first_today else " Don't ask follow-up questions.")

messages = [{"role": "system", "content": system},
            {"role": "user", "content": input("Tell Tandem: ")}]
funcs = {"add_event": add_event, "add_tasks": add_tasks}

while True:  # the agent loop
    resp = client.chat.completions.create(model="muse-spark-1.3", messages=messages, tools=tools)
    msg = resp.choices[0].message
    messages.append(msg.model_dump(exclude_none=True))
    if not msg.tool_calls:
        break
    for call in msg.tool_calls:
        result = funcs[call.function.name](**json.loads(call.function.arguments))
        print(result)
        messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

print("\n🤝 Tandem:", msg.content)
if first_today:
    mem["last_nudge"] = str(today)
json.dump(mem, open(MEMORY, "w"), indent=2)

print("\n☀️ Today's plan:")
for t in mem["tasks"]:
    if t["date"] == str(today):
        print(f"  {t.get('time', '--:--')}  {t['title']}  ({t['for_event']})")