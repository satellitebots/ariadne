"""The flow's shared skills as two runtime tools: skills_list (the index) and skill_view (the SKILL.md body).

The plan prompt already lists the flow's skills with name and description (worker.skills_block), but until now a
worker mid-run had no way to read the body itself - the writing of earlier tasks and the larger models sat in a
folder. Box answers the two reads a worker needs: the index (which skills exist, one line each) and one skill in
full, so a run can actually follow a skill before doing the work it covers.

Like the MCP Pool, it never raises at the caller: an unknown name or a missing flow comes back as `ERROR: ...`
text, which is what the model can read and recover from.
"""
import re

from .. import flows as flowlib

MAX_BODY = 8000
_DESC = re.compile(r"^description:\s*(.+)$", re.M)


def _description(skill_dir):
    head = (skill_dir / "SKILL.md").read_text(encoding="utf-8")[:600]
    m = _DESC.search(head)
    return m.group(1).strip() if m else ""


class Box:
    """The skills a run of this flow can read: skills/common/* and skills/<flow>/* (the flow's own wins)."""

    def __init__(self, flow):
        self.flow = flow

    def offered(self):
        return [
            {"type": "function", "function": {
                "name": "skills_list",
                "description": "The shared skills this flow loads (skills/common and the flow's own): one line per "
                               "skill, name and description. The index of what earlier tasks learned here.",
                "parameters": {"type": "object",
                               "properties": {"flow": {"type": "string",
                                                        "description": "list another flow's skills instead"}},
                               "required": []}}},
            {"type": "function", "function": {
                "name": "skill_view",
                "description": "Read one shared skill in full: its SKILL.md body (frontmatter included). Use it to "
                               "follow a skill before doing the work it covers.",
                "parameters": {"type": "object",
                               "properties": {
                                   "name": {"type": "string", "description": "the skill's name (from skills_list)"},
                                   "flow": {"type": "string",
                                            "description": "look it up in another flow's skills instead"}},
                               "required": ["name"]}}},
        ]

    def call(self, name, arguments):
        try:
            return self._dispatch(name, arguments or {})
        except Exception as e:   # never raises: the model reads the error and recovers
            return f"ERROR: {name} failed: {type(e).__name__}: {e}"

    def _dispatch(self, name, arguments):
        if name == "skills_list":
            return self._list(arguments)
        if name == "skill_view":
            return self._view(arguments)
        return f"ERROR: no skill tool '{name}' (use skills_list or skill_view)"

    def _dirs(self, arguments):
        # the flow's own skills, or another flow's when the call names one
        return flowlib.shared_skill_dirs(str(arguments.get("flow") or self.flow.name))

    def _list(self, arguments):
        dirs = self._dirs(arguments)
        if not dirs:
            return "(no shared skills yet)"
        return "\n".join(f"- {n}: {_description(d)}" for n, d in sorted(dirs.items()))

    def _view(self, arguments):
        name = str(arguments.get("name") or "").strip()
        if not name:
            return "ERROR: skill_view needs a name"
        dirs = self._dirs(arguments)
        d = dirs.get(name)
        if d is None:
            return f"ERROR: no skill '{name}'; available: " + (", ".join(sorted(dirs)) or "none")
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        if len(text) > MAX_BODY:
            text = text[:MAX_BODY] + f"\n[... {len(text) - MAX_BODY} more characters]"
        return text
