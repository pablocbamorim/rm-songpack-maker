"""Optional audio preview backend."""


def play_file(path):
    from importlib import import_module

    try:
        pygame = import_module("pygame")
    except ImportError as exc:
        raise RuntimeError(
            "Audio preview requires pygame; install it with 'pip install pygame'."
        ) from exc

    pygame.mixer.init()
    pygame.mixer.music.load(path)
    pygame.mixer.music.play()
