"""Stable launcher for the enhanced Songpack Editor."""
import run_improved
import condition_logic
import priority


def refresh_library(tab, keep_selection=False):
    previous = tab.selected_entry_id if keep_selection else None
    query = tab.music_search_var.get().strip().casefold()
    tab.tree.delete(*tab.tree.get_children())
    for entry in tab.app.pack.entries:
        if query and not any(query in song.casefold() for song in entry.songs):
            continue
        tab.tree.insert(
            "", "end", iid=entry.id,
            values=(
                "⚠" if not entry.has_any_condition() else "",
                entry.display_name(),
                condition_logic.summarize_entry(entry),
                priority.score_entry(entry),
            ),
        )
    if previous and tab.tree.exists(previous):
        tab.tree.selection_set(previous)


run_improved.refresh_library = refresh_library

if __name__ == "__main__":
    run_improved.main()
