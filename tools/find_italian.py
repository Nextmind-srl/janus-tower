"""Finds Italian text in the user-visible strings of the app.

Scans string literals and template text (comments excluded) in frontend/js/*.js, frontend/html/*.html
and backend/*.py (plus server.py), and reports the ones that contain Italian words or accented letters.

Usage:  python tools/find_italian.py [--summary] [paths...]
"""

import ast
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Words that are Italian and not English: one of them is enough to flag a string.
STRONG = set("""
progetto progetti utente utenti chiave chiavi scansione scansioni errore errori nessun nessuna nessuno tutti tutte
dettaglio dettagli periodo attivo attiva attivi attive spesa costo costi giorno giorni ultimo ultimi ultime totale
chiudi salva annulla cerca filtri filtro stima stime risorsa risorse servizio servizi dati oppure verifica verificato
verificata limite completi completo parziali parziale mostra apri mese mesi oggi ieri mancante mancanti abilitato
abilitata abilitati disabilitato disabilitata disabilitati sconto sconti risparmio risparmi fattura fatture listino
chiamate chiamata consumo consumi richieste richiesta rilevati rilevato rilevata rischio rischi critici
critico alti alto basso bassi medio medi bloccati bloccato violazioni violazione conformità conformi conforme
perimetro accesso negato concesso concessi permessi permesso ricerca cerca aggiorna aggiornato
aggiornamento caricamento caricamenti completata completato completati avviata avviato fallita fallito riuscita
riuscito pronto pronta attendi attendere sincronizzazione sincronizzato sincronizzati escluso esclusi esclusa
incluso inclusi inclusa nuovo nuovi nuova nuove vecchio vecchi lista elenco scheda schede apertura chiusura
dovrebbe possibile possibili necessario necessaria necessari disponibile disponibili indisponibile assente assenti
presente presenti configurato configurata configurati configurazione impostazioni impostazione valore valori
differenza massimo minimo giornaliero giornaliera giornalieri mensile mensili annuale settimana settimane
anno anni minuti secondi quando dove perché perche come cosa quale quali questo questa questi queste
questo sopra sotto prima dopo durante entro senza anche ancora sempre mai già gia ogni altro altra altri altre
stesso stessa tra fra verso dalla dallo dalle dagli dai nella nello nelle negli nei sulla sullo sulle sugli sui
della dello delle degli dei alla allo alle agli
""".split())

# Words shared with English or too short to be reliable alone: flag only in groups of two or with a strong word.
WEAK = {"per", "non", "con", "solo", "sono", "del", "dei", "nel", "il", "lo", "gli", "le", "un", "una", "uno", "di",
        "da", "su", "se", "ma", "che", "chi", "più", "piu", "meno", "poi", "già", "e", "o", "in", "a", "ed"}
# of those, only these are really ambiguous with English text; the others are never English words
WEAK_ENGLISH_OVERLAP = {"per", "non", "con", "solo", "a", "e", "o", "in", "se", "lo", "il", "su", "da", "un", "di", "ma", "poi"}
WEAK_ALWAYS = WEAK - WEAK_ENGLISH_OVERLAP

ACCENTED = re.compile(r"[àèéìòù]")
WORD = re.compile(r"[A-Za-zÀ-ÿ']+")

# Strings that are legitimately Italian-looking and must be ignored (exact match).
IGNORE_EXACT = {
    "Cinzel", "Jost", "Inter", "JetBrains Mono",
    # legacy Italian texts saved by older versions, mapped to English when the registry is loaded (sync_registry.py)
    "Nessuna API AI abilitata",
    "Nessun dato AI rilevato (0 costi, 0 token, 0 risorse)",
}


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def italian_hits(text: str) -> list:
    """Returns the Italian words found in a text ([] if it looks English). HTML comments are not user-visible."""
    text = _HTML_COMMENT.sub(" ", text or "")
    if not text.strip() or len(text) < 3:
        return []
    words = [w.lower().strip("'") for w in WORD.findall(text)]
    strong = [w for w in words if w in STRONG]
    accented = ACCENTED.findall(text)
    weak = [w for w in words if w in WEAK and w not in STRONG]
    hits = list(dict.fromkeys(strong))
    if accented and not hits:
        hits = [m.group(0) for m in re.finditer(r"\w*[àèéìòù]\w*", text)][:3]
    if not hits:
        always = [w for w in weak if w in WEAK_ALWAYS]
        overlap = [w for w in weak if w in WEAK_ENGLISH_OVERLAP]
        if len(always) >= 2 or (always and overlap):
            hits = always
    return hits


def _line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, pos) + 1


# ---------------------------------------------------------------- JavaScript
_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^")


