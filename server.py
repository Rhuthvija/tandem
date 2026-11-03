from datetime import datetime, timedelta
from calendar import monthrange
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Depends, Request
from fastapi.responses import Response
import os, json, re, uuid, requests
from pydantic import BaseModel
import agent


@asynccontextmanager
async def lifespan(app):
    agent.init_db()
    yield


app = FastAPI(title="Tandem", lifespan=lifespan)
histories = {}  # user_id -> today's conversation (in-memory, like before)


async def current_user(request: Request):
    """Bind the request to its user's memory. <img> tags can't set headers,
    so the card-image URL carries the id as ?user_id= instead."""
    raw = request.headers.get("X-User-Id") or request.query_params.get("user_id")
    try:
        user_id = str(uuid.UUID(raw or ""))
    except ValueError:
        raise HTTPException(400, "Missing or invalid X-User-Id")
    agent.bind_user(user_id, agent.load_user(user_id))
    return user_id

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
def chat(body: ChatIn, user_id: str = Depends(current_user)):
    history = trim_history(histories.get(user_id, []))
    reply, histories[user_id] = agent.chat(body.message, history)
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
async def transcribe(audio: UploadFile = File(...), user_id: str = Depends(current_user)):
    return {"heard": _transcribe(await audio.read())}

@app.post("/voice")
async def voice(audio: UploadFile = File(...), user_id: str = Depends(current_user)):
    heard = _transcribe(await audio.read())
    if not heard:
        return {"heard": "", "reply": "I didn't catch that. Try again?"}
    history = trim_history(histories.get(user_id, []))
    reply, histories[user_id] = agent.chat(heard, history)
    return {"heard": heard, "reply": reply}

class HuddleIn(BaseModel):
    energy: str

