"""
Turning the JSON into something readable.

Two audiences. The screen version is for Damir, scanning. The copy version is
plain text he can paste into an email to the composer with light editing.
"""

from .audio import format_duration

FIX_HINTS = {
    "folder link": "Open the folder in Dropbox, tap the track, and copy that link.",
    "web page": "Regenerate the share link in Dropbox and make sure it is not password-protected.",
    "expired": "Regenerate the share link in Dropbox.",
    "not found": "The file was moved or renamed. Get a fresh link.",
    "Duration mismatch": "Re-run this track on its own. If it fails again, re-export the MP3 from the session.",
    "cannot hear": "Re-export the file — it may be corrupt or effectively silent.",
    "corrupt": "Ask the composer to re-export and re-upload.",
    "token": "The Dropbox token needs regenerating in the app settings.",
    "API key": "Add the Gemini key in the app settings.",
    "silence": "Check the file actually plays. It may have exported empty.",
}


def fix_for(message: str) -> str:
    """Suggest what to do about a failure, in plain language."""
    for marker, hint in FIX_HINTS.items():
        if marker.lower() in message.lower():
            return hint
    return "Re-run this track on its own to see whether it was a one-off."


def _tc(value) -> str:
    return value if isinstance(value, str) and value.strip() else "?"


def as_markdown(item: dict) -> str:
    """The on-screen version."""
    analysis = item["result"]["analysis"]
    info = item["audio"]
    lines = []

    form = analysis.get("form", {})
    lines.append(
        f"**Form —** {form.get('identified', 'unclear')} "
        f"({form.get('confidence', '?')} confidence). "
        f"{form.get('reasoning', '')}"
    )
    length_note = (analysis.get("length_check") or "").strip()
    if length_note.startswith(info["duration_display"]):
        length_note = length_note[len(info["duration_display"]):].lstrip(" —-.,")
    lines.append(f"**Length —** {info['duration_display']} — {length_note}")
    lines.append("")

    notes = analysis.get("primary_notes") or []
    if notes:
        lines.append("**Primary notes**")
        for index, note in enumerate(notes, 1):
            where = _tc(note.get("where"))
            lines.append(f"{index}. *{where}* — {note.get('note', '')}")
            if note.get("why_it_matters"):
                lines.append(f"   {note['why_it_matters']}")
        lines.append("")

    working = analysis.get("what_is_working") or []
    if working:
        lines.append("**Working**")
        for entry in working:
            lines.append(f"- {entry}")
        lines.append("")

    structure = analysis.get("structure") or []
    if structure:
        lines.append("**Structure**")
        for section in structure:
            lines.append(
                f"- `{_tc(section.get('from'))}–{_tc(section.get('to'))}` "
                f"**{section.get('section', '?')}** — "
                f"{section.get('what_happens', '')}"
            )
        lines.append("")

    dev = analysis.get("development_vs_repetition") or {}
    if dev:
        lines.append(
            f"**Development —** {dev.get('verdict', '?')}. {dev.get('detail', '')}"
        )

    back = analysis.get("back_end") or {}
    if back:
        present = "present" if back.get("present") else "not present"
        starts = f" from {back['starts']}" if back.get("starts") else ""
        lines.append(f"**Back end —** {present}{starts}. {back.get('assessment', '')}")

    hooks = analysis.get("hooks_and_motifs") or []
    if hooks:
        lines.append("")
        lines.append("**Hooks and motifs**")
        for hook in hooks:
            tag = "" if hook.get("confidence") == "confirmed" else " *(probable)*"
            lines.append(
                f"- `{_tc(hook.get('first_heard'))}` {hook.get('what', '')}{tag} — "
                f"{hook.get('development', '')}"
            )

    edits = analysis.get("edit_points") or []
    if edits:
        lines.append("")
        strong = [e for e in edits if e.get("strength") == "strong"]
        rest = [e for e in edits if e.get("strength") != "strong"]
        rendered = ", ".join(
            f"`{_tc(e.get('at'))}`" for e in strong
        ) or "none identified"
        lines.append(f"**Edit points —** strong: {rendered}")
        if rest:
            lines.append(
                "Usable: " + ", ".join(f"`{_tc(e.get('at'))}`" for e in rest)
            )

    space = analysis.get("dialogue_space") or []
    if space:
        lines.append("")
        lines.append("**Dialogue space**")
        for window in space:
            lines.append(
                f"- `{_tc(window.get('from'))}–{_tc(window.get('to'))}` "
                f"{window.get('assessment', '')}"
            )

    if analysis.get("story_arc"):
        lines.append("")
        lines.append(f"**Arc —** {analysis['story_arc']}")

    flags = analysis.get("uncertainty_flags") or []
    if flags:
        lines.append("")
        lines.append("**Could not hear clearly:** " + "; ".join(flags))

    return "\n".join(lines)


def as_note(item: dict) -> str:
    """
    The paste-into-an-email version. Notes only, no analysis furniture.
    Deliberately bare — it is a starting point, not a finished email.
    """
    analysis = item["result"]["analysis"]
    lines = [item["label"], ""]

    working = analysis.get("what_is_working") or []
    if working:
        lines.append(working[0])
        lines.append("")

    for note in analysis.get("primary_notes") or []:
        where = note.get("where", "")
        prefix = f"{where} — " if where and where.lower() != "throughout" else ""
        lines.append(f"{prefix}{note.get('note', '')}")
        if note.get("why_it_matters"):
            lines.append(note["why_it_matters"])
        lines.append("")

    return "\n".join(lines).strip()


def failure_report(failed: list) -> str:
    """End-of-run summary of what did not process and what to do about it."""
    if not failed:
        return ""
    lines = [f"{len(failed)} track(s) did not process.", ""]
    for item in failed:
        lines.append(f"**{item['label']}**")
        lines.append(f"What happened: {item['error']}")
        lines.append(f"What to do: {fix_for(item['error'])}")
        lines.append("")
    return "\n".join(lines)


def run_summary(items: list) -> dict:
    done = [i for i in items if i["status"] == "done"]
    failed = [i for i in items if i["status"] == "failed"]
    flagged = [
        i for i in done
        if not i.get("audio", {}).get("spec", {}).get("compliant", True)
    ]
    return {
        "total": len(items),
        "analyzed": len(done),
        "failed": len(failed),
        "off_spec": len(flagged),
    }
