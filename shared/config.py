"""
shared/config.py — stałe aplikacji i feature flagi.

Feature flagi: funkcja OPCJONALNA trafia do menu dopiero, gdy spełnia swoje DoD.
Włączamy je na checkpointach integracyjnych (patrz ARCHITECTURE.md -> Harmonogram).
"""

APP_NAME = "Meevent"
APP_WORDMARK = ("Mee", "vent")     # logo w górnym pasku: początek + reszta w kolorze marki (razem = APP_NAME)
APP_TAGLINE = "Wyjdźmy razem"

DEFAULT_USER_ID = "u_ola"          # użytkownik demo (brak logowania w MVP)
CHAT_POLL_SECONDS = 2.0            # co ile fragment czatu dociąga nowe wiadomości
MAX_MATCHES_IN_PANEL = 8

FEATURES: dict[str, bool] = {
    "recommendations": True,       # M4: "Polecane dla Ciebie" w pustym prawym panelu
    "profile_view": True,          # M3: podgląd cudzego profilu
    "dm_chat": True,               # M5: prywatny czat 1:1 z dopasowaną osobą
    "add_event": True,             # M2: formularz dodawania własnego wydarzenia
}