@app.post("/huddle")
def huddle(body: HuddleIn, user_id: str = Depends(current_user)):
    """Morning huddle: review the day and propose a realistic plan."""
    history = trim_history(histories.get(user_id, []))
    reply, histories[user_id] = agent.chat(
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

def _plan_quick_add(task_id, text, user_id):
    """Background job: turn a quick-add placeholder into proper events/tasks."""
    with agent.user_context(user_id):
        try:
            history = trim_history(histories.get(user_id, []))
            reply, histories[user_id] = agent.chat(
                f"(Quick add, placeholder task id {task_id}) {text}. Turn this into proper "
                "events/tasks: rename/re-time the placeholder with update_task/move_task, or "
                "remove_task it if it's just an event. For a daily habit, remove_task the "
                "placeholder and call add_habit instead. Then reply in one short line.", history)
        except Exception as e:
            print("Quick-add planning failed:", e)
            reply = "Couldn't plan that one, it's on your list as-is."
        tasks = agent.mem["tasks"]
        if 0 <= task_id < len(tasks):
            tasks[task_id].pop("planning", None)
        agent.mem["last_reply"] = reply
        agent.save_mem()

@app.post("/quick-add")
def quick_add(body: QuickAddIn, background: BackgroundTasks, user_id: str = Depends(current_user)):
    """Save the user's text as a placeholder instantly; plan it in the background."""
    task = {"title": body.text, "date": datetime.now().strftime("%Y-%m-%d"),
            "for_event": "To-do", "done": False, "planning": True}
    agent.mem["tasks"].append(task)
    task_id = len(agent.mem["tasks"]) - 1
    agent.save_mem()
    background.add_task(_plan_quick_add, task_id, body.text, user_id)
    return {"task": {"id": task_id, **task}}

HABIT_SUGGESTIONS = [
    "🚶 Take a 10-minute walk",
    "📖 Read 10 pages",
    "🧘 Meditate for 5 minutes",
    "💧 Drink a glass of water",
    "✍️ Journal one line",
    "📵 No phone for the first 30 minutes",
    "🧹 Tidy one surface",
    "🙆 Stretch for 5 minutes",
]

@app.get("/habit-suggestions")
def habit_suggestions(user_id: str = Depends(current_user)):
    """Curated habit ideas, skipping ones the user already has."""
    have = [(h.get("title") or "").lower() for h in agent.mem["habits"]]
    fresh = [s for s in HABIT_SUGGESTIONS
             if not any(h and (h in s.lower() or s.lower() in h) for h in have)]
    return {"suggestions": fresh or HABIT_SUGGESTIONS}

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

def _paint_and_save(date, scene, user_id):
    """Background job: paint the day-card art, then attach it to the saved card."""
    with agent.user_context(user_id):
        card = agent.mem.get("cards", {}).get(date)
        if card is None:
            return
        png = agent.paint_card(scene)
        if png is not None:
            agent.save_card_image(user_id, date, png)
            card["image"] = f"/cards/{date}/image?user_id={user_id}"
        card["image_pending"] = False
        agent.save_mem()

@app.post("/reflect")
def reflect(body: Reflection, background: BackgroundTasks, user_id: str = Depends(current_user)):
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
    background.add_task(_paint_and_save, d, card.get("scene", ""), user_id)
    return {**card, "streak": reflection_streak(), "week": week_record()}

@app.get("/cards")
def all_cards(user_id: str = Depends(current_user)):
    return sorted(agent.mem.get("cards", {}).values(), key=lambda c: c["date"], reverse=True)

@app.get("/cards/{date}")
def one_card(date: str, user_id: str = Depends(current_user)):
    card = agent.mem.get("cards", {}).get(date)
    if card is None:
        raise HTTPException(404, "No card for that date")
    return card

def _media_type(png: bytes):
    if png[:4] == b"\x89PNG":
        return "image/png"
    if png[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if png[:4] == b"RIFF" and png[8:12] == b"WEBP":
        return "image/webp"
    if png[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"

@app.get("/cards/{date}/image")
def card_image(date: str, user_id: str = Depends(current_user)):
    png = agent.load_card_image(user_id, date)
    if png is None:
        raise HTTPException(404, "No art for that date")
    return Response(content=png, media_type=_media_type(png))

@app.get("/calendar")
def calendar_view(month: str, user_id: str = Depends(current_user)):
    """Per-day events, tasks and day-card flags for one month (YYYY-MM)."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(400, "month must be YYYY-MM")
    y, m = int(month[:4]), int(month[5:7])
    cards = agent.mem.get("cards", {})
    days = {}
    for day in range(1, monthrange(y, m)[1] + 1):
        d = f"{y}-{m:02d}-{day:02d}"
        days[d] = {
            "events": [e for e in agent.mem["events"] if e["date"] == d],
            "tasks": [{"id": i, **t} for i, t in enumerate(agent.mem["tasks"])
                      if t["date"] == d and not t.get("removed")],
            "has_card": d in cards,
        }
    return {"month": month, "days": days}


@app.get("/today")
def today(user_id: str = Depends(current_user)):
    d = datetime.now().strftime("%Y-%m-%d")
    tasks = [{"id": i, **t} for i, t in enumerate(agent.mem["tasks"]) if t["date"] == d and not t.get("removed")]
    tasks.sort(key=lambda t: t.get("time", ""))
    done_habits = agent.mem.get("habit_log", {}).get(d, [])
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
def toggle_done(task_id: int, user_id: str = Depends(current_user)):
    if not 0 <= task_id < len(agent.mem["tasks"]):
        raise HTTPException(404, "Task not found")
    task = agent.mem["tasks"][task_id]
    task["done"] = not task["done"]
    agent.save_mem()
    return task
@app.post("/habits/{habit_id}/done")
def toggle_habit(habit_id: int, user_id: str = Depends(current_user)):
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
def start_task(task_id: int, user_id: str = Depends(current_user)):
    t = _task(task_id)
    t["started_at"] = datetime.now().isoformat(timespec="minutes")
    agent.save_mem()
    return t

class Push(BaseModel):
    minutes: int = 30

@app.post("/tasks/{task_id}/push")
def push_task(task_id: int, body: Push, user_id: str = Depends(current_user)):
    """Push a task later, then let Tandem fix any clashes in the rest of the day."""
    t = _task(task_id)
    when = datetime.strptime(f"{t['date']} {t.get('time') or '12:00'}", "%Y-%m-%d %H:%M")
    when = max(when, datetime.now()) + timedelta(minutes=body.minutes)
    t["date"], t["time"] = when.strftime("%Y-%m-%d"), when.strftime("%H:%M")
    agent.save_mem()
    history = trim_history(histories.get(user_id, []))
    reply, histories[user_id] = agent.chat(
        f"(Check-in) I just pushed '{t['title']}' to {t['time']} on {t['date']}. "
        "If that clashes with anything else today, quietly fix it with move_task. "
        "Then tell me in one short, friendly line what changed.", history)
    return {"task": t, "reply": reply}

@app.post("/tasks/{task_id}/skip")
def skip_task(task_id: int, user_id: str = Depends(current_user)):
    t = _task(task_id)
    t["date"] = str((datetime.now() + timedelta(days=1)).date())
    agent.save_mem()
    return t

class Feedback(BaseModel):
    took: str  # quicker / as_planned / longer

@app.post("/tasks/{task_id}/feedback")
def task_feedback(task_id: int, body: Feedback, user_id: str = Depends(current_user)):
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
    days: str = "other"
    wake: str = "07:00"
    sleep: str = "23:00"
    energy: str
    per_day: int

@app.get("/profile")
def get_profile(user_id: str = Depends(current_user)):
    return {"profile": agent.mem.get("profile")}

@app.post("/onboarding")
def onboarding(body: Onboard, user_id: str = Depends(current_user)):
    agent.mem["profile"] = {"name": body.name, "days": body.days, "wake": body.wake, "sleep": body.sleep,
                            "energy": body.energy, "per_day": body.per_day}
    agent.mem["routine"] = body.routine
    agent.save_mem()
    return {"ok": True}

@app.post("/reset")
def reset(user_id: str = Depends(current_user)):  # wipes this user's everything
    agent.mem.clear()
    agent.mem.update(json.loads(json.dumps(agent.EMPTY)))
    agent.save_mem()
    histories.pop(user_id, None)
    return {"ok": True}
@app.get("/")
def home():
    return FileResponse("static/index.html")