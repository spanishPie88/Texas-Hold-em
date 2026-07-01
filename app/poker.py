import random
from typing import List, Tuple

from treys import Card, Evaluator

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_TO_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}

EVALUATOR = Evaluator()
MAX_RANK = 7462  # Treys distinct hand ranks

# Preflop ranges (conservative, 6-max flavored)
BTN_OPEN_RANGE = {
    "AA","KK","QQ","JJ","TT","99","88","77","66",
    "AKs","AQs","AJs","ATs","A9s","A8s","A7s","A6s","A5s","A4s","A3s","A2s",
    "KQs","KJs","KTs","QJs","QTs","JTs","T9s","98s","87s","76s",
    "AKo","AQo","AJo","KQo"
}
CO_OPEN_RANGE = BTN_OPEN_RANGE | {"55","44","33","22","QJo","KJo","AJo","ATo","KTo"}
MP_OPEN_RANGE = BTN_OPEN_RANGE | {"55","44","33","22","ATo","KQo"}
UTG_OPEN_RANGE = BTN_OPEN_RANGE - {"A2s","A3s","A4s","A5s","A6s","A7s","A8s","A9s"}

BB_DEFEND_RANGE = {
    "AA","KK","QQ","JJ","TT","99","88","77","66","55","44","33","22",
    "AKs","AQs","AJs","ATs","A9s","A8s","A7s","A6s","A5s","A4s","A3s","A2s",
    "KQs","KJs","KTs","QJs","QTs","JTs","J9s","T9s","98s","87s","76s","65s","54s",
    "AKo","AQo","AJo","ATo","KQo","KJo","QJo"
}


def new_deck() -> List[str]:
    return [r + s for r in RANKS for s in SUITS]


def deal(deck: List[str], n: int) -> List[str]:
    cards = deck[:n]
    del deck[:n]
    return cards


def card_value(card: str) -> int:
    return RANK_TO_VALUE[card[0]]


def _to_treys(cards: List[str]) -> List[int]:
    return [Card.new(c) for c in cards]


def evaluate_7(cards: List[str]) -> int:
    hole = cards[:2]
    board = cards[2:]
    rank = EVALUATOR.evaluate(_to_treys(board), _to_treys(hole))
    return MAX_RANK - rank


def describe_hand(cards: List[str]) -> str:
    hole = cards[:2]
    board = cards[2:]
    rank = EVALUATOR.evaluate(_to_treys(board), _to_treys(hole))
    cls = EVALUATOR.get_rank_class(rank)
    return EVALUATOR.class_to_string(cls)


def hand_key(cards: list[str]) -> str:
    v1, v2 = card_value(cards[0]), card_value(cards[1])
    r1, r2 = cards[0][0], cards[1][0]
    suited = cards[0][1] == cards[1][1]
    if v1 == v2:
        return r1 + r2
    hi_r, lo_r = (r1, r2) if v1 > v2 else (r2, r1)
    return hi_r + lo_r + ("s" if suited else "o")


def in_range(cards: list[str], range_set: set[str]) -> bool:
    return hand_key(cards) in range_set


def rank_counts(cards: list[str]) -> dict:
    counts: dict[int, int] = {}
    for c in cards:
        v = card_value(c)
        counts[v] = counts.get(v, 0) + 1
    return counts


def classify_board(board: list[str]) -> dict:
    if not board:
        return {"paired": False, "flushy": False, "straighty": False, "high": 0}
    suits = [c[1] for c in board]
    values = sorted([card_value(c) for c in board], reverse=True)
    counts = rank_counts(board)
    paired = any(v >= 2 for v in counts.values())
    flushy = max(suits.count(s) for s in set(suits)) >= 3
    unique = sorted(set(values), reverse=True)
    straighty = False
    if len(unique) >= 3:
        for i in range(len(unique) - 2):
            if unique[i] - unique[i + 2] <= 4:
                straighty = True
                break
    return {"paired": paired, "flushy": flushy, "straighty": straighty, "high": max(values)}


