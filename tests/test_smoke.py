"""Проверка на своём файле:  python tests/test_smoke.py Представление.docx"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from practice_diary import DiaryOptions, Predstavlenie, generate_diary  # noqa: E402

pr = Predstavlenie.load(sys.argv[1])
assert pr.groups, "группы не найдены"
with tempfile.TemporaryDirectory() as d:
    g = pr.groups[0]
    s = next(st for st in g.students if st.get("name"))
    r = generate_diary(s, g, DiaryOptions(output_dir=Path(d)))
    print("дневник:", r.path.name, "| не заполнено:", r.missing_values, "| нераспознано:", r.unknown_fields)
    out = pr.save(Path(d) / "copy.docx")
    assert len(Predstavlenie.load(out).groups) == len(pr.groups)
print("OK:", [(g.name, len(g.students)) for g in pr.groups])
