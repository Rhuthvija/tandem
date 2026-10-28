from datetime import datetime, timedelta
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, HTTPException, UploadFile, File
import os, json, requests
from pydantic import BaseModel
import agent

app = FastAPI(title="Tandem")
history = []  # today's conversation

class ChatIn(BaseModel):
    message: str

@app.post("/chat")
def chat(body: ChatIn):
    global history
    reply, history = agent.chat(body.message, history)
    return {"reply": reply}
@app.post("/voice")
async def voice(audio: UploadFile = File(...)):
    wav = await audio.read()
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
    heard = " ".join(line.strip() for line in r.text.splitlines() if line.strip())
    if not heard:
        return {"heard": "", "reply": "I didn't catch that. Try again?"}
    global history
    reply, history = agent.chat(heard, history)
    return {"heard": heard, "reply": reply}

app.mount("/static", StaticFiles(directory="static"), name="static")

class Reflection(BaseModel):
    went_well: str
    got_in_way: str = ""
    mood: str

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

@app.post("/reflect")
def reflect(body: Reflection):
    d = datetime.now().strftime("%Y-%m-%d")
    tasks = [t for t in agent.mem["tasks"] if t["date"] == d]
    done_h = agent.mem.get("habit_log", {}).get(d, [])
    habits = agent.mem["habits"]
    done = [t["title"] for t in tasks if t["done"]] + [h["title"] for i, h in enumerate(habits) if i in done_h]
    missed = [t["title"] for t in tasks if not t["done"]] + [h["title"] for i, h in enumerate(habits) if i not in done_h]

    card = agent.make_day_card(d, done, missed, body.went_well, body.got_in_way, body.mood)
    os.makedirs("static/cards", exist_ok=True)
    has_art = agent.paint_card(card.get("scene", ""), f"static/cards/{d}.png")
    card.update({"date": d, "mood": body.mood, "done": len(done), "total": len(done) + len(missed),
                 "image": f"/static/cards/{d}.png" if has_art else None})
    agent.mem.setdefault("cards", {})[d] = card
    agent.save_mem()
    return {**card, "streak": reflection_streak()}

@app.get("/cards")
def all_cards():
    return sorted(agent.mem.get("cards", {}).values(), key=lambda c: c["date"], reverse=True)


@app.get("/today")
def today():
    d = datetime.now().strftime("%Y-%m-%d")
    tasks = [{"id": i, **t} for i, t in enumerate(agent.mem["tasks"]) if t["date"] == d]
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
    energy: str
    per_day: int

@app.get("/profile")
def get_profile():
    return {"profile": agent.mem.get("profile")}

@app.post("/onboarding")
def onboarding(body: Onboard):
    agent.mem["profile"] = {"name": body.name, "energy": body.energy, "per_day": body.per_day}
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