def hole_strength(cards: list[str]) -> float:
    v1, v2 = card_value(cards[0]), card_value(cards[1])
    suited = cards[0][1] == cards[1][1]
    pair = v1 == v2
    high = max(v1, v2)
    low = min(v1, v2)
    gap = high - low
    score = (high + low) / 30.0
    if pair:
        score += 0.45
    if suited:
        score += 0.08
    if gap == 1:
        score += 0.06
    if high >= 13:
        score += 0.06
    return min(score, 0.99)


def choose_sizing(state: dict, board: list[str], win_prob: float) -> int:
    pot = max(1, state["pot"])
    texture = classify_board(board)
    if texture["paired"]:
        base = 0.35
    elif texture["flushy"] or texture["straighty"]:
        base = 0.45
    else:
        base = 0.6

    if win_prob > 0.75:
        base = max(base, 0.75)
    elif win_prob > 0.6:
        base = max(base, 0.6)

    target = int(pot * base)
    return max(state["big_blind"], target)


def estimate_win_prob_multi(bot_cards: List[str], board: List[str], opponents: int, samples: int = 200) -> float:
    if opponents <= 0:
        return 1.0

    wins = 0
    ties = 0
    deck = [r + s for r in RANKS for s in SUITS if r + s not in bot_cards + board]
    needed = 5 - len(board)

    for _ in range(samples):
        sample_deck = deck[:]
        random.shuffle(sample_deck)
        future_board = board + sample_deck[:needed]
        cursor = needed
        opp_hands = []
        for _ in range(opponents):
            opp_hands.append(sample_deck[cursor:cursor + 2])
            cursor += 2

        bot_rank = evaluate_7(bot_cards + future_board)
        opp_ranks = [evaluate_7(h + future_board) for h in opp_hands]
        best = max(opp_ranks)
        if bot_rank > best:
            wins += 1
        elif bot_rank == best:
            ties += 1

    return (wins + ties * 0.5) / samples


def next_street(street: str) -> str:
    order = ["preflop", "flop", "turn", "river", "showdown"]
    idx = order.index(street)
    return order[min(idx + 1, len(order) - 1)]


def required_board_len(street: str) -> int:
    if street == "preflop":
        return 0
    if street == "flop":
        return 3
    if street == "turn":
        return 4
    return 5


def normalize_board(state: dict) -> None:
    needed = required_board_len(state["street"]) - len(state["board"])
    if needed > 0:
        state["board"].extend(deal(state["deck"], needed))


def active_indices(state: dict) -> list[int]:
    return [i for i, p in enumerate(state["players"]) if p["status"] == "active" and p.get("stack", 0) > 0]


def in_hand_indices(state: dict) -> list[int]:
    return [
        i
        for i, p in enumerate(state["players"])
        if p["status"] in ("active", "allin")
    ]


def next_active_index(state: dict, start: int) -> int | None:
    total = len(state["players"])
    for step in range(1, total + 1):
        idx = (start + step) % total
        if state["players"][idx]["status"] == "active" and state["players"][idx]["stack"] > 0:
            return idx
    return None


def position_labels(table_size: int) -> list[str]:
    # 6-max style labels; for smaller tables, trim from middle
    labels = ["BTN", "SB", "BB", "UTG", "MP", "CO", "HJ", "LJ", "UTG+2"]
    return labels[:table_size]


def seat_positions(state: dict) -> list[str]:
    labels = position_labels(len(state["players"]))
    positions = [""] * len(state["players"])
    btn = state["button_index"]
    for offset in range(len(state["players"])):
        idx = (btn + offset) % len(state["players"])
        positions[idx] = labels[offset]
    return positions


