#!/usr/bin/env python3
"""Tally skill usage evidence for the sangkayana council.

Prints an evidence horizon, then one row per installed skill:
  last_used  typed  model  installed  age_days  invoke  desc_words  class  name

class:  managed (lock-tracked symlink) | foreign (hand-placed dir) | external (symlink elsewhere)
invoke: model (description loaded every turn) | user (typed only, zero context load)
desc_words: size of the always-loaded description; the context load a removal reclaims.
last_used: date of most recent evidence, or "-" when the record is silent.
"""
import json, os, re, glob, datetime, sys

H = os.path.expanduser("~")
SKILLS = f"{H}/.claude/skills"
LOCK = f"{H}/.agents/.skill-lock.json"
HIST = f"{H}/.claude/history.jsonl"
TRANSCRIPTS = f"{H}/.claude/projects/*/*.jsonl"

day = lambda ms: datetime.date.fromtimestamp(ms / 1000).isoformat()
today = datetime.date.today()


def load_lock():
    try:
        return json.load(open(LOCK))["skills"]
    except Exception:
        return {}


def classify(name):
    p = f"{SKILLS}/{name}"
    if not os.path.islink(p):
        return "foreign"
    target = os.path.realpath(p)
    return "managed" if f"{os.sep}.agents{os.sep}skills{os.sep}" in target + os.sep else "external"


def frontmatter(name):
    """(invoke, desc_words) from the skill's frontmatter."""
    for path in (f"{SKILLS}/{name}/SKILL.md", f"{SKILLS}/{name}/skill.md"):
        try:
            head = open(path, errors="ignore").read(8000)
        except OSError:
            continue
        m = re.match(r"\s*---\s*\n(.*?)\n---", head, re.S)
        if not m:
            return "?", 0
        fm = m.group(1)
        user_only = re.search(r"^disable-model-invocation:\s*true", fm, re.M | re.I)
        d = re.search(r"^description:\s*(.*(?:\n[ \t]+.*)*)", fm, re.M)
        words = len((d.group(1) if d else "").split())
        return ("user" if user_only else "model"), words
    return "?", 0


def typed_usage():
    """Typed /invocations from history.jsonl. Complete back to the file's first entry."""
    hits, stamps = {}, []
    try:
        lines = open(HIST, errors="ignore").readlines()
    except OSError:
        return {}, None
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ts = d.get("timestamp")
        if ts:
            stamps.append(ts)
        m = re.match(r"\s*/([a-zA-Z0-9_-]+)", d.get("display") or "")
        if m and ts:
            n = m.group(1)
            c, last = hits.get(n, (0, 0))
            hits[n] = (c + 1, max(last, ts))
    return hits, (min(stamps) if stamps else None)


def model_usage():
    """Skill tool-calls in surviving session transcripts. Older sessions get swept."""
    hits, stamps = {}, []
    for f in glob.glob(TRANSCRIPTS):
        try:
            body = open(f, errors="ignore").read()
            mtime = int(os.path.getmtime(f) * 1000)
        except OSError:
            continue
        stamps.append(mtime)
        for m in re.finditer(r'"skill"\s*:\s*"([a-zA-Z0-9_:-]+)"', body):
            n = m.group(1).split(":")[-1]
            c, last = hits.get(n, (0, 0))
            hits[n] = (c + 1, max(last, mtime))
    return hits, (min(stamps) if stamps else None)


def main():
    lock = load_lock()
    try:
        names = sorted(n for n in os.listdir(SKILLS) if not n.startswith("."))
    except OSError:
        sys.exit(f"no skills directory at {SKILLS}")

    typed, typed_from = typed_usage()
    model, model_from = model_usage()

    print("EVIDENCE HORIZON")
    print(f"  typed  (history.jsonl)  reaches back to {day(typed_from) if typed_from else 'nothing recorded'}")
    print(f"  model  (transcripts)    reaches back to {day(model_from) if model_from else 'nothing recorded'}")
    print("  Silence before a horizon is missing evidence, not disuse.")
    print(f"  Skills shared with other agents may have fired outside {SKILLS} entirely.\n")

    rows = []
    for n in names:
        tc, tl = typed.get(n, (0, 0))
        mc, ml = model.get(n, (0, 0))
        last = max(tl, ml)
        inst = (lock.get(n) or {}).get("installedAt", "")
        try:
            age = (today - datetime.date.fromisoformat(inst[:10])).days
        except ValueError:
            inst, age = "unknown", ""
        inv, dw = frontmatter(n)
        rows.append((last, tc + mc, {
            "last_used": day(last) if last else "-",
            "typed": tc, "model": mc,
            "installed": inst[:10] if inst else "unknown",
            "age_days": age, "invoke": inv, "desc_words": dw,
            "class": classify(n), "name": n,
        }))

    rows.sort(key=lambda r: (r[0], r[1]))
    hdr = ("last_used", "typed", "model", "installed", "age_days",
           "invoke", "desc_words", "class", "name")
    print("\t".join(hdr))
    for _, _, r in rows:
        print("\t".join(str(r[k]) for k in hdr))

    silent = sum(1 for _, t, _ in rows if t == 0)
    load = sum(r["desc_words"] for _, _, r in rows if r["invoke"] == "model")
    quiet_load = sum(r["desc_words"] for _, t, r in rows
                     if r["invoke"] == "model" and t == 0)
    noun = "skill" if len(rows) == 1 else "skills"
    print(f"\n{len(rows)} {noun} in the canon; {silent} with no surviving evidence of use.")
    print(f"context load: ~{load} description words loaded every turn, "
          f"~{quiet_load} of them from skills with no recorded use.")


if __name__ == "__main__":
    main()
