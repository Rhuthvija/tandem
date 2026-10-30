from datetime import datetime, timedelta
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
import os, json, requests
from pydantic import BaseModel
import agent

app = FastAPI(title="Tandem")
history = []  # today's conversation

def trim_history(history, keep=10):
    """Keep roughly the last `keep` messages.

    Never cuts between an assistant message with tool_calls and its tool
    results: if the cut lands inside a tool block, it moves back to include
    the whole block so no orphan tool messages are sent to the model."""
    if len(history) <= keep:
        return history
    cut = len(history) - keep
    while cut > 0 and history[cut].get("role") == "tool":
        cut -= 1
    return history[cut:]

class ChatIn(BaseModel):
    message: str

@app.post("/chat")
def chat(body: ChatIn):
    global history
    history = trim_history(history)
    reply, history = agent.chat(body.message, history)
    return {"reply": reply}
def _transcribe(wav: bytes) -> str:
    r = requests.post(
        "https://api.meta.ai/v1/asr/transcribe",
        headers={"Authorization": f"Bearer {os.environ['MODEL_API_KEY']}", "Accept": "text/plain"},
        files={
            "request": (None, json.dumps({"model": "muse-voice-transcribe-1.0",
                                          "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}), "application/json"),
            "audio": ("speech.wav", wav, "audio/wav"),
        },
        timeout=60,
    )
    if r.status_code != 200:
        raise HTTPException(502, f"Transcription failed: {r.text[:200]}")
    return " ".join(line.strip() for line in r.text.splitlines() if line.strip())

@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    return {"heard": _transcribe(await audio.read())}

@app.post("/voice")
async def voice(audio: UploadFile = File(...)):
    heard = _transcribe(await audio.read())
    if not heard:
        return {"heard": "", "reply": "I didn't catch that. Try again?"}
    global history
    history = trim_history(history)
    reply, history = agent.chat(heard, history)
    return {"heard": heard, "reply": reply}

class HuddleIn(BaseModel):
    energy: str

@app.post("/huddle")
def huddle(body: HuddleIn):
    """Morning huddle: review the day and propose a realistic plan."""
    global history
    history = trim_history(history)
    reply, history = agent.chat(
        f"Morning huddle. Energy: {body.energy}. Review today's tasks (including ones "
        "carried over), habits, upcoming events and yesterday's lesson. Propose a realistic "
        "plan for today: respect the big-task limit, go lighter if energy is low. Use "
        "add_tasks/move_task for prep work for upcoming events. If today is overloaded, push "
        "back honestly and suggest what to move to another day, but don't move it without "
        "asking. Reply with a warm 2-3 sentence summary.", history)
    agent.mem["last_huddle"] = datetime.now().strftime("%Y-%m-%d")
    agent.save_mem()
    return {"reply": reply}

class QuickAddIn(BaseModel):
    text: str

def _plan_quick_add(task_id, text):
    """Background job: turn a quick-add placeholder into proper events/tasks."""
    global history
    try:
        history = trim_history(history)
        reply, history = agent.chat(
            f"(Quick add, placeholder task id {task_id}) {text}. Turn this into proper "
            "events/tasks: rename/re-time the placeholder with update_task/move_task, or "
            "remove_task it if it's just an event. Then reply in one short line.", history)
    except Exception as e:
        print("Quick-add planning failed:", e)
        reply = "Couldn't plan that one, it's on your list as-is."
    if 0 <= task_id < len(agent.mem["tasks"]):
        agent.mem["tasks"][task_id].pop("planning", None)
    agent.mem["last_reply"] = reply
    agent.save_mem()

@app.post("/quick-add")
def quick_add(body: QuickAddIn, background: BackgroundTasks):
    """Save the user's text as a placeholder instantly; plan it in the background."""
    task = {"title": body.text, "date": datetime.now().strftime("%Y-%m-%d"),
            "for_event": "To-do", "done": False, "planning": True}
    agent.mem["tasks"].append(task)
    task_id = len(agent.mem["tasks"]) - 1
    agent.save_mem()
    background.add_task(_plan_quick_add, task_id, body.text)
    return {"task": {"id": task_id, **task}}

app.mount("/static", StaticFiles(directory="static"), name="static")

class Reflection(BaseModel):
    went_well: list[str] = []
    mood: str
    carry_over: bool = True

def week_record():
    """Tasks + habits done vs planned over the last 7 days."""
    days = {str(datetime.now().date() - timedelta(days=i)) for i in range(7)}
    tasks = [t for t in agent.mem["tasks"] if t["date"] in days and not t.get("removed")]
    log = agent.mem.get("habit_log", {})
    habit_done = sum(len(v) for d, v in log.items() if d in days)
    active_days = len({t["date"] for t in tasks} | {d for d in log if d in days}) or 1
    return {"done": sum(t["done"] for t in tasks) + habit_done,
            "total": len(tasks) + len(agent.mem["habits"]) * active_days}

def reflection_streak():
    cards = agent.mem.get("cards", {})
    day, count, grace = datetime.now().date(), 0, 1
    while True:
        if str(day) in cards:
            count += 1
        elif grace:
            grace -= 1
        else:
            break
        day -= timedelta(days=1)
    return count

def _paint_and_save(date, scene):
    """Background job: generate the day-card art, then attach it to the saved card."""
    os.makedirs("static/cards", exist_ok=True)
    if agent.paint_card(scene, f"static/cards/{date}.png"):
        card = agent.mem.get("cards", {}).get(date)
        if card is not None:
            card["image"] = f"/static/cards/{date}.png"
            card["image_pending"] = False
            agent.save_mem()

@app.post("/reflect")
def reflect(body: Reflection, background: BackgroundTasks):
    d = datetime.now().strftime("%Y-%m-%d")
    tasks = [t for t in agent.mem["tasks"] if t["date"] == d and not t.get("removed")]
    done_h = agent.mem.get("habit_log", {}).get(d, [])
    habits = agent.mem["habits"]
    done = [t["title"] for t in tasks if t["done"]] + [h["title"] for i, h in enumerate(habits) if i in done_h]
    missed = [t["title"] for t in tasks if not t["done"]] + [h["title"] for i, h in enumerate(habits) if i not in done_h]

    if body.carry_over:  # unfinished tasks roll over to tomorrow
        tomorrow = str(datetime.now().date() + timedelta(days=1))
        for t in tasks:
            if not t["done"]:
                t["date"] = tomorrow
    wins = ", ".join(body.went_well) or "they didn't pick anything, be gentle"
    card = agent.make_day_card(d, done, missed, wins, "", body.mood)
    card.update({"date": d, "mood": body.mood, "done": len(done), "total": len(done) + len(missed),
                 "image": None, "image_pending": True})
    agent.mem.setdefault("cards", {})[d] = card
    agent.save_mem()
    background.add_task(_paint_and_save, d, card.get("scene", ""))
    return {**card, "streak": reflection_streak(), "week": week_record()}

@app.get("/cards")
def all_cards():
    return sorted(agent.mem.get("cards", {}).values(), key=lambda c: c["date"], reverse=True)

@app.get("/cards/{date}")
def one_card(date: str):
    card = agent.mem.get("cards", {}).get(date)
    if card is None:
        raise HTTPException(404, "No card for that date")
    return card


@app.get("/today")
def today():
    d = datetime.now().strftime("%Y-%m-%d")
    tasks = [{"id": i, **t} for i, t in enumerate(agent.mem["tasks"]) if t["date"] == d and not t.get("removed")]
    tasks.sort(key=lambda t: t.get("time", ""))
    done_habits = agent.mem.setdefault("habit_log", {}).get(d, [])
    habits = [{"id": i, **h, "done": i in done_habits} for i, h in enumerate(agent.mem["habits"])]
    events = sorted([e for e in agent.mem["events"] if e["date"] >= d], key=lambda e: e["date"])
    return {
        "date": d,
        "tasks": tasks,
        "habits": habits,
        "upcoming": events,
        "done": sum(t["done"] for t in tasks) + sum(h["done"] for h in habits),
        "total": len(tasks) + len(habits),
        "reflected": d in agent.mem.get("cards", {}),
        "huddled": agent.mem.get("last_huddle") == d,
        "last_reply": agent.mem.get("last_reply"),
    }

@app.post("/tasks/{task_id}/done")
def toggle_done(task_id: int):
    if not 0 <= task_id < len(agent.mem["tasks"]):
        raise HTTPException(404, "Task not found")
    task = agent.mem["tasks"][task_id]
    task["done"] = not task["done"]
    agent.save_mem()
    return task
@app.post("/habits/{habit_id}/done")
def toggle_habit(habit_id: int):
    if not 0 <= habit_id < len(agent.mem["habits"]):
        raise HTTPException(404, "Habit not found")
    d = datetime.now().strftime("%Y-%m-%d")
    log = agent.mem.setdefault("habit_log", {}).setdefault(d, [])
    if habit_id in log:
        log.remove(habit_id)
    else:
        log.append(habit_id)
    agent.save_mem()
    return {"done": habit_id in log}

def _task(task_id):
    if not 0 <= task_id < len(agent.mem["tasks"]):
        raise HTTPException(404, "Task not found")
    return agent.mem["tasks"][task_id]

@app.post("/tasks/{task_id}/start")
def start_task(task_id: int):
    t = _task(task_id)
    t["started_at"] = datetime.now().isoformat(timespec="minutes")
    agent.save_mem()
    return t

class Push(BaseModel):
    minutes: int = 30

@app.post("/tasks/{task_id}/push")
def push_task(task_id: int, body: Push):
    """Push a task later, then let Tandem fix any clashes in the rest of the day."""
    global history
    t = _task(task_id)
    when = datetime.strptime(f"{t['date']} {t.get('time') or '12:00'}", "%Y-%m-%d %H:%M")
    when = max(when, datetime.now()) + timedelta(minutes=body.minutes)
    t["date"], t["time"] = when.strftime("%Y-%m-%d"), when.strftime("%H:%M")
    agent.save_mem()
    history = trim_history(history)
    reply, history = agent.chat(
        f"(Check-in) I just pushed '{t['title']}' to {t['time']} on {t['date']}. "
        "If that clashes with anything else today, quietly fix it with move_task. "
        "Then tell me in one short, friendly line what changed.", history)
    return {"task": t, "reply": reply}

@app.post("/tasks/{task_id}/skip")
def skip_task(task_id: int):
    t = _task(task_id)
    t["date"] = str((datetime.now() + timedelta(days=1)).date())
    agent.save_mem()
    return t

class Feedback(BaseModel):
    took: str  # quicker / as_planned / longer

@app.post("/tasks/{task_id}/feedback")
def task_feedback(task_id: int, body: Feedback):
    if not 0 <= task_id < len(agent.mem["tasks"]):
        raise HTTPException(404, "Task not found")
    agent.mem["tasks"][task_id]["took"] = body.took
    agent.save_mem()
    return {"ok": True}
from fastapi.responses import FileResponse
import json

class Onboard(BaseModel):
    name: str
    routine: str
    wake: str = "07:00"
    sleep: str = "23:00"
    energy: str
    per_day: int

@app.get("/profile")
def get_profile():
    return {"profile": agent.mem.get("profile")}

@app.post("/onboarding")
def onboarding(body: Onboard):
    agent.mem["profile"] = {"name": body.name, "wake": body.wake, "sleep": body.sleep,
                            "energy": body.energy, "per_day": body.per_day}
    agent.mem["routine"] = body.routine
    agent.save_mem()
    return {"ok": True}

@app.post("/reset")
def reset():  # wipes everything, handy before recording the demo
    global history
    agent.mem.clear()
    agent.mem.update(json.loads(json.dumps(agent.EMPTY)))
    agent.save_mem()
    history = []
    return {"ok": True}
@app.get("/")
def home():
    return FileResponse("static/index.html")