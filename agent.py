from dotenv import load_dotenv
load_dotenv()
import os, json, base64, urllib.request
from datetime import datetime
from openai import OpenAI

client = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"])
MODEL = "muse-spark-1.3"
# Meta API reasoning_effort: minimal/low/medium/high/xhigh/max (default medium).
# "low" is the cheapest level that still plans and calls tools reliably.
REASONING_EFFORT = "low"
MEMORY = "memory.json"
EMPTY = {"profile": None, "routine": "", "events": [], "tasks": [], "habits": [], "habit_log": {}, "cards": {}, "last_nudge": None, "last_huddle": None, "last_reply": None}
def load_mem():
    base = json.loads(json.dumps(EMPTY))
    if os.path.exists(MEMORY):
        base.update(json.load(open(MEMORY)))
    for t in base["tasks"]:  # a restart means any planning job died; keep the item, drop the flag
        t.pop("planning", None)
    return base

mem = load_mem()

def save_mem():
    json.dump(mem, open(MEMORY, "w"), indent=2)

# ---------- tools Tandem can use ----------
def set_routine(description):
    mem["routine"] = description
    return "Routine saved"

def add_event(title, date, kind):
    mem["events"].append({"title": title, "date": date, "kind": kind})
    return f"📅 Event: {title} on {date}"

def set_event_date(title, date):
    for e in mem["events"]:
        if e["title"].lower() == title.lower() and e["date"] == "unknown":
            e["date"] = date
            return f"📅 {e['title']} is now on {date}"
    return f"No undated event called {title}"

def add_tasks(tasks):
    for t in tasks:
        t["done"] = False
        mem["tasks"].append(t)
    return f"📝 Added {len(tasks)} tasks"

def move_task(task_id, date, time):
    if not 0 <= task_id < len(mem["tasks"]):
        return "No such task"
    t = mem["tasks"][task_id]
    t["date"], t["time"] = date, time
    return f"↪️ Moved {t['title']} to {date} {time}"

def update_task(task_id, title):
    if not 0 <= task_id < len(mem["tasks"]):
        return "No such task"
    mem["tasks"][task_id]["title"] = title
    return f"✏️ Renamed to {title}"

def remove_task(task_id):
    if not 0 <= task_id < len(mem["tasks"]):
        return "No such task"
    t = mem["tasks"][task_id]
    t["removed"] = True
    return f"🗑️ Removed {t['title']}"

def add_habit(title, minutes, time):
    mem["habits"].append({"title": title, "minutes": minutes, "time": time})
    return f"🔁 Habit: {title} daily at {time}"

FUNCS = {"set_routine": set_routine, "add_event": add_event, "set_event_date": set_event_date, "add_tasks": add_tasks, "add_habit": add_habit, "move_task": move_task, "update_task": update_task, "remove_task": remove_task}

def fn(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}

TOOLS = [
    fn("set_routine", "Save the user's fixed weekly routine (classes, work hours, sleep).",
       {"description": {"type": "string"}}, ["description"]),
    fn("add_event", "Add a one-off event. Use date 'unknown' if the user hasn't said when yet.",
       {"title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD, or 'unknown'"},
        "kind": {"type": "string", "enum": ["exam", "deadline", "work", "personal", "errand", "other"]}},
       ["title", "date", "kind"]),
    fn("set_event_date", "Set the date of an event that was added with date 'unknown'.",
       {"title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"}},
       ["title", "date"]),
    fn("add_tasks", "Add small tasks that prepare for events.",
       {"tasks": {"type": "array", "items": {"type": "object", "properties": {
           "title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
           "time": {"type": "string", "description": "HH:MM 24h"}, "for_event": {"type": "string"},
           "size": {"type": "string", "enum": ["big", "quick"], "description": "big = focus work, quick = under ~15 min"}},
           "required": ["title", "date", "time", "for_event"]}}},
       ["tasks"]),
    fn("move_task", "Move an existing task (by its id) to a new date/time, e.g. to fix a clash or replan.",
       {"task_id": {"type": "integer"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
        "time": {"type": "string", "description": "HH:MM 24h"}},
       ["task_id", "date", "time"]),
    fn("update_task", "Rename an existing task (by its id), e.g. to turn a generic prep session into a topic-specific one.",
       {"task_id": {"type": "integer"}, "title": {"type": "string"}},
       ["task_id", "title"]),
    fn("remove_task", "Remove a task (by its id) that is no longer needed, e.g. generic prep replaced by topic-specific sessions. Ids of other tasks stay the same.",
       {"task_id": {"type": "integer"}},
       ["task_id"]),
    fn("add_habit", "Add a recurring daily habit (e.g. walking, reading).",
       {"title": {"type": "string"}, "minutes": {"type": "integer"},
        "time": {"type": "string", "description": "HH:MM 24h, in free time"}},
       ["title", "minutes", "time"]),
]

