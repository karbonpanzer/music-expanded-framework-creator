## Highlights

- **End-to-end MEF authoring**
  - **About.xml** editor (supports versions **1.3 → 2.0**; auto-maps dependency to `musicexpanded.framework` for <1.5 and `zal.mef` for ≥1.5).
  - **Defs workspace** with multiple **Def**s per project (e.g., “FFVII”, “FFVIII”).
  - **Live XML previews:** right-side tabs for `tracks.xml` and `theme.xml` update in real time.

- **Track workflow built for speed**
  - **Add files** or **Add folder** (recursive) for `.ogg`.
  - Auto-fills **Label** from file name (cleaned); **Label Prefix** applies to all tracks in a Def.
  - **Cue editor** with **Apply Cue** / **Remove Cue**, supports:
    - Ambient (default for all tracks until changed)
    - MainMenu, Credits
    - BattleSmall, BattleMedium, BattleLarge, BattleLegendary (auto-adds `<tense>true</tense>`)
    - Custom + **cueData** (base game & DLC events you specify)
  - **Allowed Biomes** per-use (optional).

- **Standards & structure baked in**
  - `clipPath` uses `MusicExpanded/<GameFolder>/<NNN>. <Title>` (**no `.ogg`** suffix).
  - Tracks grouped in this exact order with separators:
    1) Ambient (No Cue)  
    2) MainMenu & Credits  
    3) Battle (Small/Medium/Large/Legendary)  
    4) Custom Cues
  - `theme.xml` lists Defs in the same grouped order and points `iconPath` to **UI/Icons/<IconName>**.

- **Icons made simple**
  - Per-Def **Icon name** (no `.png`) + **Browse** to select the PNG.
  - Live icon preview; auto-copies to **Textures/UI/Icons/<IconName>.png** on build.

- **Open & overwrite existing mods**
  - Open an on-disk MEF mod → parse About, Defs, tracks/cues, icon name.
  - **Overwrite** updates `tracks.xml` / `theme.xml` in-place (keeps audio & About).

- **Project save/load**
  - Save to a single `.mefproj` (JSON) and reopen later.

- **Responsive UI**
  - Panels stretch, editors and previews have scrollbars, works windowed or full-screen.

- **Preflight checks**
  - Before **Build** (export) or **Overwrite** (update opened mod), shows stats + issues and asks for confirmation.

---

## Quick start

1. **Run the app**
   - Windows: `py -3w "MEF Creator.py"`
   - macOS/Linux: `python3 "MEF Creator.py"`

2. **About tab**
   - **Name:** start with `Music Expanded: ` and finish it (required).
   - **Package ID:** must start with `musicexpanded.` and include your suffix (required).
   - Tick supported versions (1.3 → 2.0).
   - (Optional) choose **Preview.png** and **modicon.png**.

3. **Defs tab**
   - **Add new Def…** (e.g., `Fallout Sonora`). Required before adding tracks.
   - Set **Label Prefix** (defaults to the Def name).
   - **Add files…** or **Add folder…** for `.ogg`.
   - Select tracks → choose **Cue** (Ambient/Main/Credits/Battle/Custom) → **Apply Cue**.
     - For **Custom**, fill **cueData**.
     - Toggle **Allowed Biomes** if needed.
     - To change back, use **Remove Cue**.
   - Watch the right-side **tracks.xml/theme.xml** previews update.

4. **Icon tab**
   - Pick the **icon PNG** and set the **Icon name** (no `.png`). Preview confirms.

5. **Build vs. Overwrite**
   - **Build:** exports a self-contained mod folder (About, Defs, Sounds, Textures).
   - **Overwrite:** when a mod is **opened**, updates only `tracks.xml` & `theme.xml`.

---

## Output layout

```text
<MyChosenOutput><ModFolder>
├─ About
│  ├─ About.xml
│  ├─ Preview.png (optional)
│  └─ modicon.png (optional)
├─ Defs
│  └─ <DefFolder>
│     ├─ tracks.xml
│     └─ theme.xml
├─ Sounds
│  └─ MusicExpanded
│     └─ <GameFolder>\   # 001. Title.ogg, 002. Title.ogg, ...
└─ Textures
   └─ UI
      └─ Icons
         └─ <IconName>.png
```

---

## Build a binary (no Python required for end users)

**PyInstaller** (recommended):

```bat
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip pyinstaller
pyinstaller --onefile --windowed --icon app.ico "MEF Creator.py"
```

You'll get `dist\MEF Builder.exe`. Ship that file.

**Nuitka** (optimized, slower build):

```bat
.venv\Scripts\activate
pip install nuitka
python -m nuitka "MEF Creator.py" --onefile --windows-console-mode=disable --enable-plugin=tk-inter --output-filename="MEF Builder.exe"
```

---

## FAQ

**The script won’t run.**  
Install Python first — Windows/macOS installers from [python.org](https://www.python.org/) include Tkinter.  
On Linux (Debian/Ubuntu and similar), install Tk bindings too:
```bash
sudo apt install python3 python3-tk
```

**MEF settings complain or my theme can’t be selected.**  
Make sure each Def has an **icon** set. The builder copies it to:
```
Textures/UI/Icons/<IconName>.png
```

**Why do battle tracks feel different?**  
Battle cues auto-add:
```xml
<tense>true</tense>
```
per MEF expectations.

**Where is “ambient” in the XML?**  
Ambient tracks **don’t** have a `<cue>` tag. The UI shows **Ambient** so it’s clear the track is used.

---

## Credits & links

- **Framework:** https://github.com/Music-Expanded/music-expanded-framework  
- **Author:** karbonpanzer  
- **This tool:** MEF Builder (v2.7.4)
  