def reset_street(state: dict) -> None:
    state["current_bet"] = 0
    state["last_raise"] = state["big_blind"]
    state["street_contrib"] = [0 for _ in state["players"]]
    state["acted_since_raise"] = [p["id"] for p in state["players"] if p["status"] == "allin"]
    # first to act
    if state["street"] == "preflop":
        # UTG: next after BB
        state["acting_index"] = next_active_index(state, state["bb_index"]) or state["bb_index"]
    else:
        # postflop: next after button (SB)
        state["acting_index"] = next_active_index(state, state["button_index"]) or state["button_index"]


def post_blinds(state: dict) -> None:
    sb = state["small_blind"]
    bb = state["big_blind"]
    button = state["button_index"]

    sb_index = next_active_index(state, button)
    bb_index = next_active_index(state, sb_index if sb_index is not None else button)
    state["sb_index"] = sb_index
    state["bb_index"] = bb_index

    if sb_index is None or bb_index is None:
        return

    sb_amount = min(sb, state["players"][sb_index]["stack"])
    bb_amount = min(bb, state["players"][bb_index]["stack"])

    state["players"][sb_index]["stack"] -= sb_amount
    state["players"][bb_index]["stack"] -= bb_amount
    state["pot"] += sb_amount + bb_amount

    state["street_contrib"][sb_index] = sb_amount
    state["street_contrib"][bb_index] = bb_amount
    if state["players"][sb_index]["stack"] == 0:
        state["players"][sb_index]["status"] = "allin"
    if state["players"][bb_index]["stack"] == 0:
        state["players"][bb_index]["status"] = "allin"
    state["current_bet"] = bb
    state["last_raise"] = bb
    state["acted_since_raise"] = []
    # first to act preflop
    state["acting_index"] = next_active_index(state, bb_index)


def current_to_call(state: dict, idx: int) -> int:
    return max(0, state["current_bet"] - state["street_contrib"][idx])


def max_target_total(state: dict) -> int:
    # cap raises to avoid side-pots: all active players must be able to match
    totals = []
    for i, p in enumerate(state["players"]):
        if p["status"] == "active":
            totals.append(state["street_contrib"][i] + p["stack"])
    return min(totals) if totals else state["current_bet"]


def apply_call(state: dict, idx: int) -> int:
    needed = current_to_call(state, idx)
    amount = min(needed, state["players"][idx]["stack"])
    state["players"][idx]["stack"] -= amount
    state["pot"] += amount
    state["street_contrib"][idx] += amount
    if state["players"][idx]["stack"] == 0 and state["players"][idx]["status"] == "active":
        state["players"][idx]["status"] = "allin"
    return amount


def apply_bet_or_raise(state: dict, idx: int, target_total: int) -> Tuple[bool, int]:
    current = state["current_bet"]
    min_raise = state["last_raise"]
    contrib = state["street_contrib"][idx]

    cap = max_target_total(state)
    if target_total > cap:
        target_total = cap

    if target_total <= current:
        return False, 0

    raise_size = target_total - current
    if raise_size < min_raise:
        return False, 0

    amount = target_total - contrib
    amount = min(amount, state["players"][idx]["stack"])
    state["players"][idx]["stack"] -= amount
    state["pot"] += amount
    state["street_contrib"][idx] = contrib + amount
    if state["players"][idx]["stack"] == 0 and state["players"][idx]["status"] == "active":
        state["players"][idx]["status"] = "allin"

    state["last_raise"] = max(raise_size, min_raise)
    state["current_bet"] = state["street_contrib"][idx]

    return True, amount


def round_complete(state: dict) -> bool:
    in_hand = in_hand_indices(state)
    if len(in_hand) <= 1:
        return True

    # If there has been a bet/raise, the round is complete once all
    # remaining players have matched the current bet (or are all-in).
    if state.get("current_bet", 0) > 0:
        for i in in_hand:
            player = state["players"][i]
            if player["status"] == "allin":
                continue
            if current_to_call(state, i) > 0:
                return False
        return True

    for i in in_hand:
        player = state["players"][i]
        if player["status"] == "allin":
            continue
        if current_to_call(state, i) > 0:
            return False
        if player["id"] not in state["acted_since_raise"]:
            return False
    return True


