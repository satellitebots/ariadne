"""Plan -> the backbrief document. The only formatter: if a surface shows a plan, it shows this."""
SECTION = ("MISSION", "STEPS", "GATES", "RISKS", "QUESTIONS")


def backbrief(plan):
    out = ["MISSION:", f"  {plan.get('mission') or '(not stated)'}", "", "STEPS:"]
    for s in plan["steps"]:
        out.append(f"  {s['n']}. {s['text']}")
        if s.get("model"):
            out.append(f"     model: {s['model']}")
    out += ["", "GATES:"]
    out += [f"  - {g}" for g in plan.get("gates") or []] or ["  - (none named)"]
    out += ["", "RISKS:"]
    out += [f"  - {r}" for r in plan.get("risks") or []] or ["  - (none named)"]
    out += ["", "QUESTIONS:"]
    out += [f"  - {q}" for q in plan.get("questions") or []] or ["  - (none)"]
    return "\n".join(out)


def steps(plan):
    """What the page renders as rows: number, text, model."""
    return [{"n": s["n"], "text": s["text"], "model": s.get("model") or ""} for s in plan["steps"]]