def js_strings(src: str):
    """Yields (line, text) for each literal piece of strings and templates (comments skipped)."""
    n = len(src)
    last_sig = ""  # last significant character, to tell a regex literal from a division
    out = []

    def scan_string(i, quote):
        j = i + 1
        buf = []
        while j < n:
            c = src[j]
            if c == "\\":
                buf.append(src[j:j + 2])
                j += 2
                continue
            if c == quote:
                return j + 1, "".join(buf)
            if c == "\n" and quote != "`":
                return j, "".join(buf)
            buf.append(c)
            j += 1
        return j, "".join(buf)

    def scan_template(i):
        """Template literal: yields literal chunks; expressions inside ${} are scanned recursively."""
        j = i + 1
        buf_start = j
        while j < n:
            c = src[j]
            if c == "\\":
                j += 2
                continue
            if c == "`":
                out.append((_line_of(src, buf_start), src[buf_start:j]))
                return j + 1
            if c == "$" and src[j + 1:j + 2] == "{":
                out.append((_line_of(src, buf_start), src[buf_start:j]))
                j = scan_code(j + 2, until_brace=True)
                buf_start = j
                continue
            j += 1
        return j

    def scan_code(i, until_brace=False):
        nonlocal last_sig
        depth = 0
        while i < n:
            c = src[i]
            if c == "/" and src[i + 1:i + 2] == "/":
                i = src.find("\n", i)
                i = n if i == -1 else i
                continue
            if c == "/" and src[i + 1:i + 2] == "*":
                e = src.find("*/", i + 2)
                i = n if e == -1 else e + 2
                continue
            if c in "'\"":
                e, text = scan_string(i, c)
                out.append((_line_of(src, i), text))
                i = e
                last_sig = "a"
                continue
            if c == "`":
                i = scan_template(i)
                last_sig = "a"
                continue
            if c == "/" and (last_sig == "" or last_sig in _REGEX_PREV):
                j = i + 1
                in_class = False
                while j < n:
                    d = src[j]
                    if d == "\\":
                        j += 2
                        continue
                    if d == "[":
                        in_class = True
                    elif d == "]":
                        in_class = False
                    elif d == "/" and not in_class:
                        break
                    elif d == "\n":
                        break
                    j += 1
                i = j + 1
                last_sig = "a"
                continue
            if until_brace:
                if c == "{":
                    depth += 1
                elif c == "}":
                    if depth == 0:
                        return i + 1
                    depth -= 1
            if not c.isspace():
                last_sig = c
            i += 1
        return i

    scan_code(0)
    return out


# ---------------------------------------------------------------------- HTML
class _HtmlText(HTMLParser):
    ATTRS = {"title", "placeholder", "aria-label", "alt", "value", "data-jt-more-label"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for k, v in attrs:
            if k in self.ATTRS and v:
                self.found.append((self.getpos()[0], v))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.found.append((self.getpos()[0], data.strip()))


# -------------------------------------------------------------------- Python
def py_strings(src: str):
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


# ------------------------------------------------------------------- driver
def default_paths():
    paths = sorted((ROOT / "frontend" / "js").glob("*.js")) + sorted((ROOT / "frontend" / "html").glob("*.html"))
    paths += sorted((ROOT / "backend").glob("*.py")) + [ROOT / "server.py"]
    return paths


def _translator_lines(src: str) -> range:
    """Lines of the runtime IT->EN translator (to be deleted in a later wave): not reported."""
    a, b = src.find("const IT_TO_EN_PHRASES"), src.find("function translateDomTreeItToEn")
    if a == -1 or b == -1:
        return range(0)
    return range(_line_of(src, a), _line_of(src, b) + 40)


def scan_file(path: Path) -> list:
    src = path.read_text(encoding="utf-8")
    skip = _translator_lines(src) if path.name == "core_and_auth.js" else range(0)
    if path.suffix == ".js":
        pieces = js_strings(src)
    elif path.suffix == ".html":
        p = _HtmlText()
        p.feed(src)
        pieces = p.found
    elif path.suffix == ".py":
        pieces = list(py_strings(src))
    else:
        return []
    findings = []
    for line, text in pieces:
        if text in IGNORE_EXACT or line in skip:
            continue
        hits = italian_hits(text)
        if hits:
            findings.append((line, hits, " ".join(text.split())[:140]))
    return findings


def scan_repo(paths=None) -> dict:
    result = {}
    for p in paths or default_paths():
        found = scan_file(Path(p))
        if found:
            try:
                key = str(Path(p).resolve().relative_to(ROOT))
            except ValueError:
                key = str(p)
            result[key] = found
    return result


def main(argv):
    summary = "--summary" in argv
    paths = [Path(a) for a in argv if not a.startswith("--")] or None
    result = scan_repo(paths)
    total = 0
    for f, items in result.items():
        total += len(items)
        if summary:
            print(f"{len(items):5d}  {f}")
        else:
            for line, hits, text in items:
                print(f"{f}:{line}: [{','.join(hits[:4])}] {text}")
    print(f"TOTAL: {total} strings with Italian text in {len(result)} files", file=sys.stderr)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