def bot_preflop_decision(state: dict, idx: int) -> tuple[str, int | None]:
    cards = state["players"][idx]["cards"]
    to_call = current_to_call(state, idx)
    positions = seat_positions(state)
    pos = positions[idx]

    if to_call > 0:
        # defend ranges by position
        if pos == "BB":
            if not in_range(cards, BB_DEFEND_RANGE):
                return ("fold", None)
        else:
            # smaller defend in other spots
            if not in_range(cards, MP_OPEN_RANGE):
                return ("fold", None)

        strength = hole_strength(cards)
        if strength > 0.8 and state["players"][idx]["stack"] > to_call:
            target = state["current_bet"] + max(state["last_raise"], state["big_blind"] * 3)
            return ("raise", target)
        return ("call", None)

    # no bet: open by position (steal less)
    if pos == "BTN" and in_range(cards, BTN_OPEN_RANGE):
        target = max(state["big_blind"], int(state["pot"] * 0.8))
        return ("bet", target)
    if pos in ("CO", "MP") and in_range(cards, CO_OPEN_RANGE if pos == "CO" else MP_OPEN_RANGE):
        target = max(state["big_blind"], int(state["pot"] * 0.8))
        return ("bet", target)
    if pos == "UTG" and in_range(cards, UTG_OPEN_RANGE):
        target = max(state["big_blind"], int(state["pot"] * 0.8))
        return ("bet", target)

    return ("check", None)


def opponent_profile(state: dict) -> dict:
    opp = state.get("opponent", {})
    hands = max(opp.get("hands", 1), 1)
    vpip = opp.get("vpip", 0) / hands
    pfr = opp.get("pfr", 0) / hands
    agg = opp.get("agg", 0)
    calls = opp.get("calls", 0)
    folds = opp.get("folds", 0)
    total_actions = max(agg + calls + folds, 1)
    agg_factor = agg / total_actions
    call_factor = calls / total_actions
    fold_factor = folds / total_actions
    return {"vpip": vpip, "pfr": pfr, "agg": agg_factor, "call": call_factor, "fold": fold_factor}


def bot_action(state: dict) -> Tuple[str, int | None] | None:
    idx = state["acting_index"]
    if idx is None:
        return None
    player = state["players"][idx]
    if player["status"] != "active":
        return None
    if player.get("is_user"):
        return None
    if player["stack"] <= 0:
        player["status"] = "allin"
        return None

    to_call = current_to_call(state, idx)
    board = state["board"]
    active = active_indices(state)
    opponents = max(len(active) - 1, 1)

    if state["street"] == "preflop":
        decision, target = bot_preflop_decision(state, idx)
        if decision == "fold":
            player["status"] = "folded"
            state["last_action"] = f"{player['name']} folds"
            return ("fold", None)
        if decision == "call":
            amount = apply_call(state, idx)
            state["last_action"] = f"{player['name']} calls {amount}"
            return ("call", amount)
        if decision in ("bet", "raise"):
            ok, amount = apply_bet_or_raise(state, idx, target)
            if ok:
                word = "raises to" if to_call > 0 else "bets"
                state["last_action"] = f"{player['name']} {word} {state['current_bet']}"
                return ("raise" if to_call > 0 else "bet", amount)
            # fallback: if facing a bet, call instead of illegal check
            if to_call > 0:
                amount = apply_call(state, idx)
                state["last_action"] = f"{player['name']} calls {amount}"
                return ("call", amount)
        state["last_action"] = f"{player['name']} checks"
        return ("check", None)

    win_prob = estimate_win_prob_multi(player["cards"], board, opponents=opponents, samples=160)
    texture = classify_board(board)
    profile = opponent_profile(state)

    if to_call > 0:
        pot_odds = to_call / max(1, state["pot"] + to_call)
        noisy = win_prob + random.uniform(-0.04, 0.04)
        fold_bias = 0.08 + (0.05 if profile["agg"] > 0.45 else 0)
        if noisy < pot_odds - fold_bias:
            player["status"] = "folded"
            state["last_action"] = f"{player['name']} folds"
            return ("fold", None)

        if noisy > 0.76:
            target = state["current_bet"] + max(state["last_raise"], choose_sizing(state, board, win_prob))
            ok, amount = apply_bet_or_raise(state, idx, target)
            if ok:
                state["last_action"] = f"{player['name']} raises to {state['current_bet']}"
                return ("raise", amount)

        amount = apply_call(state, idx)
        state["last_action"] = f"{player['name']} calls {amount}"
        return ("call", amount)

    base = 0.62 if (texture["flushy"] or texture["straighty"]) else 0.52
    if profile["call"] > 0.5:
        base += 0.07
    elif profile["fold"] > 0.45:
        base -= 0.05

    if win_prob > base:
        target = choose_sizing(state, board, win_prob)
        ok, amount = apply_bet_or_raise(state, idx, target)
        if ok:
            state["last_action"] = f"{player['name']} bets {amount}"
            return ("bet", amount)

    state["last_action"] = f"{player['name']} checks"
    return ("check", None)


