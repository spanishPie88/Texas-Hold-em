from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import json
from collections import defaultdict

from app import poker
from app import models

app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

DEFAULT_SETTINGS = {
    "starting_stack": 1000,
    "small_blind": 5,
    "big_blind": 10,
    "auto_runout": True,
    "table_size": 6,
}


@app.on_event("startup")
def startup() -> None:
    models.init_db()


def load_settings() -> dict:
    raw = models.get_meta("settings")
    if not raw:
        return DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(raw)
    except Exception:
        return DEFAULT_SETTINGS.copy()
    merged = DEFAULT_SETTINGS.copy()
    merged.update({k: data.get(k, merged[k]) for k in merged})
    return merged


def save_settings(data: dict) -> dict:
    cleaned = {
        "starting_stack": int(data.get("starting_stack", DEFAULT_SETTINGS["starting_stack"])),
        "small_blind": int(data.get("small_blind", DEFAULT_SETTINGS["small_blind"])),
        "big_blind": int(data.get("big_blind", DEFAULT_SETTINGS["big_blind"])),
        "auto_runout": bool(data.get("auto_runout", False)),
        "table_size": int(data.get("table_size", DEFAULT_SETTINGS["table_size"])),
    }
    if cleaned["small_blind"] <= 0:
        cleaned["small_blind"] = DEFAULT_SETTINGS["small_blind"]
    if cleaned["big_blind"] <= cleaned["small_blind"]:
        cleaned["big_blind"] = max(cleaned["small_blind"] * 2, DEFAULT_SETTINGS["big_blind"])
    if cleaned["starting_stack"] <= cleaned["big_blind"] * 5:
        cleaned["starting_stack"] = DEFAULT_SETTINGS["starting_stack"]
    if cleaned["table_size"] < 2:
        cleaned["table_size"] = 2
    if cleaned["table_size"] > 9:
        cleaned["table_size"] = 9
    models.set_meta("settings", json.dumps(cleaned))
    return cleaned


def build_new_match(settings: dict, button_index: int = 0, stacks: list[int] | None = None) -> dict:
    state = poker.new_hand_state(
        settings["table_size"],
        settings["starting_stack"],
        button_index=button_index,
        stacks=stacks,
    )
    state["small_blind"] = settings["small_blind"]
    state["big_blind"] = settings["big_blind"]
    state["last_raise"] = settings["big_blind"]
    state["auto_runout"] = settings["auto_runout"]
    state["opponent"] = {"hands": 1, "vpip": 0, "pfr": 0, "agg": 0, "calls": 0, "folds": 0}
    poker.post_blinds(state)
    return state


def upgrade_state(state: dict) -> dict:
    settings = load_settings()
    if "players" not in state:
        return build_new_match(settings, button_index=0)

    # If table size changed or state is incompatible, rebuild cleanly.
    if len(state.get("players", [])) != settings["table_size"]:
        return build_new_match(settings, button_index=0)
    if len(state.get("street_contrib", [])) != settings["table_size"]:
        return build_new_match(settings, button_index=0)

    state["small_blind"] = settings["small_blind"]
    state["big_blind"] = settings["big_blind"]
    state["auto_runout"] = settings["auto_runout"]
    state["table_size"] = settings["table_size"]
    state.setdefault("opponent", {"hands": 1, "vpip": 0, "pfr": 0, "agg": 0, "calls": 0, "folds": 0})

    # sanitize statuses for zero stacks
    for p in state.get("players", []):
        if p.get("stack", 0) <= 0 and p.get("status") == "active":
            p["status"] = "allin"
    if "acted_since_raise" in state:
        for p in state.get("players", []):
            if p.get("status") == "allin" and p.get("id") not in state["acted_since_raise"]:
                state["acted_since_raise"].append(p.get("id"))

    # fix acting_index if pointing to non-active player
    if state.get("acting_index") is not None:
        idx = state["acting_index"]
        if state["players"][idx].get("status") != "active":
            state["acting_index"] = poker.next_active_index(state, idx)
    if state.get("street") == "preflop" and state.get("current_bet", 0) == 0:
        poker.post_blinds(state)
    poker.normalize_board(state)
    if state.get("street") == "showdown":
        state["hand_over"] = True
    return state


