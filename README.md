# Tandem 🦦

**An AI planning partner that plans your day *with* you, so you can sleep peacefully knowing what you got done.**

Built solo for the **Meta Global AI Developer Hackathon** (Oct 26 – Nov 4, 2026).
Track: **Indie Developer** · Problem statement: **Build for Your World**
🎥 **Demo video (2 min):** [Watch on Google Drive](https://drive.google.com/file/d/1C8nsTCS8l7VxVcxaWwrCUaPKvGTDy9cS/view?usp=sharing)

🌐 **Live app:** https://tandem-a62r.onrender.com (free server, the first load can take ~50 seconds to wake up)

---

## The problem

Most planners are lists you fill in. Most AI assistants wait to be asked.
Neither notices when your plan falls apart at 3 PM, and neither helps you
understand how much you can actually get done in a day.

## What Tandem does

Tandem is an AI **agent with memory and tools** that runs your day alongside you:

| Moment | What happens |
|---|---|
| **Quick-add (text or voice)** | Say *"DBMS exam Monday and I want to start reading daily"*. It appears instantly; Tandem plans it in the background. |
| **Smart planning** | Breaks events into small sessions in your **free time only** (around your routine, wake and sleep times), hardest work in your most productive hours, a day of buffer before deadlines. Asks for the syllabus/topics before splitting exam prep. Adds undated items right away and asks for the date. |
| **Morning huddle** | Asks how your energy is, proposes a realistic plan, and **pushes back** when the day is overloaded. |
| **Check-ins** | At each task's time: *Start* (live timer) · *Push 30 min* (the agent **replans the rest of your day** to fix clashes) · *Not today* (moves to tomorrow, no guilt). |
| **Completion cards** | Ticking a task gives encouragement and a quick "how long did it take?", which helps future plans fit reality. |
| **Evening wrap-up → day card** | Tap-only reflection (what went well, mood). Tandem writes a chapter-style **day card** with a lesson for tomorrow, painted in paper cut-out style with our otter mascot. Unfinished tasks roll over. |
| **Memory** | Yesterday's lesson, your routine, habits and history shape tomorrow's plan. Weekly record (X of Y done) and a gentle reflection streak. |
| **Calendar** | Month view with events, tasks and day cards. |

No health, diet or personality advice: Tandem only plans what *you* choose to do.

## How Tandem uses Meta's models

| Model | Where | What it does |
|---|---|---|
| **Muse Spark 1.3** (`muse-spark-1.3`) | `agent.py` → `chat()`, `make_day_card()`, habit suggestions | The agent brain. Runs an **agent loop with tool calling**: `set_routine`, `add_event`, `set_event_date`, `add_tasks`, `move_task`, `update_task`, `remove_task`, `add_habit`. Also writes day cards and huddle summaries. |
| **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | `server.py` → `/voice` | Turns spoken input (recorded as WAV in the browser) into text via `POST /v1/asr/transcribe`, which the agent then plans from. |
| **Muse Image** (`muse-image-1.0`) | `agent.py` → `paint_card()`, `scripts/mascot.py` | Generated the paper cut-out otter mascot, and paints each day card using **image edit** with the mascot as the reference, so the same character appears every day. |
| **Muse Code** | Development | Used as a coding agent to build parts of the app (calendar, morning huddle, quick-add, multi-user storage, tests). |

All model calls go through the **Meta Model API** (`https://api.meta.ai/v1`).

## Architecture

```
Browser (static/index.html)          FastAPI (server.py)                 Meta Model API
 ├─ text / quick-add  ───────────▶   /quick-add, /chat ──▶ agent.py ──▶  Muse Spark (tools)
 ├─ 🎙️ voice (WAV)    ───────────▶   /voice ─────────────────────────▶  Muse Voice Transcribe
 ├─ check-ins, ticks  ───────────▶   /tasks/{id}/start|push|skip|done
 ├─ wrap-up           ───────────▶   /reflect ──▶ day card (Spark) + art (Muse Image)
 └─ X-User-Id header (private id per browser)
                                     storage: Postgres (DATABASE_URL) or local data/ files
```

## Run it locally

```bash
git clone https://github.com/Rhuthvija/tandem.git
cd tandem
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "MODEL_API_KEY=your-meta-model-api-key" > .env
uvicorn server:app --reload
```

Open http://127.0.0.1:8000 (Chrome recommended for voice and notifications).
Each browser gets its own private profile, so the first visit shows onboarding.

Run tests: `python -m unittest discover -s tests`

Deploying (Render + Neon Postgres): see [DEPLOY.md](DEPLOY.md).

## Built during the hackathon

Everything in this repository was built during the hackathon window (Oct 26 – Nov 4, 2026):
first commit on Oct 27 (first Muse Spark call), then the agent, voice, day cards,
check-ins, calendar, huddle, quick-add and multi-user storage, as the commit history shows.
`experiments/` holds the first prototypes (agent v0/v1) from day one.

## What's next

See [ROADMAP.md](ROADMAP.md).

## Author

**Rhuthvija Allavala** (solo) · [GitHub](https://github.com/Rhuthvija) · [LinkedIn](https://linkedin.com/in/rhuthvija-allavala)
