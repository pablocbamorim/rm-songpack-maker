"""
audio_preview.py
-----------------
One shared pygame.mixer.music wrapper for the whole editor.

WHY A SHARED OBJECT
-------------------
ui_enhancements already owned a small preview state machine (which file is
loaded, is it paused, what should the button say). The audio editor needs
exactly the same thing for its own "play the selected region" button, and
pygame's music channel is a *single global stream* -- two independent
copies of that state would immediately disagree the moment one of them
started playing. So the state lives here once, and both call sites use it.

The practical payoff: starting a preview in the editor automatically stops
the song list's preview, and the song list's button text follows along via
`add_listener`, with no cross-imports between the two UI modules.

pygame is imported lazily so the app still starts (minus previews) when it
isn't installed -- the existing behaviour.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional


class PreviewError(Exception):
    """A user-facing playback problem."""


STOPPED = "stopped"
PLAYING = "playing"
PAUSED = "paused"


class PreviewPlayer:
    def __init__(self) -> None:
        self._pygame = None
        self._import_failed = False
        self._path: Optional[str] = None
        self._state: str = STOPPED
        self._volume: float = 1.0
        self._listeners: List[Callable[[str, Optional[str]], None]] = []

    # -- availability ----------------------------------------------------
    def _module(self):
        if self._pygame is None and not self._import_failed:
            try:
                import pygame  # noqa: PLC0415 - deliberately lazy
                self._pygame = pygame
            except Exception:  # noqa: BLE001
                self._import_failed = True
        return self._pygame

    def available(self) -> bool:
        return self._module() is not None

    def _mixer(self):
        pygame = self._module()
        if pygame is None:
            raise PreviewError(
                "Audio preview needs the 'pygame' package.\n\n"
                "Install it with:  python -m pip install pygame")
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception as exc:  # noqa: BLE001
            raise PreviewError(
                f"The audio device could not be opened.\n\nDetails: {exc}"
            ) from exc
        return pygame.mixer

    # -- listeners -------------------------------------------------------
    def add_listener(self, callback) -> None:
        """Register a `callback(state, path)` fired on every state change.

        Called on whichever thread changed the state; in this app that is
        always the Tk main thread, since every call site is a widget
        command.
        """
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback(self._state, self._path)
            except Exception:  # noqa: BLE001 - a dead widget must not break audio
                self.remove_listener(callback)

    # -- state -----------------------------------------------------------
    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def state(self) -> str:
        if self._state == PLAYING:
            # pygame doesn't call us back when a track ends on its own.
            try:
                if not self._mixer().music.get_busy():
                    self._state = STOPPED
                    self._path = None
            except PreviewError:
                pass
        return self._state

    def is_playing(self) -> bool:
        return self.state == PLAYING

    def is_paused(self) -> bool:
        return self._state == PAUSED

    def is_current(self, path: Optional[str]) -> bool:
        if not path or not self._path:
            return False
        return os.path.abspath(path) == os.path.abspath(self._path)

    # -- transport -------------------------------------------------------
    def play(self, path: str, volume: Optional[float] = None) -> None:
        if not path or not os.path.isfile(path):
            raise PreviewError(f"The audio file could not be found:\n{path}")
        mixer = self._mixer()
        if volume is not None:
            self._volume = _clamp01(volume)
        try:
            mixer.music.load(path)
            mixer.music.set_volume(self._volume)
            mixer.music.play()
        except Exception as exc:  # noqa: BLE001
            self._state = STOPPED
            self._path = None
            self._notify()
            raise PreviewError(
                f"'{os.path.basename(path)}' could not be played.\n\n"
                f"Details: {exc}") from exc
        self._path = path
        self._state = PLAYING
        self._notify()

    def pause(self) -> None:
        if self._state != PLAYING:
            return
        try:
            self._mixer().music.pause()
        except PreviewError:
            return
        self._state = PAUSED
        self._notify()

    def resume(self) -> None:
        if self._state != PAUSED:
            return
        try:
            self._mixer().music.unpause()
        except PreviewError:
            return
        self._state = PLAYING
        self._notify()

    def toggle(self, path: str, volume: Optional[float] = None) -> str:
        """Play `path`, or pause/resume it when it's already the loaded one.
        Returns the resulting state.
        """
        if self.is_current(path):
            if self.state == PLAYING:
                self.pause()
                return self._state
            if self._state == PAUSED:
                self.resume()
                return self._state
        self.play(path, volume=volume)
        return self._state

    def stop(self) -> None:
        pygame = self._module()
        if pygame is not None:
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
            except Exception:  # noqa: BLE001
                pass
        changed = self._state != STOPPED or self._path is not None
        self._state = STOPPED
        self._path = None
        if changed:
            self._notify()

    def unload(self) -> None:
        """Stop and release the file handle.

        Windows keeps a lock on whatever pygame has loaded, so this has to
        run before the editor overwrites or deletes a file that might be
        the one currently loaded.
        """
        self.stop()
        pygame = self._module()
        if pygame is None:
            return
        try:
            if pygame.mixer.get_init() and hasattr(pygame.mixer.music, "unload"):
                pygame.mixer.music.unload()
        except Exception:  # noqa: BLE001 - older pygame has no unload()
            pass

    # -- volume ----------------------------------------------------------
    def set_volume(self, volume: float) -> None:
        """Preview-only gain. This is a property of the output stream, so
        it never touches the file on disk.
        """
        self._volume = _clamp01(volume)
        pygame = self._module()
        if pygame is None:
            return
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.set_volume(self._volume)
        except Exception:  # noqa: BLE001
            pass

    def get_volume(self) -> float:
        return self._volume

    # -- position --------------------------------------------------------
    def position(self) -> float:
        """Seconds of playback elapsed since play() was called, or 0.0.

        pygame reports position relative to the start of the stream it is
        playing, which for the editor is the trimmed preview clip -- the
        caller adds its own offset.
        """
        pygame = self._module()
        if pygame is None or self._state == STOPPED:
            return 0.0
        try:
            millis = pygame.mixer.music.get_pos()
        except Exception:  # noqa: BLE001
            return 0.0
        return max(0.0, millis / 1000.0) if millis and millis > 0 else 0.0


def _clamp01(value) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, value))


_PLAYER = PreviewPlayer()


def get_player() -> PreviewPlayer:
    """The one preview player shared by the song list and the editor."""
    return _PLAYER
