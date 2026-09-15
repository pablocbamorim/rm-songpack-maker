"""
app.py
------
The Tkinter GUI for the ReactiveMusic Songpack Editor.

Three tabs:
  1. Songpack Info      -- the global yaml keys (name, author, ...)
  2. Music & Conditions  -- pick a song, check the conditions that should
                            trigger it, see a live preview + rarity score
  3. Priority Order      -- the auto-computed (and freely drag-reorderable)
                            play-priority list

See README.md for the reasoning behind the rarity scoring and the
"variety mixing" fallback helper.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
import customtkinter as ctk

import constants as C
import block_data
yaml_io
import priority
import condition_logic
import biome_customization
import mod_versions
import app_settings
import settings_tab
from models import Songpack, Entry, BiomeCondition, DimensionCondition, BlockCondition