def ensure_state() -> dict:
    state = models.load_state()
    if state is not None:
        return upgrade_state(state)
    settings = load_settings()
    hand_id = models.create_hand()
    state = build_new_match(settings, button_index=0)
    state["hand_id"] = hand_id
    state["message"] = ""
    models.save_state(state)
    return state


def update_opponent_stats(state: dict, action: str, amount: int | None) -> None:
    opp = state.setdefault("opponent", {"hands": 0, "vpip": 0, "pfr": 0, "agg": 0, "calls": 0, "folds": 0})
    street = state.get("street", "preflop")

    if street == "preflop":
        if action in ("call", "bet", "raise"):
            opp["vpip"] += 1
        if action in ("bet", "raise"):
            opp["pfr"] += 1

    if action in ("bet", "raise"):
        opp["agg"] += 1
    elif action in ("call", "check"):
        opp["calls"] += 1
    elif action == "fold":
        opp["folds"] += 1


def user_index(state: dict) -> int:
    for i, p in enumerate(state["players"]):
        if p.get("is_user"):
            return i
    return 0


def apply_user_action(state: dict, action: str, amount: int | None) -> str:
    if state["hand_over"]:
        return "Hand over. Start a new hand."

    idx = user_index(state)
    if state.get("acting_index") != idx:
        return "Wait for your turn."

    to_call = poker.current_to_call(state, idx)

    if action == "fold":
        state["players"][idx]["status"] = "folded"
        models.add_action(state["hand_id"], state["street"], "user", "fold", None)
        update_opponent_stats(state, "fold", None)
        state["last_action"] = "You fold"
        return "You folded."

    if action == "check":
        if to_call > 0:
            return "You cannot check; there is a bet to call."
        models.add_action(state["hand_id"], state["street"], "user", "check", None)
        update_opponent_stats(state, "check", None)
        state["acted_since_raise"].append("user")
        state["last_action"] = "You check"
        return "Check."

    if action == "call":
        if to_call == 0:
            models.add_action(state["hand_id"], state["street"], "user", "check", None)
            update_opponent_stats(state, "check", None)
            state["acted_since_raise"].append("user")
            state["last_action"] = "You check"
            return "Check."
        amount_put = poker.apply_call(state, idx)
        models.add_action(state["hand_id"], state["street"], "user", "call", amount_put)
        update_opponent_stats(state, "call", amount_put)
        state["acted_since_raise"].append("user")
        state["last_action"] = f"You call {amount_put}"
        return "Call."

    if action in ("bet", "raise"):
        if action == "bet" and to_call > 0:
            return "You cannot bet; you must call, raise, or fold."
        if action == "raise" and to_call == 0:
            return "You cannot raise; no bet to raise."

        if amount is None:
            if to_call > 0:
                target = state["current_bet"] + state["last_raise"]
            else:
                target = max(state["big_blind"], int(state["pot"] * 0.5))
        else:
            target = amount

        ok, amount_put = poker.apply_bet_or_raise(state, idx, target)
        if not ok:
            return "Raise size too small."

        models.add_action(state["hand_id"], state["street"], "user", action, amount_put)
        update_opponent_stats(state, action, amount_put)
        state["acted_since_raise"] = ["user"]
        verb = "raises to" if to_call > 0 else "bets"
        state["last_action"] = f"You {verb} {state['current_bet']}"
        return "Bet/raise."

    return "Unknown action."


def advance_turn(state: dict) -> None:
    idx = state.get("acting_index")
    if idx is None:
        return
    next_idx = poker.next_active_index(state, idx)
    state["acting_index"] = next_idx


def force_progress(state: dict) -> None:
    # Defensive progression: if all remaining players have matched the bet,
    # advance the street even if acted_since_raise is inconsistent.
    for _ in range(6):
        if state["hand_over"]:
            return
        if state.get("current_bet", 0) > 0:
            in_hand = poker.in_hand_indices(state)
            all_matched = True
            for i in in_hand:
                player = state["players"][i]
                if player.get("status") == "allin":
                    continue
                if poker.current_to_call(state, i) > 0:
                    all_matched = False
                    break
            if all_matched:
                poker.maybe_advance_round(state)
                continue
        return


