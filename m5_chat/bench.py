"""
M5 — pomiar ticka fragmentu czatu (M5-02):  python -m m5_chat.bench [liczba_wiadomości]

Baza w RAM z mockami + N wiadomości w pokoju jazzowym. Pisze 5 osób na zmianę, więc każda
wiadomość to osobna grupa (najgorszy przypadek). W trakcie pomiaru dochodzą nowe wiadomości.
Tick = czas funkcji fragmentu (polling + rysowanie), mierzony w chat_view (`m5_tick_ms`).
Na żywo to samo widać w sandboxie z `?m5_debug=1`.
"""

from __future__ import annotations

import statistics
import sys
from datetime import datetime, timedelta

from streamlit.testing.v1 import AppTest

import shared.storage as storage_module
from shared.models import ChatMessage, event_room_id

ROOM = event_room_id("e_jazz_alchemia")
AUTHORS = ["u_ola", "u_kuba", "u_bartek", "u_natalia", "u_zosia"]
TICK_BUDGET_MS = 30


def _app() -> None:
    from m5_chat.chat_view import render_chat_room
    from shared import state
    from shared.models import event_room_id
    from shared.storage import get_storage

    storage = get_storage()
    state.init()
    render_chat_room(storage, storage.get_user("u_ola"), event_room_id("e_jazz_alchemia"))


def main(n_messages: int = 500, runs: int = 20) -> None:
    store = storage_module.Storage(":memory:")
    first = datetime.now() - timedelta(minutes=n_messages)
    for i in range(n_messages):
        store.add_message(ChatMessage(
            room_id=ROOM, user_id=AUTHORS[i % len(AUTHORS)], text=f"wiadomość testowa nr {i}",
            created_at=first + timedelta(minutes=i),
        ))
    storage_module._default_storage = store

    at = AppTest.from_function(_app, default_timeout=60).run()
    ticks = []
    for i in range(runs):
        store.post_message(ROOM, AUTHORS[i % len(AUTHORS)], f"nowa wiadomość {i}")
        at.run()
        assert not at.exception, at.exception
        ticks.append(at.session_state["m5_tick_ms"])

    median = statistics.median(ticks)
    print(f"Pokój: {store.count_messages(ROOM)} wiadomości, bufor: {len(at.session_state[f'm5_buf_{ROOM}'])}")
    print(f"Tick fragmentu: mediana {median:.1f} ms, min {min(ticks):.1f} ms, max {max(ticks):.1f} ms "
          f"({runs} ticków) -> {'OK' if median < TICK_BUDGET_MS else 'ZA WOLNO'} (budżet {TICK_BUDGET_MS} ms)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500)
