"""
M4-08 — podobieństwo opisów profilu (bio). CZYSTA LOGIKA: zero importów streamlit.

Backend domyślny: TF-IDF w czystym Pythonie (zero zależności, ~ms dla setek osób).
Furtka na embeddingi: wszystko idzie przez interfejs `BioEncoder` — inny backend (model
lokalny, API, wektory policzone offline) wystarczy przypisać do `bio.ENCODER`. Silnik zna tylko
`bio_similarities(user, others)`.

Koszt na rerunie: wektory liczymy raz na „wersję bio” (klucz = krotka (id, bio) wszystkich osób,
lru_cache) — rerun bez zmian w profilach to tylko iloczyny skalarne rzadkich wektorów.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from typing import Protocol

from shared.models import User

# --------------------------------------------------------------------------- #
# Tokenizacja z prostym stemmingiem PL
# --------------------------------------------------------------------------- #

STEM_LEN = 6                # rdzeń = początek słowa po odcięciu końcówki (fotografka/fotografuję → fotogr)
MIN_STEM_LEN = 4            # końcówki nie odcinamy, jeśli zostałoby mniej
MIN_TOKEN_LEN = 3

# Końcówki fleksyjne, od najdłuższych; odcinamy co najwyżej jedną.
_SUFFIXES = sorted(
    # bez „ow”: Kraków → „krak” ≠ Krakowie → „krakow”; długie słowa na -ów i tak przycina STEM_LEN
    ["ami", "ach", "owi", "ego", "emu", "ych", "ich", "ymi", "imi", "om", "ie", "ej", "em",
     "ia", "ze", "y", "i", "u", "a", "e", "o"],
    key=len, reverse=True,
)

STOPWORDS = frozenset("""
a aby ale bo by byc co czy dla do go i ich im jak jako jest juz ja jej lub ma mam mi mnie moj moja
na nad nie o od po pod przy sa sie ta tak te to tu w we z za ze zawsze kazdy bardzo lubie szukam
and the to of in on at for with my is am are i love like
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _ascii_fold(text: str) -> str:
    """„Śmieję się” → „smieje sie” (ł nie rozkłada się w NFKD, więc osobno)."""
    text = text.lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def stem(token: str) -> str:
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_STEM_LEN:
            token = token[: -len(suffix)]
            break
    return token[:STEM_LEN]


def tokenize_bio(text: str) -> list[str]:
    """Rdzenie słów bio bez stopwords i bardzo krótkich tokenów (kolejność zachowana)."""
    return [
        stem(tok) for tok in _TOKEN_RE.findall(_ascii_fold(text))
        if len(tok) >= MIN_TOKEN_LEN and tok not in STOPWORDS
    ]


# --------------------------------------------------------------------------- #
# Interfejs backendu (furtka na embeddingi)
# --------------------------------------------------------------------------- #

class BioEncoder(Protocol):
    """Backend podobieństwa opisów. Kontrakt:

    * `vectors` — {user_id: wektor} dla osób z niepustym bio (brak klucza = brak sygnału),
      deterministycznie dla tego samego wejścia; powinien sam cache'ować kosztowne obliczenia,
    * `similarity` — wynik w [0, 1], symetryczny.
    """

    def vectors(self, bios: tuple[tuple[str, str], ...]) -> Mapping[str, object]: ...

    def similarity(self, a: object, b: object) -> float: ...


SparseVector = Mapping[str, float]       # rdzeń → waga TF-IDF, wektor znormalizowany (L2 = 1)


class TfidfBioEncoder:
    """TF-IDF po rdzeniach słów; idf(t) = ln((N + 1) / (df(t) + 1)) + 1 (jak IDF tagów)."""

    def vectors(self, bios: tuple[tuple[str, str], ...]) -> Mapping[str, SparseVector]:
        return _tfidf_vectors(bios)

    def similarity(self, a: SparseVector, b: SparseVector) -> float:
        if len(b) < len(a):
            a, b = b, a
        return min(1.0, max(0.0, math.fsum(w * b.get(t, 0.0) for t, w in a.items())))


@lru_cache(maxsize=8)
def _tfidf_vectors(bios: tuple[tuple[str, str], ...]) -> dict[str, SparseVector]:
    tokens = {uid: Counter(tokenize_bio(text)) for uid, text in bios}
    tokens = {uid: tf for uid, tf in tokens.items() if tf}
    n_docs = len(tokens)
    df: Counter[str] = Counter()
    for tf in tokens.values():
        df.update(tf.keys())
    out: dict[str, SparseVector] = {}
    for uid, tf in tokens.items():
        weights = {t: c * (math.log((n_docs + 1) / (df[t] + 1)) + 1.0) for t, c in tf.items()}
        norm = math.sqrt(math.fsum(w * w for w in weights.values()))
        out[uid] = {t: w / norm for t, w in sorted(weights.items())}
    return out


ENCODER: BioEncoder = TfidfBioEncoder()   # ← tu podmieniamy backend (np. embeddingi)


# --------------------------------------------------------------------------- #
# API dla engine.py
# --------------------------------------------------------------------------- #

def bio_key(users: Iterable[User]) -> tuple[tuple[str, str], ...]:
    """Klucz cache: (id, bio) wszystkich osób, posortowane — zmiana dowolnego bio = nowy klucz."""
    return tuple(sorted((u.id, u.bio) for u in users))


def bio_similarities(user: User, others: Sequence[User], all_users: Iterable[User]) -> dict[str, float]:
    """{id osoby z `others`: podobieństwo bio do `user`} — tylko gdy OBOJE mają niepuste bio.

    `all_users` wyznacza korpus (IDF) — w aplikacji: storage.list_users().
    """
    vectors = ENCODER.vectors(bio_key(all_users))
    mine = vectors.get(user.id)
    if mine is None:
        return {}
    return {o.id: ENCODER.similarity(mine, vectors[o.id]) for o in others if o.id in vectors}
