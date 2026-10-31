"""Низкоуровневые помощники для работы с XML документа Word."""
from __future__ import annotations

import copy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

W14_ATTRS = (
    "{http://schemas.microsoft.com/office/word/2010/wordml}paraId",
    "{http://schemas.microsoft.com/office/word/2010/wordml}textId",
)


# ---------- текст ----------

def run_text(r) -> str:
    out = []
    for ch in r.iterchildren():
        if ch.tag == qn("w:t"):
            out.append(ch.text or "")
        elif ch.tag == qn("w:tab"):
            out.append("\t")
        elif ch.tag in (qn("w:br"), qn("w:cr")):
            out.append("\n")
    return "".join(out)


def paragraph_runs(p):
    """Все w:r параграфа, включая вложенные в гиперссылки/smartTag и т.п."""
    return [r for r in p.iter(qn("w:r"))
            if r.getparent() is p or r.getparent().tag != qn("w:r")]


def paragraph_text(p) -> str:
    return "".join(run_text(r) for r in paragraph_runs(p))


def tc_text(tc) -> str:
    return "\n".join(paragraph_text(p) for p in tc.findall(qn("w:p"))).strip()


def set_run_text(r, text: str) -> None:
    """Заменить содержимое run, сохранив его форматирование (rPr)."""
    for ch in list(r):
        if ch.tag != qn("w:rPr"):
            r.remove(ch)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    r.append(t)


def set_paragraph_text(p, text: str) -> None:
    """Заменить весь текст параграфа, сохранив форматирование первого run."""
    runs = paragraph_runs(p)
    if runs:
        first = runs[0]
        for r in runs[1:]:
            r.getparent().remove(r)
        set_run_text(first, text)
        return
    r = OxmlElement("w:r")
    ppr = p.find(qn("w:pPr"))
    if ppr is not None and ppr.find(qn("w:rPr")) is not None:
        rpr = copy.deepcopy(ppr.find(qn("w:rPr")))
        r.append(rpr)
    set_run_text(r, text)
    p.append(r)


def set_text_after_colon(p, value: str) -> None:
    """«Метка: значение» — заменить всё, что идёт после первого двоеточия."""
    runs = paragraph_runs(p)
    acc = ""
    for i, r in enumerate(runs):
        t = run_text(r)
        if ":" in t:
            head = t[: t.index(":") + 1]
            set_run_text(r, head + " " + value)
            for rr in runs[i + 1:]:
                rr.getparent().remove(rr)
            return
        acc += t
    set_paragraph_text(p, value)


def strip_w14(el) -> None:
    for node in el.iter():
        for a in W14_ATTRS:
            if a in node.attrib:
                del node.attrib[a]


def set_tc_text(tc, text: str) -> None:
    """Записать многострочный текст в ячейку, сохранив оформление."""
    paras = tc.findall(qn("w:p"))
    if not paras:
        p = OxmlElement("w:p")
        tc.append(p)
        paras = [p]
    lines = text.split("\n") if text else [""]
    template = paras[0]
    last = None
    for i, line in enumerate(lines):
        if i < len(paras):
            p = paras[i]
        else:
            p = copy.deepcopy(template)
            strip_w14(p)
            last.addnext(p)
        set_paragraph_text(p, line)
        last = p
    for p in paras[len(lines):]:
        tc.remove(p)


# ---------- таблицы и объединённые ячейки ----------

def tc_vmerge(tc) -> str | None:
    tcpr = tc.find(qn("w:tcPr"))
    if tcpr is None:
        return None
    vm = tcpr.find(qn("w:vMerge"))
    if vm is None:
        return None
    return vm.get(qn("w:val")) or "continue"


def set_tc_vmerge(tc, val: str | None) -> None:
    tcpr = tc.get_or_add_tcPr()
    vm = tcpr.find(qn("w:vMerge"))
    if val is None:
        if vm is not None:
            tcpr.remove(vm)
        return
    if vm is None:
        vm = OxmlElement("w:vMerge")
        # vMerge должен идти после tcW/gridSpan/hMerge
        anchor = None
        for tag in ("w:tcW", "w:gridSpan", "w:hMerge"):
            found = tcpr.find(qn(tag))
            if found is not None:
                anchor = found
        if anchor is not None:
            anchor.addnext(vm)
        else:
            tcpr.insert(0, vm)
    if val == "restart":
        vm.set(qn("w:val"), "restart")
    elif qn("w:val") in vm.attrib:
        del vm.attrib[qn("w:val")]


def row_grid(tr) -> dict[int, object]:
    """{номер колонки сетки: tc}"""
    out, col = {}, 0
    for tc in tr.findall(qn("w:tc")):
        out[col] = tc
        tcpr = tc.find(qn("w:tcPr"))
        span = 1
        if tcpr is not None and tcpr.find(qn("w:gridSpan")) is not None:
            span = int(tcpr.find(qn("w:gridSpan")).get(qn("w:val")))
        col += span
    return out


def table_rows(tbl):
    return tbl.findall(qn("w:tr"))


def resolved_cell_text(rows, ri: int, col: int) -> str:
    """Текст ячейки с учётом вертикального объединения."""
    while ri >= 0:
        tc = row_grid(rows[ri]).get(col)
        if tc is None:
            return ""
        if tc_vmerge(tc) != "continue":
            return tc_text(tc)
        ri -= 1
    return ""


# ---------- выделение цветом ----------

YELLOW_FILLS = {"FFFF00", "FFFF66", "FFFF99", "FFF200"}


def run_is_highlighted(r, yellow_only: bool = True) -> bool:
    rpr = r.find(qn("w:rPr"))
    if rpr is None:
        return False
    hl = rpr.find(qn("w:highlight"))
    if hl is not None:
        val = hl.get(qn("w:val"))
        if val and val != "none" and (not yellow_only or val == "yellow"):
            return True
    shd = rpr.find(qn("w:shd"))
    if shd is not None:
        fill = (shd.get(qn("w:fill")) or "").upper()
        if fill in YELLOW_FILLS or (not yellow_only and fill not in ("", "AUTO", "FFFFFF")):
            return True
    return False