def system_prompt():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    upcoming = [{"id": i, **t} for i, t in enumerate(mem["tasks"]) if t["date"] >= today and not t.get("removed")]
    profile = mem.get("profile") or {}
    past = sorted(d for d in mem.get("cards", {}) if d < today)
    last_lesson = mem["cards"][past[-1]]["lesson"] if past else "none yet"
    per_day = profile.get("per_day", 3)
    return f"""You are Tandem, a warm, down-to-earth planning partner who plans the day WITH the user.
Now: {now:%A %Y-%m-%d %H:%M}
User: {profile.get('name', 'unknown')} · most productive in the {profile.get('energy', 'unknown')} · wakes around {profile.get('wake', 'unknown')} · sleeps around {profile.get('sleep', 'unknown')}
Fixed routine: {mem['routine'] or 'unknown'}
Events: {json.dumps(mem['events'])}
Daily habits: {json.dumps(mem['habits'])}
Planned tasks from today: {json.dumps(upcoming)}
Yesterday's lesson (from their reflection): {last_lesson}

Rules:
- Be fast: decide everything you need to do FIRST, then call ALL the tools you need in ONE single turn (several parallel tool calls at once), then write your reply. Never do one tool call per turn when independent calls can go together.
- Event with a clear date: call add_event right away.
- Prep-heavy events (exam, test, presentation, interview, project, trip): if the user hasn't said what it covers, do NOT add prep tasks yet. Ask ONE short question about the content, e.g. "Which subject? Send me the topics or syllabus and I'll split them across your free slots."
- When they answer with topics, call add_tasks with one topic (or a small group) per session (under 90 min), hardest topics in their most productive time, plus a short revision slot right before the event. If generic prep sessions already exist for that event, rename them with update_task or drop them with remove_task instead of duplicating.
- If they say "just plan it" or don't know the topics, create sensible generic sessions and say they can share topics anytime to make them specific.
- Light events (birthday, party, appointment): no prep question needed, just add_event.
- Never schedule anything before they wake up or after their bedtime.
- Only schedule in FREE time: never inside the fixed routine, never before the current time, no clashes with existing tasks or habits.
- Max {per_day} BIG tasks (focus work, ~30+ min) per day. Quick to-dos (under ~15 min, like 'buy milk', 'reply to email') don't count toward this limit, add them freely. Put the hardest tasks in their most productive time.
- Recurring things ("every day", "10k steps") are habits: call add_habit.
- Work out relative dates yourself (tomorrow, day after, this Friday).
- If a date is truly unknown, STILL call add_event with date 'unknown' right away so it shows up, then ask for the date. When they answer, call set_event_date, then plan prep like any dated event (ask what a prep-heavy event covers before adding tasks).
- If the user describes their routine, call set_routine first.
- If you pick a time the user didn't give, say so in your reply and invite them to change it.
- Small same-day to-dos with no bigger event are just tasks (add_tasks with for_event "To-do"), NOT events.
- Use their name sometimes. Reply in 1-3 short, warm sentences, like a friend, not an assistant.
- When planning, quietly apply yesterday's lesson if it's relevant.
- For deadlines, aim to finish a day early for breathing room and mention it in one line.
- When the user adds a to-do, confirm where you put it. Only sometimes, when genuinely useful, add a one-line tip on how to tackle it."""
def make_day_card(date, done, missed, went_well, got_in_way, mood):
    name = (mem.get("profile") or {}).get("name", "the user")
    prompt = f"""Write today's day card for {name}.
Date: {date}
Done: {json.dumps(done)}
Not done: {json.dumps(missed)}
What they were proud of today (tapped from their done list): {went_well}
Mood: {mood}

Return ONLY JSON with these keys:
"title": a warm, slightly playful chapter-style title for the day (max 7 words)
"lesson": one lesson for tomorrow based on what they said, in plain words (max 18 words)
"note": one encouraging line from Tandem, honest, not cheesy (max 20 words)
"scene": a cosy visual scene that captures the day, for an illustration (max 25 words)"""
    resp = client.chat.completions.create(model=MODEL, reasoning_effort=REASONING_EFFORT,
                                          messages=[{"role": "user", "content": prompt}])
    text = resp.choices[0].message.content
    return json.loads(text[text.find("{"): text.rfind("}") + 1])

def paint_card(scene, path):
    try:
        result = client.images.generate(model="muse-image-1.0", prompt=(
            "Handmade paper cut-out illustration made of layered torn construction paper, visible paper grain, "
            "soft lilac and warm orange palette, cosy and calm, no text. Scene: " + scene))
        img = result.data[0]
        if getattr(img, "b64_json", None):
            with open(path, "wb") as f:
                f.write(base64.b64decode(img.b64_json))
        else:
            urllib.request.urlretrieve(img.url, path)
        return True
    except Exception as e:
        print("Card art failed:", e)
        return False
def chat(user_text, history):
    today = datetime.now().strftime("%Y-%m-%d")
    first_today = mem["last_nudge"] != today
    system = system_prompt() + ("\nOnce you're done, ask ONE gentle question to help them remember anything else."
                                if first_today else "\nDon't ask extra follow-up questions.")
    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_text}]

    while True:  # agent loop
        resp = client.chat.completions.create(model=MODEL, reasoning_effort=REASONING_EFFORT,
                                              messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            break
        for call in msg.tool_calls:
            result = FUNCS[call.function.name](**json.loads(call.function.arguments))
            print("   ", result)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    if first_today:
        mem["last_nudge"] = today
    save_mem()
    return msg.content, messages[1:]

def print_today():
    today = datetime.now().strftime("%Y-%m-%d")
    items = [(t["time"], t["title"]) for t in mem["tasks"] if t["date"] == today and not t.get("removed")]
    items += [(h["time"], f"{h['title']} ({h['minutes']} min)") for h in mem["habits"]]
    print("\n☀️ Today's plan:")
    for time, title in sorted(items):
        print(f"  {time}  {title}")

if __name__ == "__main__":
    history = []
    print("🤝 Tandem is here. Type 'bye' to finish.\n")
    while True:
        text = input("You: ")
        if text.strip().lower() == "bye":
            break
        reply, history = chat(text, history)
        print(f"\n🤝 Tandem: {reply}\n")
    print_today()