def run_bot_and_advance(state: dict) -> str | None:
    last_bot_action = None
    safety = 0

    if state.get("acting_index") is None and not state["hand_over"]:
        state["acting_index"] = poker.next_active_index(state, state.get("button_index", 0) or 0)

    while not state["hand_over"] and state.get("acting_index") is not None and safety < 200:
        safety += 1
        idx = state["acting_index"]
        player = state["players"][idx]
        if player.get("is_user"):
            if player.get("status") != "active":
                advance_turn(state)
                continue
            break

        result = poker.bot_action(state)
        if result:
            action, amount = result
            models.add_action(state["hand_id"], state["street"], player["id"], action, amount)
            if action in ("bet", "raise"):
                state["acted_since_raise"] = [player["id"]]
            else:
                state["acted_since_raise"].append(player["id"])
            last_bot_action = state.get("last_action")

        poker.maybe_advance_round(state)
        if state["hand_over"]:
            break

        if state.get("acting_index") == idx:
            advance_turn(state)

    if state.get("acting_index") is not None and state.get("acting_index") != user_index(state):
        advance_turn(state)

    # If user is folded/all-in, finish the hand in the same request.
    user_idx = user_index(state)
    if state["players"][user_idx].get("status") != "active" and not state["hand_over"]:
        # try advancing rounds a few times
        for _ in range(8):
            poker.maybe_advance_round(state)
            if state["hand_over"]:
                break
            # let bots act again if needed
            if state.get("acting_index") is None:
                state["acting_index"] = poker.next_active_index(state, state.get("button_index", 0) or 0)
            safety += 1
            if safety >= 220:
                break
            idx = state.get("acting_index")
            if idx is None:
                break
            player = state["players"][idx]
            if not player.get("is_user"):
                result = poker.bot_action(state)
                if result:
                    action, amount = result
                    models.add_action(state["hand_id"], state["street"], player["id"], action, amount)
                    if action in ("bet", "raise"):
                        state["acted_since_raise"] = [player["id"]]
                    else:
                        state["acted_since_raise"].append(player["id"])
                poker.maybe_advance_round(state)

        if not state["hand_over"] and state.get("auto_runout", True):
            # hard stop: run out remaining streets to showdown
            while state["street"] != "river":
                state["street"] = poker.next_street(state["street"])
                poker.normalize_board(state)
            state["street"] = "showdown"
            state["hand_over"] = True

    force_progress(state)

    if state["street"] == "showdown" and state["hand_over"]:
        poker.resolve_showdown(state)
        models.finish_hand(state["hand_id"], state, state.get("last_action", ""))

    return last_bot_action


def finalize_hand(state: dict, reason: str) -> None:
    if reason == "showdown":
        result = poker.resolve_showdown(state)
    else:
        result = reason
    state["result"] = result
    models.finish_hand(state["hand_id"], state, state.get("last_action", ""))


def build_action_log(state: dict):
    actions = models.get_actions(state.get("hand_id", 0)) if state.get("hand_id") else []
    grouped = []
    by_street = defaultdict(list)
    for item in actions:
        by_street[item["street"]].append(item)
    for street in ("preflop", "flop", "turn", "river"):
        if street in by_street:
            entries = []
            for act in by_street[street]:
                actor = "You" if act["actor"] == "user" else act["actor"].replace("bot", "Bot ")
                if act["amount"] is None:
                    entries.append(f"{actor} {act['action']}")
                else:
                    verb = "raises" if act["action"] == "raise" else act["action"]
                    entries.append(f"{actor} {verb} {act['amount']}")
            grouped.append({"street": street, "entries": entries})
    return grouped


def build_last_hand():
    last_hand = models.get_last_finished_hand()
    if last_hand and last_hand.get("board"):
        last_hand["user_hand_name"] = poker.describe_hand(last_hand["user_cards"] + last_hand["board"])
    return last_hand


