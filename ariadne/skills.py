"""Shared skills: what Ariadne's flows have learned, kept in the repo (skills/<flow>/<name>/SKILL.md) so they are
versioned, pushed, and open to contributions (a pull request that adds or edits a SKILL.md).

Skills are written by the larger models that drive Ariadne over MCP (Claude and the like), not by the local
workers: after a task, the caller turns the person's feedback and its own review into a skill update with
save_skill. Every run of the flow loads all of that flow's skills.
"""
import re
import subprocess

from . import paths

SKILLS = paths.ROOT / "skills"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class SkillError(ValueError):
    pass


def skill_path(flow, name):
    return SKILLS / flow / name / "SKILL.md"


def list_skills(flow=None):
    out = []
    for f in sorted(SKILLS.glob(f"{flow or '*'}/*/SKILL.md")):
        head = f.read_text(encoding="utf-8")[:600]
        m = re.search(r"^description:\s*(.+)$", head, re.M)
        out.append({"flow": f.parent.parent.name, "name": f.parent.name, "description": m.group(1).strip() if m else ""})
    return out


def read(flow, name):
    f = skill_path(flow, name)
    if not f.exists():
        raise SkillError(f"no skill {flow}/{name}")
    return f.read_text(encoding="utf-8")


def _git(*args):
    return subprocess.run(["git", "-C", str(paths.ROOT), *args], capture_output=True, text=True, timeout=120)


def save(flow, name, content, note="", push=True, git=_git):
    """Write a skill, then commit it (only that file) and push. Returns a short report."""
    if not NAME_RE.match(name or ""):
        raise SkillError("name: lowercase letters, digits and dashes")
    if flow != "common" and not (paths.FLOWS_DIR / flow / "flow.yaml").exists():
        raise SkillError(f"no flow '{flow}' (or 'common' for skills every flow loads)")
    text = (content or "").strip()
    head = re.match(r"^---\n(.*?)\n---\n", text + "\n", re.S)
    if not head or not re.search(rf"^name:\s*{re.escape(name)}\s*$", head.group(1), re.M) \
            or not re.search(r"^description:\s*\S", head.group(1), re.M):
        raise SkillError(f"content must start with frontmatter: ---\\nname: {name}\\ndescription: ...\\n---")
    f = skill_path(flow, name)
    new = not f.exists()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text + "\n", encoding="utf-8")
    rel = f.relative_to(paths.ROOT).as_posix()
    msg = f"Skill {flow}/{name}: {note.strip() or ('add' if new else 'update')}"[:120]
    report = [f"{'created' if new else 'updated'} {rel}"]
    git("add", "--", rel)
    c = git("commit", "-m", msg, "--", rel)
    if c.returncode != 0:
        report.append("not committed: " + (c.stdout + c.stderr).strip()[-300:])
        return "; ".join(report)
    report.append("committed")
    if push:
        p = git("push", "origin", "HEAD")
        report.append("pushed" if p.returncode == 0 else "push failed: " + p.stderr.strip()[-300:])
    from . import flows as flowlib
    targets = [d.name for d in paths.FLOWS_DIR.iterdir() if (d / "flow.yaml").exists()] if flow == "common" else [flow]
    for target in targets:
        try:
            flowlib.install_shared_skills(flowlib.load_flow(paths.FLOWS_DIR / target))
        except Exception:  # the next compile picks it up anyway
            pass
    return "; ".join(report)
