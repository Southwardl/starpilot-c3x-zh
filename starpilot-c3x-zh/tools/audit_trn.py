"""审计代码中所有 trn() 复数调用，找出 .po 里缺少 msgid_plural 的条目。"""
import re
import json
from pathlib import Path

ROOT = Path("/data/openpilot")
PO = ROOT / "selfdrive/ui/translations/app_zh-CHS.po"
SCAN = [ROOT / "selfdrive/ui", ROOT / "starpilot", ROOT / "system/ui"]

# trn("singular", "plural", ...)
TRN = re.compile(
    r'trn\(\s*(["\'])(?P<sing>(?:\\.|(?!\1).)*?)\1\s*,\s*(["\'])(?P<plur>(?:\\.|(?!\3).)*?)\3',
    re.S,
)

def unesc(s: str) -> str:
    return s.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")

def main():
    po_text = PO.read_text(encoding="utf-8")
    has_plural = set()
    for m in re.finditer(r'^msgid "((?:[^"\\]|\\.)*)"\nmsgid_plural', po_text, re.M):
        has_plural.add(unesc(m.group(1)))
    singular_only = set()
    for m in re.finditer(r'^msgid "((?:[^"\\]|\\.)*)"\nmsgstr "', po_text, re.M):
        singular_only.add(unesc(m.group(1)))

    found = {}
    files = 0
    for root in SCAN:
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            if "__pycache__" in str(py) or "/tests/" in str(py).replace("\\", "/"):
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "trn(" not in text:
                continue
            files += 1
            for m in TRN.finditer(text):
                sing, plur = unesc(m.group("sing")), unesc(m.group("plur"))
                found.setdefault((sing, plur), []).append(str(py.relative_to(ROOT)))

    print(f"  含 trn() 的文件: {files}")
    print(f"  唯一 (单数, 复数) 组合: {len(found)}")
    missing = []
    only_singular = []
    for (sing, plur), where in sorted(found.items()):
        if sing in has_plural:
            continue
        missing.append({"singular": sing, "plural": plur, "where": where[:2]})
        if sing in singular_only:
            only_singular.append(sing)

    print(f"  缺少 msgid_plural 的: {len(missing)}")
    print(f"  其中已有单数译文(但 trn 查不到): {len(only_singular)}")
    for item in missing:
        tag = "有单数译文" if item["singular"] in only_singular else "完全缺失"
        print(f"    [{tag}] {item['singular']!r} / {item['plural']!r}   <- {item['where'][0] if item['where'] else '?'}")

    Path("/tmp/trn_missing.json").write_text(
        json.dumps(missing, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  已写入 /tmp/trn_missing.json")


if __name__ == "__main__":
    main()