def maybe_advance_round(state: dict) -> None:
    if state["hand_over"]:
        return

    if round_complete(state):
        in_hand = in_hand_indices(state)
        if len(in_hand) <= 1:
            winner = in_hand[0] if in_hand else None
            if winner is not None:
                state["players"][winner]["stack"] += state["pot"]
                state["winner"] = state["players"][winner]["id"]
            state["pot"] = 0
            state["hand_over"] = True
            return

        # If nobody can act (everyone all-in), auto runout to showdown.
        if not active_indices(state) and state.get("auto_runout", True):
            while state["street"] != "river":
                state["street"] = next_street(state["street"])
                normalize_board(state)
            state["street"] = "showdown"
            state["hand_over"] = True
            return

        if state["street"] == "river":
            state["street"] = "showdown"
            state["hand_over"] = True
            return

        state["street"] = next_street(state["street"])
        normalize_board(state)
        reset_street(state)


def resolve_showdown(state: dict) -> str:
    active = [
        i
        for i in range(len(state["players"]))
        if state["players"][i]["status"] in ("active", "allin")
    ]
    if not active:
        state["pot"] = 0
        return "No contest"

    ranks = [(i, evaluate_7(state["players"][i]["cards"] + state["board"])) for i in active]
    best = max(r[1] for r in ranks)
    winners = [i for i, r in ranks if r == best]
    split = state["pot"] // len(winners)
    for i in winners:
        state["players"][i]["stack"] += split
    state["pot"] = 0
    if len(winners) == 1:
        state["winner"] = state["players"][winners[0]]["id"]
        return "Winner"
    state["winner"] = "tie"
    return "Split pot"


def new_hand_state(table_size: int, starting_stack: int, button_index: int, stacks: list[int] | None = None) -> dict:
    deck = new_deck()
    random.shuffle(deck)

    players = []
    for i in range(table_size):
        is_user = i == 0
        stack = starting_stack
        if stacks and i < len(stacks):
            stack = stacks[i]
        status = "active" if stack > 0 else "allin"
        players.append({
            "id": "user" if is_user else f"bot{i}",
            "name": "You" if is_user else f"Bot {i}",
            "is_user": is_user,
            "stack": stack,
            "cards": [],
            "status": status,
        })

    # deal cards
    for p in players:
        p["cards"] = deal(deck, 2)

    return {
        "deck": deck,
        "players": players,
        "table_size": table_size,
        "button_index": button_index,
        "board": [],
        "street": "preflop",
        "pot": 0,
        "acting_index": None,
        "street_contrib": [0 for _ in range(table_size)],
        "current_bet": 0,
        "last_raise": 0,
        "acted_since_raise": [],
        "hand_over": False,
        "winner": None,
        "last_action": "",
        "small_blind": 5,
        "big_blind": 10,
        "auto_runout": True,
        "sb_index": None,
        "bb_index": None,
    }

