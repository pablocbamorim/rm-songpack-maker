"""Optional audio preview backend."""

def play_file(path):
    import pygame
    pygame.mixer.init()
    pygame.mixer.music.load(path)
    pygame.mixer.music.play()
