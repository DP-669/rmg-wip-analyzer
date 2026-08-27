"""
rMG WIP Analyzer

Paste, pick or drag in work-in-progress tracks. Each one is verified, then
analyzed on its own, one after another. Results appear as they land.
"""

import os

import streamlit as st

from core import audio, gemini, render, sources
from core.prompts import CATALOGS

st.set_page_config(
    page_title="rMG WIP Analyzer",
    page_icon="🎚",
    layout="wide",
)


# ------------------------------------------------------------------ state

def init_state():
    st.session_state.setdefault("queue", [])
    st.session_state.setdefault("workspace", None)
    st.session_state.setdefault("folder_listing", [])
    st.session_state.setdefault("folder_link", "")
    st.session_state.setdefault("running", False)


init_state()


def workspace() -> str:
    if not st.session_state.workspace or not os.path.isdir(st.session_state.workspace):
        st.session_state.workspace = sources.workspace()
    return st.session_state.workspace


def secret(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


def add_to_queue(label: str, **kwargs):
    """Queue one track. Duplicates by label are ignored."""
    if any(item["label"] == label for item in st.session_state.queue):
        return False
    st.session_state.queue.append({
        "label": label,
        "status": "queued",
        "error": None,
        "audio": None,
        "result": None,
        **kwargs,
    })
    return True


# --------------------------------------------------------------- sidebar

with st.sidebar:
    st.markdown("### Album")

    catalog = st.selectbox(
        "Catalog",
        options=list(CATALOGS.keys()),
        format_func=lambda code: f"{code} — {CATALOGS[code]['name']}",
        help="Sets the standards the cue is judged against.",
    )

    brief = st.text_area(
        "Album brief",
        height=160,
        placeholder=(
            "The concept, direction, references, anything the composer was "
            "asked to work to. Leave empty to assess on craft alone."
        ),
    )

    st.divider()
    st.markdown("### Status")

    gemini_key = secret("GEMINI_API_KEY")
    dropbox_token = secret("DROPBOX_ACCESS_TOKEN")

    st.write("Gemini key", "✅" if gemini_key else "❌ missing")
    st.write("Dropbox token", "✅" if dropbox_token else "— folder listing off")

    if not gemini_key:
        st.error("Add GEMINI_API_KEY in app settings before running.")

    st.divider()
    if st.button("Clear everything", use_container_width=True):
        if st.session_state.workspace:
            sources.cleanup(st.session_state.workspace)
        for key in ("queue", "workspace", "folder_listing", "folder_link"):
            st.session_state[key] = [] if key.endswith(("queue", "listing")) else None
        st.session_state.folder_link = ""
        st.rerun()


# ------------------------------------------------------------------ input

st.title("WIP Analyzer")
st.caption(
    "Every track is checked before it is analyzed. If the model cannot prove "
    "it heard the audio, that track is flagged and skipped rather than guessed at."
)

pick, paste, folder = st.tabs(["Pick files", "Paste links", "Dropbox folder"])

with pick:
    st.write(
        "Choose tracks from Files, iCloud or Dropbox. On a Mac you can also "
        "drag them in from Finder."
    )
    uploads = st.file_uploader(
        "Audio files",
        type=["mp3", "wav", "aif", "aiff", "flac", "m4a"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if uploads and st.button("Add to queue", key="add_uploads", type="primary"):
        added = 0
        for upload in uploads:
            path = sources.save_upload(upload, workspace())
            if add_to_queue(upload.name, kind="local", path=path):
                added += 1
        st.success(f"Added {added} track(s).")
        st.rerun()

with paste:
    st.write("One Dropbox file link per line. Folder links belong in the next tab.")
    raw = st.text_area(
        "Links",
        height=150,
        placeholder="https://www.dropbox.com/scl/fi/.../Track 01 v1.mp3?rlkey=...",
        label_visibility="collapsed",
    )
    if raw.strip() and st.button("Add to queue", key="add_links", type="primary"):
        added = 0
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            label = sources.filename_from(line, fallback=f"link {added + 1}")
            if add_to_queue(label, kind="link", url=line):
                added += 1
        st.success(f"Added {added} link(s).")
        st.rerun()

with folder:
    if not dropbox_token:
        st.info(
            "Folder listing needs a Dropbox access token. Add "
            "DROPBOX_ACCESS_TOKEN in app settings, or paste individual file "
            "links in the tab above."
        )
    else:
        st.write(
            "Paste a composer's folder link. Every audio file inside is listed, "
            "wherever it sits — pick the ones you want."
        )
        link = st.text_input(
            "Folder link",
            value=st.session_state.folder_link,
            placeholder="https://www.dropbox.com/scl/fo/...",
            label_visibility="collapsed",
        )
        if st.button("List folder", key="list_folder"):
            try:
                with st.spinner("Reading the folder..."):
                    st.session_state.folder_listing = sources.list_dropbox_folder(
                        link, dropbox_token
                    )
                    st.session_state.folder_link = link
            except sources.SourceError as exc:
                st.session_state.folder_listing = []
                st.error(str(exc))

        listing = st.session_state.folder_listing
        if listing:
            st.caption(
                f"{len(listing)} audio file(s) found. Folder position is not "
                "trusted — pick by name."
            )
            chosen = st.multiselect(
                "Tracks",
                options=[f["rel_path"] for f in listing],
                format_func=lambda p: p.lstrip("/"),
                default=[],
            )
            if chosen and st.button("Add to queue", key="add_folder", type="primary"):
                by_path = {f["rel_path"]: f for f in listing}
                added = 0
                for rel in chosen:
                    entry = by_path[rel]
                    if add_to_queue(
                        entry["name"],
                        kind="shared",
                        rel_path=rel,
                        shared_link=entry["shared_link"],
                    ):
                        added += 1
                st.success(f"Added {added} track(s).")
                st.rerun()


# ------------------------------------------------------------------ queue

st.divider()

queue = st.session_state.queue

if not queue:
    st.info("Nothing queued yet. Add tracks above to get started.")
    st.stop()

header_left, header_right = st.columns([3, 1])
with header_left:
    st.markdown(f"### Queue — {len(queue)} track(s)")
    st.caption("Processed top to bottom, one at a time.")

for index, item in enumerate(queue):
    row = st.columns([6, 2, 1])
    icon = {
        "queued": "○", "running": "◐", "done": "●", "failed": "✕",
    }[item["status"]]
    row[0].write(f"{icon}  {item['label']}")
    row[1].caption(item["status"])
    if item["status"] in ("queued", "failed") and not st.session_state.running:
        if row[2].button("Remove", key=f"rm_{index}"):
            st.session_state.queue.pop(index)
            st.rerun()

can_run = bool(gemini_key) and any(i["status"] == "queued" for i in queue)

if st.button(
    "Analyze queue",
    type="primary",
    disabled=not can_run,
    use_container_width=True,
):
    st.session_state.running = True
    client = gemini.make_client(gemini_key)
    results_area = st.container()

    progress = st.progress(0.0)
    pending = [i for i in queue if i["status"] == "queued"]

    for position, item in enumerate(pending):
        progress.progress(
            position / max(len(pending), 1),
            text=f"{item['label']} — {position + 1} of {len(pending)}",
        )
        item["status"] = "running"

        try:
            # Get the file onto disk.
            if item["kind"] == "local":
                path = item["path"]
            elif item["kind"] == "link":
                path = sources.download(item["url"], workspace())
            else:
                path = sources.download_from_shared_folder(
                    item["shared_link"], item["rel_path"],
                    dropbox_token, workspace(),
                )

            # Measure it. This is the ground truth the gate uses.
            item["audio"] = audio.inspect(path)

            # Upload, gate, analyze — its own Gemini session, no shared context.
            item["result"] = gemini.analyze_track(
                client, path, item["audio"], catalog, brief
            )
            item["status"] = "done"

        except (sources.SourceError, audio.AudioError,
                gemini.GateFailure, gemini.AnalysisFailure) as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 — surface, never swallow
            item["status"] = "failed"
            item["error"] = f"Unexpected problem: {exc}"

        # Show it the moment it lands.
        with results_area:
            if item["status"] == "done":
                st.success(f"{item['label']} — analyzed")
            else:
                st.error(f"{item['label']} — {item['error']}")

    progress.progress(1.0, text="Finished")
    st.session_state.running = False
    st.rerun()


# ---------------------------------------------------------------- results

done = [i for i in queue if i["status"] == "done"]
failed = [i for i in queue if i["status"] == "failed"]

if done:
    st.divider()
    summary = render.run_summary(queue)
    st.markdown(
        f"### Results — {summary['analyzed']} analyzed"
        + (f", {summary['failed']} failed" if summary["failed"] else "")
    )

    for item in done:
        spec = item["audio"]["spec"]
        title = item["label"]
        if not spec["compliant"]:
            title += "   ⚠ off spec"

        with st.expander(title, expanded=len(done) == 1):
            gate = item["result"]["gate"]
            st.caption(
                f"Verified — file {item['audio']['duration_display']}, "
                f"Gemini heard {audio.format_duration(gate['_claimed_duration'])}, "
                f"drift {gate['_drift_seconds']}s"
                + (
                    f" · {', '.join(spec['issues'])}"
                    if not spec["compliant"] else ""
                )
            )
            st.markdown(render.as_markdown(item))
            st.text_area(
                "Draft note",
                value=render.as_note(item),
                height=200,
                key=f"note_{item['label']}",
                help="Starting point for the email. Edit before sending.",
            )

if failed:
    st.divider()
    st.markdown("### Did not process")
    st.markdown(render.failure_report(failed))
