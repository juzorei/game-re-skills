"""Check every skills/<name>/SKILL.md: frontmatter, scope section, size and local links."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\]\(((?:references|templates|assets|scripts)/[^)#\s]+)")
SCOPE_LINE = "Don't help bypass or hide from anti-cheat"
MAX_LINES = 300
MAX_DESCRIPTION = 1024


def frontmatter(text: str) -> dict | None:
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter isn't valid YAML: {exc}") from None
    return data if isinstance(data, dict) else None


def check(skill_dir: Path) -> list[str]:
    errors = []
    path = skill_dir / "SKILL.md"
    if not path.is_file():
        return [f"{skill_dir.name}: missing SKILL.md"]
    text = path.read_text(encoding="utf-8")
    try:
        meta = frontmatter(text)
    except ValueError as exc:
        return [f"{skill_dir.name}: {exc}"]
    if meta is None:
        return [f"{skill_dir.name}: SKILL.md has no '---' frontmatter block"]
    name, description = str(meta.get("name", "")), str(meta.get("description", ""))
    if name != skill_dir.name:
        errors.append(f"{skill_dir.name}: name {name!r} doesn't match the directory")
    if not NAME_RE.match(name) or len(name) > 64:
        errors.append(f"{skill_dir.name}: name must be kebab-case, at most 64 chars")
    if not description:
        errors.append(f"{skill_dir.name}: description is empty")
    elif len(description) > MAX_DESCRIPTION:
        errors.append(f"{skill_dir.name}: description is {len(description)} chars (max {MAX_DESCRIPTION})")
    if SCOPE_LINE not in text:
        errors.append(f"{skill_dir.name}: scope section is missing")
    lines = text.count("\n") + 1
    if lines > MAX_LINES:
        errors.append(f"{skill_dir.name}: SKILL.md is {lines} lines (max {MAX_LINES}); move detail to references/")
    for md in skill_dir.rglob("*.md"):
        for target in LINK_RE.findall(md.read_text(encoding="utf-8")):
            if not (md.parent / target).exists() and not (skill_dir / target).exists():
                errors.append(f"{skill_dir.name}: {md.relative_to(skill_dir)} links to missing {target}")
    return errors


def main() -> int:
    skill_dirs = sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir())
    if not skill_dirs:
        print("no skills found")
        return 1
    errors = [e for d in skill_dirs for e in check(d)]
    for error in errors:
        print(f"error: {error}")
    print(f"{len(skill_dirs)} skills checked, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
