# MEF Builder

A dark-mode, point-and-click tool to build and maintain **Music Expanded Framework (MEF)** music mods for RimWorld—without hand-editing XML.

## What it does
- **Real-time previews:** Live `tracks.xml` and `theme.xml` as you edit.
- **Ambient by default:** Tracks start as Ambient; assign cues when needed.
- **Cues & cueData:** MainMenu, Credits, Battle (auto-adds `<tense>true</tense>`), and **Custom** with `cueData`.
- **Allowed biomes:** Tick vanilla biomes to emit `<allowedBiomes>…</allowedBiomes>`.
- **Clean labels:** Auto-fill label from filename + global **Label Prefix** (e.g., `Fallout Sonora – Theme`).
- **Track reuse:** One audio file can appear under multiple cues (separate `<defName>` entries).
- **Multi-Def projects:** Manage multiple game “Defs” (e.g., FF7 + FF8) in one build.
- **Icons:** Per-Def icon picker + base name editor for `<iconPath>UI/Icons/<name>` with live preview.
- **Open & Overwrite:** Open an existing MEF mod, tweak cues/labels/icons, and overwrite just the XML.
- **Safety rails:** Validates Name/Package ID/versions/icons/tracks; clear prompts before build/overwrite.

## Quick start
1. **About:**  
   - Name starts with `Music Expanded: `  
   - Package ID starts with `musicexpanded.` (e.g., `musicexpanded.fallout`)  
   - Select supported versions (1.3–2.0). Dependencies auto-mapped: `<1.5 → musicexpanded.framework`, `≥1.5 → zal.mef`.
2. **Defs:**  
   - Add a Def (game/collection).  
   - Add `.ogg` files (files or folder).  
   - Assign cues, optional `cueData`, allowed biomes, and per-track labels.
3. **Icon:**  
   - Select which Def to edit (dropdown).  
   - Set icon base name and PNG file (preview shown).

## Build vs Overwrite
- **Build** (creates new mod folder; copies audio; writes About/Defs/Textures):
```text
<YourMod>/
  About/ (About.xml, Preview.png?, modicon.png?)
  Defs/<Def>/(tracks.xml, theme.xml)
  Sounds/MusicExpanded/<ContentFolder>/<NNN>. Title.ogg
  Textures/UI/Icons/<iconBase>.png
