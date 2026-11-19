"""Helfer für die Tests des Motors (kein Test, discover sammelt nur test*.py).

motor_python: ein python3.12 mit python-pptx, openpyxl und lxml, sonst None (die Tests des Motors werden dann
übersprungen). venv_ersatz: legt im Temp-Datenordner .venv/bin/python3 an. Im Betrieb liegen die Pakete in der .venv,
der Server startet sie mit -I. Am Mac des Betreuers liegen sie oft im Nutzer-Ordner von python3.12, den -I ausblendet:
Der Ersatz nimmt darum statt -I die Schalter -E -P (ohne Umgebung, ohne Ordner des Skripts im Suchpfad).
sandbox_ersatz: sandbox-exec lässt sich in der Sandbox von Claude Code nicht schachteln. Der Ersatz merkt sich das
Profil in profil.sb und startet den Rest ohne Sandbox.
"""
import functools
import os
import shutil
import subprocess
from pathlib import Path

PAKETE = "import pptx, openpyxl, lxml"
SANDBOX = """#!/bin/bash
[ "$1" = "-p" ] && printf '%s' "$2" > "$(dirname "$0")/profil.sb"
shift 2
exec "$@"
"""


@functools.lru_cache(maxsize=1)
def motor_python():
    for kandidat in (os.environ.get("KITS_TEST_MOTOR", ""), "/opt/homebrew/bin/python3.12", shutil.which("python3.12")):
        if kandidat and os.access(kandidat, os.X_OK):
            try:
                if subprocess.run([kandidat, "-c", PAKETE], capture_output=True, timeout=60).returncode == 0:
                    return kandidat
            except (OSError, subprocess.SubprocessError):
                continue
    return None


def venv_ersatz(daten: Path) -> Path:
    py = daten / ".venv" / "bin" / "python3"
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text('#!/bin/bash\nargs=()\nfor a in "$@"; do if [ "$a" = "-I" ]; then args+=(-E -P); '
                  f'else args+=("$a"); fi; done\nexec "{motor_python()}" "${{args[@]}}"\n')
    py.chmod(0o755)
    return py


def sandbox_ersatz(ordner: Path) -> Path:
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / "sandbox-exec"
    datei.write_text(SANDBOX)
    datei.chmod(0o755)
    return datei


def sandbox_exec_geht() -> bool:
    """In der Bash-Sandbox von Claude Code scheitert sandbox-exec (macOS schachtelt keine Sandbox)."""
    try:
        return subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def profil_uebersetzt(profil: str) -> str:
    """Leer, wenn sandbox-exec das Profil übersetzt (in der Bash-Sandbox scheitert danach nur sandbox_apply), sonst
    die Meldung des Übersetzers."""
    r = subprocess.run(["/usr/bin/sandbox-exec", "-p", profil, "/usr/bin/true"], capture_output=True, text=True,
                       timeout=10)
    if r.returncode == 0 or "sandbox_apply" in r.stderr:
        return ""
    return r.stderr.strip() or f"Code {r.returncode}"


DECK = """
import sys
from pptx import Presentation
prs = Presentation()
s = prs.slides.add_slide(prs.slide_layouts[1])
s.shapes.title.text = "Test Titel"
s.placeholders[1].text = "Punkt alt"
prs.save(sys.argv[1])
"""
MAPPE = """
import sys, openpyxl
wb = openpyxl.Workbook(); wb.active.title = "Liste"; wb.active["A1"] = "alt"; wb.active["B1"] = 2
wb.save(sys.argv[1])
"""


def erzeuge(skript: str, ziel: Path) -> Path:
    subprocess.run([motor_python(), "-c", skript, str(ziel)], check=True, timeout=60)
    return ziel