def render_state(request: Request, state: dict):
    hands = models.get_recent_hands(20)
    idx = user_index(state)
    state["to_call"] = poker.current_to_call(state, idx) if state["players"][idx].get("status") == "active" else 0
    state["positions"] = poker.seat_positions(state)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "state": state,
            "hands": hands,
            "settings": load_settings(),
            "action_log": build_action_log(state),
            "last_hand": build_last_hand(),
        },
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    state = ensure_state()
    bot_msg = run_bot_and_advance(state)
    if bot_msg:
        state["message"] = bot_msg
    models.save_state(state)
    return render_state(request, state)


@app.post("/action", response_class=HTMLResponse)
def action(request: Request, action: str = Form(...), amount: int | None = Form(None)):
    state = ensure_state()
    apply_user_action(state, action, amount)
    advance_turn(state)
    poker.maybe_advance_round(state)
    bot_msg = run_bot_and_advance(state)
    force_progress(state)
    state["message"] = bot_msg or ""
    models.save_state(state)

    hands = models.get_recent_hands(20)
    idx = user_index(state)
    state["to_call"] = poker.current_to_call(state, idx) if state["players"][idx].get("status") == "active" else 0
    state["positions"] = poker.seat_positions(state)
    return templates.TemplateResponse(
        "partials/table.html",
        {
            "request": request,
            "state": state,
            "hands": hands,
            "settings": load_settings(),
            "action_log": build_action_log(state),
            "last_hand": build_last_hand(),
        },
    )


@app.post("/new-hand", response_class=HTMLResponse)
def new_hand(request: Request):
    state = ensure_state()
    if not state["hand_over"]:
        state["message"] = "Finish the current hand first."
    else:
        settings = load_settings()
        button = (state.get("button_index", 0) + 1) % settings["table_size"]
        hand_id = models.create_hand()
        stacks = []
        for i in range(settings["table_size"]):
            if i < len(state.get("players", [])):
                stack = state["players"][i].get("stack", settings["starting_stack"])
            else:
                stack = settings["starting_stack"]
            if stack < 500:
                stack = settings["starting_stack"]
            stacks.append(stack)
        state = build_new_match(settings, button_index=button, stacks=stacks)
        state["hand_id"] = hand_id
        state["message"] = "New hand started."

    bot_msg = run_bot_and_advance(state)
    if bot_msg:
        state["message"] = bot_msg
    models.save_state(state)

    hands = models.get_recent_hands(20)
    idx = user_index(state)
    state["to_call"] = poker.current_to_call(state, idx) if state["players"][idx].get("status") == "active" else 0
    state["positions"] = poker.seat_positions(state)
    return templates.TemplateResponse(
        "partials/table.html",
        {
            "request": request,
            "state": state,
            "hands": hands,
            "settings": load_settings(),
            "action_log": build_action_log(state),
            "last_hand": build_last_hand(),
        },
    )


@app.post("/reset", response_class=HTMLResponse)
def reset(request: Request):
    settings = load_settings()
    hand_id = models.create_hand()
    state = build_new_match(settings, button_index=0)
    state["hand_id"] = hand_id
    state["message"] = "Match reset."
    models.save_state(state)

    hands = models.get_recent_hands(20)
    idx = user_index(state)
    state["to_call"] = poker.current_to_call(state, idx) if state["players"][idx].get("status") == "active" else 0
    state["positions"] = poker.seat_positions(state)
    return templates.TemplateResponse(
        "partials/table.html",
        {
            "request": request,
            "state": state,
            "hands": hands,
            "settings": load_settings(),
            "action_log": build_action_log(state),
            "last_hand": build_last_hand(),
        },
    )


@app.post("/settings", response_class=HTMLResponse)
def settings(
    request: Request,
    starting_stack: int = Form(...),
    small_blind: int = Form(...),
    big_blind: int = Form(...),
    table_size: int = Form(...),
    auto_runout: str | None = Form(None),
):
    data = {
        "starting_stack": starting_stack,
        "small_blind": small_blind,
        "big_blind": big_blind,
        "table_size": table_size,
        "auto_runout": auto_runout is not None,
    }
    save_settings(data)
    return reset(request)

