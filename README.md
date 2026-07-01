# Texas Hold'em Coach

A browser-based Texas Hold'em training application where you can play against configurable poker bots and review your decisions. Game state and hand history are stored locally in SQLite.

## Features

- Configurable 2–9 player tables
- Oval poker table interface with community cards in the center
- Fold, check, call, bet, raise, and custom bet sizing
- Position-aware preflop ranges and multiway decision making
- Board texture, pot odds, estimated equity, and opponent-profile analysis
- Fast hand evaluation and Monte Carlo simulations powered by `treys`
- All-in handling, automatic board runout, and showdown settlement
- Persistent stacks between hands
- Automatic stack refill when a player drops below 500 chips
- Action logs, recent hand history, and local game-state persistence

## Requirements

- Python 3.11 or newer
- Windows is recommended for the included launch scripts

## Installation

```powershell
git clone https://github.com/spanishPie88/Texas-Hold-em.git
cd Texas-Hold-em
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Running the Application

On Windows, double-click `run.bat`, then open:

<http://127.0.0.1:8000>

You can also start the server from PowerShell:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

When using the virtual environment:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If dependencies are installed in the local `.deps` directory:

```powershell
$env:PYTHONPATH="$PWD\.deps;$PWD"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Table Settings

The Settings panel allows you to configure:

- Players: table size from 2 to 9
- Starting stack: initial and refill stack size
- Small blind and big blind
- Auto runout after all-in situations

Saving settings resets the current match.

## Project Structure

```text
app/
  main.py                 FastAPI routes and game flow
  poker.py                Dealing, betting, bot strategy, and settlement
  models.py               SQLite persistence and hand history
  static/style.css        User interface styles
  templates/              Jinja2 and HTMX templates
requirements.txt          Python dependencies
run.bat                   Windows double-click launcher
run.ps1                   PowerShell launcher
```

## Local Data

The application creates `app/poker.db` at runtime. It contains the current game state and hand history and is excluded from Git by default.

## Disclaimer

This project is intended for poker education, strategy practice, and software experimentation. It does not involve real-money gaming. The bots combine heuristic strategies with Monte Carlo evaluation and are not a complete GTO solver.

