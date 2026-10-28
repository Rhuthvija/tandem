from datetime import datetime
from fastapi import FastAPI, HTTPException
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

@app.get("/today")
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