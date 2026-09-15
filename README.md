<p align="center">
  <img src="assets/SoundpackMaker512.png" alt="Soundpack Maker">
</p>
# ReactiveMusic Songpack Maker

A desktop editor for creating and maintaining songpacks for the [ReactiveMusic](https://github.com/CircuitLord/ReactiveMusic) Minecraft mod.

ReactiveMusic songpacks are folders containing a `ReactiveMusic.yaml` configuration file and a `music` folder with the audio files referenced by that configuration. The mod loads songpacks from Minecraft's `resourcepacks` folder, even though songpacks are not conventional resource packs; this is simply how the mod makes them available through its configuration UI.

This program provides a graphical interface for building that YAML instead of editing the configuration by hand. It can scan a music folder, create song entries, configure event conditions, manage priority, and preserve conditions that the GUI does not recognize.

## What it does
![alt text](.assets/showcase.png)
The editor currently provides:

- Songpack metadata editing: name, version, author, description, credits, music switch speed, and music delay length.
- Music-folder scanning for `.mp3`, `.ogg`, and `.wav` files. The editor uses the filename without its extension as the song identifier.
- Condition editing for ReactiveMusic's fixed event categories: special events, time, weather, world height, entities, actions, location, and combat.
- Biome conditions, including `BIOME=` and `BIOMETAG=` conditions, with OR/AND combination controls.
- Custom biome and biome-tag definitions with custom display colors, saved as `biome_customization.json` alongside the songpack.
- Dimension conditions using `DIM=`.
- Nearby-block conditions using `BLOCK=` and a minimum block count within ReactiveMusic's 25-block detection radius.
- Advanced entry behavior such as `allowFallback`, `forceStopMusicOnChanged`, `forceStopMusicOnValid`, `forceStopMusicOnInvalid`, `forceStartMusicOnValid`, and `forceChance`.
- A text area for custom or unrecognized raw conditions. Existing YAML conditions that cannot be represented by the structured editor are preserved rather than silently discarded.
- Automatic rarity/specificity scoring and a recommended priority order. More specific conditions are placed before broader conditions because ReactiveMusic evaluates entries from the top of the list and uses the first matching entry.
- Manual priority reordering by dragging, plus Move Up/Move Down controls.
- A variety helper that can identify broader entries whose songs could also be mixed into a more specific entry's rotation.
- Search/filtering of the song entry list and visual warnings for entries with no conditions, since such entries always match.

The priority score is an editor-side heuristic. It is not a ReactiveMusic setting and does not change the mod's own song-selection algorithm.

## Windows installation

The repository builds a standalone Windows executable with GitHub Actions. There is currently no traditional installer: `SoundpackMaker.exe` is a portable executable.

1. Open the repository's **Actions** page.
2. Select the **Build Windows executable** workflow.
3. Open the latest successful workflow run.
4. Under **Artifacts**, download `SoundpackMaker-Windows`.
5. Extract the downloaded ZIP.
6. Run `SoundpackMaker.exe`.

The workflow uses Python 3.12 to build the executable with PyInstaller. The resulting executable is bundled, so Python does not need to be installed on the machine where you run the Windows build.

If there is no recent artifact, the workflow can be started manually from the Actions page using **Run workflow**. The workflow also runs automatically whenever `main` is updated.

## Running from source

If you prefer to run the Python version directly, use Python 3.12 or another compatible Python 3 version with Tkinter available.

```text
python -m pip install -r requirements.txt
python main.py
```

On Windows, Tkinter is normally included with the standard Python installer. If the program reports that Tkinter is missing, install Python from the official Python distribution with the standard GUI components enabled.

## Creating a songpack

### 1. Start a new songpack

Open the program and use **File > New Songpack**.

Alternatively, you can immediately use **Load Music Folder…** and let the editor create blank entries for the audio files it finds.

### 2. Fill in Songpack Info

Open the **Songpack Info** tab and set the songpack's metadata.

The important fields are:

- **Songpack Name** — the name/identifier displayed by ReactiveMusic.
- **Version** — the version string of your songpack, not the editor's version.
- **Author**, **Description**, **Credits** — metadata written to the YAML.
- **Music Switch Speed** — `INSTANT`, `SHORT`, `NORMAL`, or `LONG`.
- **Music Delay Length** — `NONE`, `SHORT`, `NORMAL`, or `LONG`.

The editor also shows the detected YAML entries root key. Existing files are inspected when loaded; new songpacks use `entries` unless you change it.

### 3. Load your music

Go to **Music & Conditions** and click **Load Music Folder…**.

Select the folder containing your audio files. The editor scans `.mp3`, `.ogg`, and `.wav` files and creates one entry per new filename stem.

For example:

```text
music/
├── Route 10.mp3
├── Battle Theme.ogg
└── Cave.wav
```

becomes entries referring to:

```text
Route 10
Battle Theme
Cave
```

The editor does not currently copy those audio files into the final songpack when you use **Save Config…**. You must make sure the referenced audio files are present in the songpack's `music` folder yourself.

### 4. Configure when each song can play

Select an entry on the left. The condition editor on the right is divided into the same categories used by ReactiveMusic.

Fixed conditions are grouped so that checked options within a category are OR'd. For example, checking `RAIN` and `STORM` means either condition can satisfy that category.

Different condition categories are represented as separate YAML event items, which makes them AND conditions. For example:

```yaml
- events: ["DAY", "BIOME=forest"]
  songs:
    - "MySong"
```

means the entry requires both daytime and a matching forest biome.

The editor also supports the documented dynamic condition types:

```text
BIOME=...
BIOMETAG=...
DIM=...
BLOCK=...,count
```

Biome names are soft-matched by ReactiveMusic, so a partial biome name can be useful. Biome tags are broader and can provide compatibility across modded biomes when those biomes use the relevant conventional tags.

### 5. Use the advanced options when necessary

The **Advanced / Fallback Behaviour** section exposes ReactiveMusic's advanced entry properties.

`allowFallback` is particularly useful for rare or one-off events. When enabled, once the entry's own songs have been exhausted, ReactiveMusic can fall through to another valid entry instead of repeatedly selecting the same narrow entry.

The force-stop/start options should be used when a song needs to react immediately to an event becoming valid or invalid. `forceChance` controls the chance of those forced transitions when the relevant force behavior is enabled.

### 6. Check priority

Open the **Priority Order** tab.

ReactiveMusic evaluates songpack entries from top to bottom and plays the first entry whose conditions are currently valid. Because of that, a highly specific entry generally needs to be above a broad entry that would also match the same situation.

Use **Auto-arrange by rarity (recommended)** to sort entries by the editor's specificity score. You can then drag entries manually or use **Move Up** and **Move Down** if the resulting order is not what you want.

Entries with no conditions are highlighted because they always match. These should normally be kept low in the priority list unless that behavior is intentional.

### 7. Save the songpack

Use **File > Save Config…** and choose the folder where the songpack should be stored.

The editor writes:

```text
Your Songpack/
├── ReactiveMusic.yaml
└── biome_customization.json
```

The second file is editor metadata for custom biome/biome-tag display colors; ReactiveMusic itself does not use it for its event logic.

Create a `music` subfolder and place all referenced audio files there:

```text
Your Songpack/
├── ReactiveMusic.yaml
├── biome_customization.json
└── music/
    ├── Route 10.mp3
    ├── Battle Theme.ogg
    └── Cave.wav
```

If you loaded an existing songpack, the editor will preserve its detected entries root key and supported metadata when saving.

## Installing the finished songpack in Minecraft

ReactiveMusic's songpack documentation places songpacks in Minecraft's `resourcepacks` directory. Despite the directory name, these songpacks are selected through ReactiveMusic rather than behaving like normal resource packs.

A typical layout is:

```text
.minecraft/
└── resourcepacks/
    └── My Songpack/
        ├── ReactiveMusic.yaml
        ├── biome_customization.json
        └── music/
            ├── Song A.mp3
            └── Song B.mp3
```

Launch Minecraft with ReactiveMusic installed and open the ReactiveMusic songpack menu with:

```text
/reactivemusic
```

Select the songpack to start playing it.

## Testing and debugging

The ReactiveMusic documentation recommends enabling debug mode while testing a songpack. Debug mode makes songs switch whenever their events become valid and removes silence gaps, which makes condition testing much easier.

ReactiveMusic also provides:

```text
/reactivemusic toggleLogging
```

for real-time logging of what the mod is doing.

If you are working with nearby-block conditions, use:

```text
/reactivemusic logBlockCounter
```

to see the nearby block counts and choose an appropriate minimum count.

You can reload a songpack after making changes by selecting another songpack and then selecting yours again, without restarting Minecraft.

## Supported ReactiveMusic conditions

The editor covers the fixed event types documented by ReactiveMusic:

| Category | Conditions |
| --- | --- |
| Special | `MAIN_MENU`, `CREDITS`, `HOME` |
| Time | `DAY`, `NIGHT`, `SUNRISE`, `SUNSET` |
| Weather | `RAIN`, `SNOW`, `STORM` |
| World height | `UNDERWATER`, `UNDERGROUND`, `DEEP_UNDERGROUND`, `HIGH_UP` |
| Entities | `NEARBY_MOBS`, `MINECART`, `BOAT`, `HORSE`, `PIG` |
| Actions | `FISHING`, `DYING` |
| Location | `VILLAGE` |
| Combat | `BOSS` |
| Dynamic | `BIOME=...`, `BIOMETAG=...`, `DIM=...`, `BLOCK=...,count` |

The editor also preserves raw conditions that it does not recognize, so loading and saving a hand-written songpack should not silently throw away an unfamiliar event expression.

## YAML compatibility notes

The underlying ReactiveMusic format is YAML, so indentation and structure matter. The editor handles YAML generation for you, but manually editing the generated file should be done carefully.

The official ReactiveMusic documentation recommends using a YAML-aware editor such as VS Code when editing songpacks by hand.

For the full ReactiveMusic songpack format, see the official [Making Songpacks documentation](https://github.com/CircuitLord/ReactiveMusic/blob/master/docs/MAKING_SONGPACKS.md).

## Project version

The editor build currently uses a four-part version number in the form `0.x.y.z` and displays it in the Help menu. The repository follows the project's versioning convention: `z` is used for smaller fixes/iterations, `y` for a successfully completed larger feature, and `x` for a bundle of larger features.

Current editor build: `0.1.4.2`.

## License and upstream project

This tool is an independent editor for the ReactiveMusic songpack format. ReactiveMusic itself is developed by CircuitLord. Refer to the respective repositories for their licensing and distribution terms.
