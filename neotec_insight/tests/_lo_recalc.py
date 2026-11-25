"""Portable LibreOffice recalculation for workbook tests (v3.9.8).

Finds LibreOffice on PATH, recalculates a copy of the workbook in a unique
temporary directory (its own LibreOffice profile too, so parallel runs do not
collide), checks the exit status, and returns the recalculated copy's path.
Tests skip when LibreOffice is not installed."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")


def recalculated_copy(path: str | Path, timeout: int = 120) -> Path:
    if not SOFFICE:
        raise RuntimeError("LibreOffice is not installed")
    work = Path(tempfile.mkdtemp(prefix="insight-recalc-"))
    src = work / "in" / Path(path).name
    src.parent.mkdir()
    shutil.copy(path, src)
    out = work / "out"
    r = subprocess.run(
        [SOFFICE, "--headless", "--norestore", "--nologo", f"-env:UserInstallation={(work / 'profile').as_uri()}",
         "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out), str(src)],
        capture_output=True, text=True, timeout=timeout)
    result = out / src.name
    if r.returncode != 0 or not result.exists():
        raise RuntimeError(f"LibreOffice recalculation failed ({r.returncode}): {r.stderr[-500:]}")
    return result


def formula_errors(path: str | Path) -> list[str]:
    """Cells holding a spreadsheet error value after recalculation."""
    import openpyxl
    bad = []
    wb = openpyxl.load_workbook(path, data_only=True)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("#") and c.value.rstrip("!?0/").upper() in (
                        "#REF", "#DIV", "#VALUE", "#NAME", "#N/A", "#NUM", "#NULL"):
                    bad.append(f"{ws.title}!{c.coordinate}={c.value}")
    return bad
