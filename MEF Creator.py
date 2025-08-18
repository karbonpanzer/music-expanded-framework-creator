#!/usr/bin/env python3
# mef_builder_gui_v2_6_2.py
# v2.6.2 — Icon tab DEF selector, icon name editor, cue button text fixes, show loaded-from paths, layout polish, dark mode

import re, shutil, webbrowser, os, math
from pathlib import Path
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

APP_TITLE = "MEF Builder v2.6.2"

ABOUT_VERSIONS = [f"1.{i}" for i in range(3,10)] + ["2.0"]  # 1.3…1.9, 2.0
BATTLE_CUES = {"BattleSmall","BattleMedium","BattleLarge","BattleLegendary"}
DEFAULT_BIOMES = [
	"TemperateForest","BorealForest","Tundra","AridShrubland","Desert",
	"TropicalRainforest","TemperateSwamp","TropicalSwamp","IceSheet","SeaIce"
]
INVALID_FS = r'<>:"/\\|?*'

# ---- Dark theme colors
CLR_BG   = "#1e1e1e"
CLR_FG   = "#e6e6e6"
CLR_ALT  = "#252526"
CLR_ACC  = "#007acc"
CLR_MID  = "#3c3c3c"
CLR_SEL  = "#094771"

def apply_dark_mode(root: tk.Tk):
	style = ttk.Style(root)
	try: style.theme_use("clam")
	except: pass
	root.configure(bg=CLR_BG)
	style.configure(".", background=CLR_BG, foreground=CLR_FG, fieldbackground=CLR_ALT, bordercolor=CLR_MID, focuscolor=CLR_ACC)
	for n in ("TFrame","TLabelframe","TLabelframe.Label","TLabel","TButton","TEntry","TCheckbutton","TMenubutton",
	          "TNotebook","TNotebook.Tab","TCombobox","Horizontal.TScrollbar","Vertical.TScrollbar","TSeparator"):
		style.configure(n, background=CLR_BG, foreground=CLR_FG)
	style.map("TButton", background=[("active", CLR_MID), ("pressed", CLR_MID)])
	style.configure("TEntry", fieldbackground=CLR_ALT)
	style.configure("TCombobox", fieldbackground=CLR_ALT)
	style.configure("TNotebook", background=CLR_BG, bordercolor=CLR_MID)
	style.configure("TNotebook.Tab", background=CLR_ALT, lightcolor=CLR_ALT, bordercolor=CLR_MID, padding=(10,5))
	style.map("TNotebook.Tab", background=[("selected", CLR_MID)], foreground=[("selected", CLR_FG)])
	style.configure("Treeview", background=CLR_ALT, fieldbackground=CLR_ALT, foreground=CLR_FG, bordercolor=CLR_MID)
	style.configure("Treeview.Heading", background=CLR_MID, foreground=CLR_FG)
	style.map("Treeview", background=[("selected", CLR_SEL)])
	root.option_add("*Menu*background", CLR_BG)
	root.option_add("*Menu*foreground", CLR_FG)
	root.option_add("*Menu*activeBackground", CLR_MID)
	root.option_add("*Menu*activeForeground", CLR_FG)

def sanitize_component(s: str) -> str:
	s2 = "".join("_" if c in INVALID_FS else c for c in s)
	return s2.rstrip(" .")

def sanitize_simple(name: str) -> str:
	return re.sub(r'[^A-Za-z0-9]', '', name)

def infer_game_code(label: str) -> str:
	toks = re.findall(r'[A-Za-z0-9]+', label or "")
	return ("".join(t[0] for t in toks)[:3] or "GME").upper()

def infer_title_from_filename(fname: str, game_label: str, content_folder: str) -> str:
	title = re.sub(r'\.ogg$', '', fname, flags=re.IGNORECASE)
	title = re.sub(r'^\s*\d{1,3}\s*[\.\-]\s*', '', title)
	prefix = r'^\s*(?:' + re.escape(game_label) + r'|' + re.escape(content_folder) + r'|soundtrack|ost)\s*[-–—]\s*'
	title = re.sub(prefix, '', title, flags=re.IGNORECASE)
	title = re.sub(r'\s+', ' ', title)
	return title.strip()

def dep_for_version(v: str):
	try: val = float(v)
	except: val = 99.9
	return ("musicexpanded.framework", "Music Expanded Framework") if val < 1.5 else ("zal.mef", "Music Expanded Framework")

# ---------------- Data models ----------------
class TrackUse:
	def __init__(self, cue_type=None, cue_data="", allowed_biomes=None):
		self.cue_type = cue_type  # None = Ambient
		self.cue_data = (cue_data or "").strip()
		self.allowed_biomes = list(allowed_biomes) if allowed_biomes else []
	def summary(self):
		if self.cue_type is None: return "Ambient"
		if self.cue_type == "Custom": return f'Custom[{self.cue_data}]' if self.cue_data else "Custom"
		return self.cue_type

class Track:
	def __init__(self, idx: int, path: Path, display_title: str, file_title: str):
		self.idx = idx
		self.path = Path(path)
		self.display_title = display_title     # right-side label part (editable)
		self.file_title = file_title           # sanitized for clipPath/filename
		self.uses: list[TrackUse] = [TrackUse()]  # default Ambient

class ProjectDef:
	def __init__(self, label_game: str):
		self.label_game = label_game
		self.game_code = infer_game_code(label_game)
		self.content_folder = sanitize_simple(label_game)
		self.icon_base = self.content_folder
		self.icon_src = ""          # optional picked file path
		self.src_music = ""         # optional memory of where files came from
		self.label_prefix = self.label_game
		self.tracks: list[Track] = []
		self._src_def_dir: Path|None = None  # set if imported

# ---------------- XML builders ----------------
def build_about_xml(name, description_cdata, author, package_id, versions_checked, load_after_lines):
	lines = []
	lines.append('<?xml version="1.0" encoding="utf-8"?>')
	lines.append('<ModMetaData>')
	lines.append(f'\t<name>{name}</name>')
	lines.append('\t<description><![CDATA[' + description_cdata + ']]></description>')
	lines.append(f'\t<author>{author}</author>')
	lines.append(f'\t<packageId>{package_id}</packageId>')
	lines.append('\t\t<supportedVersions>')
	for v in versions_checked:
		lines.append(f'\t\t\t<li>{v}</li>')
	lines.append('\t\t</supportedVersions>')
	lines.append('\t<loadAfter>')
	for la in load_after_lines:
		la = la.strip()
		if la: lines.append(f'\t\t<li>{la}</li>')
	lines.append('\t</loadAfter>')
	lines.append('\t\t<modDependenciesByVersion>')
	for v in versions_checked:
		pkg, disp = dep_for_version(v)
		lines.append(f'\t\t\t<v{v}>')
		lines.append('\t\t\t\t<li>')
		lines.append(f'\t\t\t\t\t<packageId>{pkg}</packageId>')
		lines.append(f'\t\t\t\t\t<displayName>{disp}</displayName>')
		lines.append('\t\t\t\t\t<downloadUrl>https://github.com/Music-Expanded/music-expanded-framework/releases/latest</downloadUrl>')
		lines.append('\t\t\t\t</li>')
		lines.append(f'\t\t\t</v{v}>')
	lines.append('\t\t</modDependenciesByVersion>')
	lines.append('</ModMetaData>')
	return "\n".join(lines) + "\n"

def xml_trackdef(defname, label, clip_path, cue=None, cue_data=None, allowed_biomes=None) -> str:
	buf = []
	buf.append("\t<MusicExpanded.TrackDef>")
	buf.append(f"\t\t<defName>{defname}</defName>")
	buf.append(f"\t\t<label>{label}</label>")
	buf.append(f"\t\t<clipPath>{clip_path}</clipPath>")
	if cue:
		buf.append(f"\t\t<cue>{cue}</cue>")
		if cue == "Custom" and cue_data:
			buf.append(f"\t\t<cueData>{cue_data}</cueData>")
	if cue in BATTLE_CUES:
		buf.append("\t\t<tense>true</tense>")
	if allowed_biomes:
		buf.append("\t\t<allowedBiomes>")
		for b in allowed_biomes:
			buf.append(f"\t\t\t<li>{b}</li>")
		buf.append("\t\t</allowedBiomes>")
	buf.append("\t</MusicExpanded.TrackDef>")
	return "\n".join(buf)

def build_tracks_xml(project_def: ProjectDef):
	def next_defname():
		i = 0
		while True:
			i += 1
			yield f"ME_{project_def.game_code}_{i:03d}"
	gen = next_defname(); next_dn = lambda: next(gen)

	sections = {"ambient": [], "maincredits": [], "battle": [], "custom": []}
	for t in project_def.tracks:
		for use in t.uses:
			defname = next_dn()
			label_left = (project_def.label_prefix or project_def.label_game).strip()
			right = t.display_title.strip() or t.file_title
			label = f"{label_left} – {right}"
			clip = f"MusicExpanded/{project_def.content_folder}/{t.idx:03d}. {t.file_title}"
			entry = {"defname": defname, "label": label, "clip": clip, "cue": None, "cue_data": None, "biomes": use.allowed_biomes or None}
			if use.cue_type is None:
				sections["ambient"].append(entry)
			elif use.cue_type in ("MainMenu","Credits"):
				entry["cue"] = use.cue_type; sections["maincredits"].append(entry)
			elif use.cue_type in BATTLE_CUES:
				entry["cue"] = use.cue_type; sections["battle"].append(entry)
			elif use.cue_type == "Custom":
				entry["cue"] = "Custom"; entry["cue_data"] = use.cue_data; sections["custom"].append(entry)
			else:
				sections["ambient"].append(entry)

	lines = ['<?xml version="1.0" encoding="utf-8"?>', '<Defs>']
	lines.append('\t<!-- Ambient Tracks (No Cue) -->')
	for e in sections["ambient"]:
		lines.append(xml_trackdef(e["defname"], e["label"], e["clip"], e["cue"], e["cue_data"], e["biomes"]))
	lines.append('')
	lines.append('\t<!-- MainMenu and Credits Tracks -->')
	for e in sections["maincredits"]:
		lines.append(xml_trackdef(e["defname"], e["label"], e["clip"], e["cue"], e["cue_data"], e["biomes"]))
	lines.append('')
	lines.append('\t<!-- Battle Tracks (BattleSmall, BattleMedium, BattleLarge, BattleLegendary) -->')
	for e in sections["battle"]:
		lines.append(xml_trackdef(e["defname"], e["label"], e["clip"], e["cue"], e["cue_data"], e["biomes"]))
	lines.append('')
	lines.append('\t<!-- Custom Cues -->')
	for e in sections["custom"]:
		lines.append(xml_trackdef(e["defname"], e["label"], e["clip"], e["cue"], e["cue_data"], e["biomes"]))
	lines.append('</Defs>')
	return "\n".join(lines) + "\n"

def build_theme_xml(project_def: ProjectDef, description_text: str):
	def next_defname():
		i = 0
		while True:
			i += 1
			yield f"ME_{project_def.game_code}_{i:03d}"
	gen = next_defname()
	sec = {"ambient": [], "maincredits": [], "battle": [], "custom": []}
	for t in project_def.tracks:
		for use in t.uses:
			dn = next(gen)
			if use.cue_type is None: sec["ambient"].append(dn)
			elif use.cue_type in ("MainMenu","Credits"): sec["maincredits"].append(dn)
			elif use.cue_type in BATTLE_CUES: sec["battle"].append(dn)
			elif use.cue_type == "Custom": sec["custom"].append(dn)
			else: sec["ambient"].append(dn)

	lines = ['<?xml version="1.0" encoding="utf-8"?>', '<Defs>']
	lines.append('\t<MusicExpanded.ThemeDef>')
	lines.append(f'\t\t<defName>ME_{project_def.game_code}</defName>')
	lines.append(f'\t\t<label>Music Expanded: {project_def.label_game}</label>')
	lines.append(f'\t\t<description>{description_text}</description>')
	lines.append(f'\t\t<iconPath>UI/Icons/{project_def.icon_base}</iconPath>')
	lines.append('\t\t<tracks>')
	lines.append('\t\t\t<!-- Ambient Tracks (No Cue) -->')
	for dn in sec["ambient"]: lines.append(f'\t\t\t<li>{dn}</li>')
	lines.append('\t\t\t<!-- MainMenu and Credits Tracks -->')
	for dn in sec["maincredits"]: lines.append(f'\t\t\t<li>{dn}</li>')
	lines.append('\t\t\t<!-- Battle Tracks (BattleSmall, BattleMedium, BattleLarge, BattleLegendary) -->')
	for dn in sec["battle"]: lines.append(f'\t\t\t<li>{dn}</li>')
	lines.append('\t\t\t<!-- Custom Cues -->')
	for dn in sec["custom"]: lines.append(f'\t\t\t<li>{dn}</li>')
	lines.append('\t\t</tracks>')
	lines.append('\t</MusicExpanded.ThemeDef>')
	lines.append('</Defs>')
	return "\n".join(lines) + "\n"

# ---------------- Import helpers ----------------
def _split_label_pair(lbl: str):
	if lbl is None: return (None, "")
	parts = re.split(r'\s+[-–—]\s+', lbl.strip(), maxsplit=1)
	return (parts[0].strip(), parts[1].strip()) if len(parts)==2 else (None, lbl.strip())

def parse_about_xml(about_dir: Path):
	about_xml = about_dir / "About.xml"
	if not about_xml.exists(): return None
	tree = ET.parse(about_xml); root = tree.getroot()
	def gx(tag):
		node = root.find(tag)
		return node.text if node is not None and node.text is not None else ""
	name = gx("name"); author = gx("author"); pkg = gx("packageId")
	desc_node = root.find("description")
	desc = desc_node.text if desc_node is not None and desc_node.text is not None else ""
	versions = []
	if root.find("supportedVersions") is not None:
		for li in root.find("supportedVersions").iter("li"):
			if li.text: versions.append(li.text.strip())
	load_after = []
	if root.find("loadAfter") is not None:
		for li in root.find("loadAfter").iter("li"):
			if li.text: load_after.append(li.text.strip())
	return {
		"name": name, "author": author, "packageId": pkg,
		"description": desc, "versions": versions, "load_after": load_after,
		"preview": (about_dir / "Preview.png" if (about_dir / "Preview.png").exists() else None),
		"modicon": (about_dir / "modicon.png" if (about_dir / "modicon.png").exists() else None)
	}

def parse_def_folder(def_folder: Path, textures_root: Path) -> ProjectDef|None:
	tracks_xml = def_folder / "tracks.xml"
	theme_xml = def_folder / "theme.xml"
	if not tracks_xml.exists() or not theme_xml.exists():
		return None

	try:
		tree_t = ET.parse(theme_xml); r = tree_t.getroot()
	except Exception:
		return None
	td = r.find(".//MusicExpanded.ThemeDef")
	if td is None:
		return None

	label_node = td.find("label")
	label_text = label_node.text if label_node is not None else ""
	game_label = re.sub(r'^\s*Music Expanded:\s*', '', label_text).strip() or def_folder.name
	icon_path_node = td.find("iconPath")
	icon_base = ""
	if icon_path_node is not None and icon_path_node.text:
		m = re.match(r'^\s*UI/Icons/(.+?)\s*$', icon_path_node.text.strip())
		if m: icon_base = m.group(1)

	defname_node = td.find("defName")
	game_code = None
	if defname_node is not None and defname_node.text:
		m = re.match(r'^\s*ME_([A-Z0-9]+)\s*$', defname_node.text.strip())
		if m: game_code = m.group(1)

	try:
		tree_x = ET.parse(tracks_xml); rt = tree_x.getroot()
	except Exception:
		return None
	track_nodes = rt.findall(".//MusicExpanded.TrackDef")
	if not track_nodes:
		return None

	group = {}
	prefix_candidates = []
	content_folder = None

	for tdnode in track_nodes:
		lbl = tdnode.findtext("label", default="").strip()
		clip = tdnode.findtext("clipPath", default="").strip()

		idx, file_title = None, None
		m = re.match(r'^\s*MusicExpanded/([^/]+)/(\d{3})\.\s*(.+?)\s*$', clip)
		if m:
			content_folder = content_folder or m.group(1)
			try: idx = int(m.group(2))
			except: idx = None
			file_title = sanitize_component(m.group(3))
		else:
			file_title = sanitize_component(Path(clip).name)

		left, right = _split_label_pair(lbl)
		if left: prefix_candidates.append(left)
		display_right = right or file_title

		cue = tdnode.findtext("cue", default="").strip() or None
		cue_data = tdnode.findtext("cueData", default="").strip() if cue == "Custom" else ""
		allowed_biomes = []
		ab = tdnode.find("allowedBiomes")
		if ab is not None:
			for li in ab.iter("li"):
				if li.text: allowed_biomes.append(li.text.strip())

		if clip not in group:
			group[clip] = {"idx": idx, "file_title": file_title, "display": display_right, "uses": []}
		group[clip]["uses"].append(TrackUse(cue, cue_data, allowed_biomes))

	pd = ProjectDef(game_label)
	if game_code: pd.game_code = game_code
	if content_folder:
		pd.content_folder = content_folder
		pd.icon_base = content_folder
	if icon_base:
		pd.icon_base = icon_base
		icon_file = textures_root / f"{icon_base}.png"
		if icon_file.exists():
			pd.icon_src = str(icon_file)

	if prefix_candidates:
		from collections import Counter
		pd.label_prefix = Counter(prefix_candidates).most_common(1)[0][0]
	else:
		pd.label_prefix = pd.label_game

	items = list(group.items())
	def _sortkey(it):
		_, rec = it
		return (rec["idx"] if isinstance(rec["idx"], int) else 9999, rec["file_title"])
	items.sort(key=_sortkey)

	pd.tracks = []
	for i, (clip, rec) in enumerate(items, start=1):
		idx = rec["idx"] if isinstance(rec["idx"], int) else i
		fake_path = Path(f"{rec['file_title']}.ogg")
		t = Track(idx, fake_path, rec["display"], rec["file_title"])
		seen = set(); uses = []
		for u in rec["uses"]:
			key = (u.cue_type, u.cue_data, tuple(u.allowed_biomes))
			if key in seen: continue
			seen.add(key); uses.append(u)
		t.uses = uses if uses else [TrackUse()]
		pd.tracks.append(t)

	pd._src_def_dir = def_folder
	return pd

# ---------------- GUI ----------------
class App(tk.Tk):
	def __init__(self):
		super().__init__()
		self.title(APP_TITLE); self.geometry("1280x900"); self.minsize(1200, 860)

		# About state
		self.about_name = tk.StringVar(value="Music Expanded: ")
		self.about_author = tk.StringVar(value="karbonpanzer")
		self.about_package = tk.StringVar(value="musicexpanded.")
		self.about_versions = {v: tk.BooleanVar(value=(v in ["1.6","2.0"])) for v in ABOUT_VERSIONS}
		self.about_load_after = tk.StringVar(value="musicexpanded.framework\nVanillaExpanded.VEE")
		self.about_desc = "Put your About description here (wrapped in CDATA)."
		self.preview_src = tk.StringVar(value="")
		self.modicon_src = tk.StringVar(value="")

		# Project state
		self.defs: list[ProjectDef] = []
		self.cur_def_idx = tk.IntVar(value=-1)
		self.loaded_mod_dir: Path|None = None

		# Output
		self.out_root = tk.StringVar(value=str(Path.cwd() / "out"))

		# Icon-tab state
		self.icon_src = tk.StringVar(value="")
		self.icon_base_var = tk.StringVar(value="")

		# Build UI
		self._build_ui()
		apply_dark_mode(self)
		self._refresh_all_previews()

	def _build_ui(self):
		# Menubar
		menubar = tk.Menu(self)
		filemenu = tk.Menu(menubar, tearoff=0)
		filemenu.add_command(label="Build (export new folder)", command=self._build, accelerator="Ctrl+B")
		filemenu.add_command(label="Overwrite (update opened mod XMLs)", command=self._overwrite, accelerator="Ctrl+O")
		filemenu.add_separator()
		filemenu.add_command(label="Exit", command=self.destroy)
		menubar.add_cascade(label="File", menu=filemenu)

		projmenu = tk.Menu(menubar, tearoff=0)
		projmenu.add_command(label="Open MEF Mod Folder…", command=self._open_mod_folder)
		projmenu.add_command(label="New (clear project)", command=self._new_project)
		menubar.add_cascade(label="Project", menu=projmenu)

		helpmenu = tk.Menu(menubar, tearoff=0)
		helpmenu.add_command(label="Open ZAL.MEF / MEF GitHub", command=lambda: webbrowser.open_new("https://github.com/Music-Expanded/music-expanded-framework"))
		helpmenu.add_command(label="Open KarbonPanzer GitHub", command=lambda: webbrowser.open_new("https://github.com/karbonpanzer"))
		menubar.add_cascade(label="Help", menu=helpmenu)

		self.config(menu=menubar)
		self.bind_all("<Control-b>", lambda e: self._build())
		self.bind_all("<Control-o>", lambda e: self._overwrite())

		root = ttk.Frame(self, padding=(10,8,10,6)); root.pack(fill="both", expand=True)
		self.tabs = ttk.Notebook(root); self.tabs.pack(fill="both", expand=True)

		# About
		tab_about = ttk.Frame(self.tabs, padding=10); self.tabs.add(tab_about, text="About")
		self._build_about(tab_about)

		# Defs
		tab_defs = ttk.Frame(self.tabs, padding=10); self.tabs.add(tab_defs, text="Defs")
		self._build_defs(tab_defs)

		# Icon (formerly Textures)
		tab_icon = ttk.Frame(self.tabs, padding=10); self.tabs.add(tab_icon, text="Icon")
		self._build_icon(tab_icon)

		# Bottom bar (tighter)
		bar = ttk.Frame(root); bar.pack(fill="x", pady=(8,0))
		self.prev_btn = ttk.Button(bar, text="◀ Previous", command=self._prev_tab); self.prev_btn.pack(side="left")
		self.next_btn = ttk.Button(bar, text="Next ▶", command=self._next_tab); self.next_btn.pack(side="left", padx=(6,12))
		ttk.Label(bar, text="Output root:").pack(side="left")
		ttk.Entry(bar, textvariable=self.out_root, width=52).pack(side="left", padx=6)
		ttk.Button(bar, text="Browse…", command=self._pick_out_root).pack(side="left", padx=(0,10))
		self.overwrite_btn = ttk.Button(bar, text="Overwrite", command=self._overwrite)
		self.overwrite_btn.pack(side="right", padx=(6,0))
		self.build_btn = ttk.Button(bar, text="Build", command=self._build); self.build_btn.pack(side="right")

		self._update_nav(); self._update_overwrite_enabled()

	# ---------- About tab
	def _build_about(self, tab):
		r1 = ttk.Frame(tab); r1.pack(fill="x", pady=(0,6))
		ttk.Label(r1, text="Name:").pack(side="left")
		ttk.Entry(r1, textvariable=self.about_name, width=44).pack(side="left", padx=6)
		self.name_hint = ttk.Label(r1, text="← finish after “Music Expanded: ”"); self.name_hint.pack(side="left")

		r2 = ttk.Frame(tab); r2.pack(fill="x", pady=(0,6))
		ttk.Label(r2, text="Author:").pack(side="left")
		ttk.Entry(r2, textvariable=self.about_author, width=22).pack(side="left", padx=6)
		ttk.Label(r2, text="Package ID:").pack(side="left")
		ttk.Entry(r2, textvariable=self.about_package, width=30).pack(side="left", padx=6)
		self.pkg_hint = ttk.Label(r2, text="← must start with “musicexpanded.”"); self.pkg_hint.pack(side="left")

		def _about_validate(*_):
			ok_name = self.about_name.get().strip() not in ("","Music Expanded:")
			ok_pkg  = (self.about_package.get().strip().startswith("musicexpanded.") and self.about_package.get().strip()!="musicexpanded.")
			self.name_hint.configure(foreground=("#80ff80" if ok_name else "#ff8a80"))
			self.pkg_hint.configure(foreground=("#80ff80" if ok_pkg else "#ff8a80"))
		self.about_name.trace_add("write", _about_validate)
		self.about_package.trace_add("write", _about_validate); _about_validate()

		ttk.Label(tab, text="Supported Versions:").pack(anchor="w")
		grid = ttk.Frame(tab); grid.pack(fill="x", pady=(2,6))
		for i, v in enumerate(ABOUT_VERSIONS):
			ttk.Checkbutton(grid, text=v, variable=self.about_versions[v]).grid(row=i//8, column=i%8, sticky="w", padx=4, pady=2)

		ttk.Label(tab, text="Load After (one per line):").pack(anchor="w")
		ttk.Entry(tab, textvariable=self.about_load_after, width=90).pack(fill="x", pady=(0,6))

		ttk.Label(tab, text="Description (CDATA):").pack(anchor="w")
		self.desc_txt = tk.Text(tab, height=8, width=100, bg=CLR_ALT, fg=CLR_FG, insertbackground=CLR_FG)
		self.desc_txt.insert("1.0", self.about_desc); self.desc_txt.pack(fill="x")

		ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=8)
		imgs = ttk.Frame(tab); imgs.pack(fill="x")
		ttk.Label(imgs, text="Preview.png:").grid(row=0, column=0, sticky="w")
		ttk.Entry(imgs, textvariable=self.preview_src, width=70).grid(row=0, column=1, sticky="w", padx=6)
		ttk.Button(imgs, text="Choose…", command=self._pick_preview).grid(row=0, column=2, sticky="w")
		ttk.Label(imgs, text="modicon.png:").grid(row=1, column=0, sticky="w", pady=(6,0))
		ttk.Entry(imgs, textvariable=self.modicon_src, width=70).grid(row=1, column=1, sticky="w", padx=6, pady=(6,0))
		ttk.Button(imgs, text="Choose…", command=self._pick_modicon).grid(row=1, column=2, sticky="w", pady=(6,0))

	# ---------- Defs tab
	def _build_defs(self, tab):
		# Status (where opened from)
		status = ttk.Frame(tab); status.pack(fill="x", pady=(0,4))
		self.loaded_from_lbl = ttk.Label(status, text="Opened mod: (none)"); self.loaded_from_lbl.pack(side="left")
		self.def_folder_lbl = ttk.Label(status, text="   Def folder: (none)"); self.def_folder_lbl.pack(side="right")

		# Row 1: Add-new-def
		row_add = ttk.Frame(tab); row_add.pack(fill="x", pady=(0,6))
		ttk.Button(row_add, text="Add new Def…", command=self._add_def).pack(side="left")

		# Row 2: Def selector + rename/delete
		h = ttk.Frame(tab); h.pack(fill="x", pady=(0,6))
		ttk.Label(h, text="Def:").pack(side="left")
		self.def_combo = ttk.Combobox(h, state="readonly", width=32, values=[])
		self.def_combo.bind("<<ComboboxSelected>>", self._on_def_combo_select)
		self.def_combo.pack(side="left", padx=6)
		ttk.Button(h, text="Rename…", command=self._rename_def).pack(side="left", padx=4)
		ttk.Button(h, text="Delete", command=self._delete_def).pack(side="left", padx=4)

		# Core fields + Label Prefix
		core = ttk.Frame(tab); core.pack(fill="x", pady=(2,6))
		self.game_label = tk.StringVar(value="")
		self.game_code = tk.StringVar(value="")
		self.content_folder = tk.StringVar(value="")
		self.label_prefix = tk.StringVar(value="")
		ttk.Label(core, text="Game Name:").pack(side="left")
		ttk.Entry(core, textvariable=self.game_label, width=22).pack(side="left", padx=6)
		ttk.Label(core, text="Game Code:").pack(side="left")
		ttk.Entry(core, textvariable=self.game_code, width=8).pack(side="left", padx=6)
		ttk.Label(core, text="Content folder:").pack(side="left")
		ttk.Entry(core, textvariable=self.content_folder, width=18).pack(side="left", padx=6)
		ttk.Label(core, text="Label Prefix:").pack(side="left")
		ttk.Entry(core, textvariable=self.label_prefix, width=28).pack(side="left", padx=6)
		for var in (self.game_label, self.game_code, self.content_folder, self.label_prefix):
			var.trace_add("write", self._on_core_changed)

		# Adders
		srcrow = ttk.Frame(tab); srcrow.pack(fill="x", pady=(0,8))
		ttk.Button(srcrow, text="Add files…", command=self._add_track_files).pack(side="left")
		ttk.Button(srcrow, text="Add folder…", command=self._add_tracks_from_folder).pack(side="left", padx=6)

		# Split
		main_split = ttk.PanedWindow(tab, orient="vertical"); main_split.pack(fill="both", expand=True)
		top = ttk.PanedWindow(main_split, orient="horizontal"); main_split.add(top, weight=4)
		left = ttk.Frame(top); top.add(left, weight=3)
		right = ttk.Frame(top); top.add(right, weight=4)

		self.tracks_tree = ttk.Treeview(left, columns=("idx","file","label","uses"), show="headings", height=18)
		for c,w in (("idx",60),("file",380),("label",340),("uses",300)):
			self.tracks_tree.heading(c, text=c.upper()); self.tracks_tree.column(c, width=w, anchor="w")
		self.tracks_tree.pack(side="left", fill="both", expand=True)
		self.tracks_tree.bind("<<TreeviewSelect>>", lambda e: self._on_track_select())
		scroll = ttk.Scrollbar(left, orient="vertical", command=self.tracks_tree.yview)
		self.tracks_tree.configure(yscroll=scroll.set); scroll.pack(side="left", fill="y")

		self.prev_nb = ttk.Notebook(right); self.prev_nb.pack(fill="both", expand=True)
		tab_tracks = ttk.Frame(self.prev_nb); self.prev_nb.add(tab_tracks, text="tracks.xml")
		tab_theme  = ttk.Frame(self.prev_nb); self.prev_nb.add(tab_theme,  text="theme.xml")
		self.preview_tracks = tk.Text(tab_tracks, wrap="none", bg=CLR_ALT, fg=CLR_FG, insertbackground=CLR_FG)
		self.preview_tracks.pack(fill="both", expand=True); self.preview_tracks.configure(state="disabled")
		self.preview_theme  = tk.Text(tab_theme,  wrap="none", bg=CLR_ALT, fg=CLR_FG, insertbackground=CLR_FG)
		self.preview_theme.pack(fill="both", expand=True); self.preview_theme.configure(state="disabled")

		editor = ttk.LabelFrame(main_split, text="Track editor (assign cues / labels / biomes)")
		main_split.add(editor, weight=1)
		ttk.Label(editor, text="Cue:").grid(row=0, column=0, sticky="w", padx=6, pady=(8,2))
		self.cue_choice = ttk.Combobox(editor, state="readonly", width=22,
			values=["Ambient","MainMenu","Credits","BattleSmall","BattleMedium","BattleLarge","BattleLegendary","Custom"])
		self.cue_choice.current(0); self.cue_choice.grid(row=0, column=1, sticky="w", padx=6, pady=(8,2))

		ttk.Label(editor, text="cueData (Custom):").grid(row=1, column=0, sticky="w", padx=6)
		self.cue_data = tk.StringVar(value="")
		ttk.Entry(editor, textvariable=self.cue_data, width=30).grid(row=1, column=1, sticky="w", padx=6)

		ttk.Label(editor, text="Label Prefix (global):").grid(row=0, column=2, sticky="w", padx=16, pady=(8,2))
		self.label_prefix_entry = ttk.Entry(editor, textvariable=self.label_prefix, width=36)
		self.label_prefix_entry.grid(row=0, column=3, sticky="w", padx=6, pady=(8,2))

		ttk.Label(editor, text="Label (right part):").grid(row=1, column=2, sticky="w", padx=16)
		self.track_label = tk.StringVar(value="")
		ttk.Entry(editor, textvariable=self.track_label, width=36).grid(row=1, column=3, sticky="w", padx=6)

		ttk.Label(editor, text="Allowed Biomes:").grid(row=0, column=4, sticky="nw", padx=16, pady=(8,2))
		abf = ttk.Frame(editor); abf.grid(row=0, column=5, rowspan=2, sticky="w", padx=6, pady=(8,2))
		self.biome_vars = {}
		for i, b in enumerate(DEFAULT_BIOMES):
			var = tk.BooleanVar(value=False); self.biome_vars[b] = var
			ttk.Checkbutton(abf, text=b, variable=var).grid(row=i//5, column=i%5, sticky="w")

		self.replace_ambient = tk.BooleanVar(value=True)
		ttk.Checkbutton(editor, text="Replace default Ambient if first non-ambient is added", variable=self.replace_ambient)\
			.grid(row=2, column=1, columnspan=3, sticky="w", padx=6, pady=(6,4))

		bbar = ttk.Frame(editor); bbar.grid(row=2, column=4, columnspan=2, sticky="e", padx=6, pady=(6,8))
		ttk.Button(bbar, text="Apply Cue",  command=self._apply_queue).pack(side="left")
		ttk.Button(bbar, text="Remove Cue", command=self._remove_queue).pack(side="left", padx=8)

	# ---------- Icon tab (per-Def selector + icon name + preview)
	def _build_icon(self, tab):
		# Header: choose which Def to edit (top-right)
		header = ttk.Frame(tab); header.pack(fill="x", pady=(0,6))
		ttk.Label(header, text="Editing Def:").pack(side="right")
		self.icon_def_combo = ttk.Combobox(header, state="readonly", width=32, values=[])
		self.icon_def_combo.bind("<<ComboboxSelected>>", self._on_icon_def_select)
		self.icon_def_combo.pack(side="right", padx=(6,0))

		# Icon base name (affects theme.xml <iconPath>)
		row_name = ttk.Frame(tab); row_name.pack(fill="x", pady=(0,6))
		ttk.Label(row_name, text="Icon name (no .png):").pack(side="left")
		ttk.Entry(row_name, textvariable=self.icon_base_var, width=40).pack(side="left", padx=6)
		ttk.Label(row_name, text="(theme.xml → UI/Icons/<name>)").pack(side="left")

		# File picker for the PNG that will be copied during Build
		row = ttk.Frame(tab); row.pack(fill="x")
		ttk.Label(row, text="Icon file (.png) for this Def:").pack(side="left")
		ttk.Entry(row, textvariable=self.icon_src, width=70).pack(side="left", padx=6)
		ttk.Button(row, text="Browse…", command=self._pick_def_icon).pack(side="left")

		# Preview
		self.icon_preview = tk.Label(tab, bg=CLR_ALT)
		self.icon_preview.pack(pady=10, ipadx=8, ipady=8)

	# ---------- Nav helpers / guards
	def _update_nav(self):
		i = self.tabs.index(self.tabs.select())
		self.prev_btn.configure(state=("disabled" if i == 0 else "normal"))
		self.next_btn.configure(state=("disabled" if i >= self.tabs.index("end")-1 else "normal"))

	def _update_overwrite_enabled(self):
		self.overwrite_btn.configure(state=("normal" if self.loaded_mod_dir else "disabled"))
		self.loaded_from_lbl.configure(text=f"Opened mod: {self.loaded_mod_dir}" if self.loaded_mod_dir else "Opened mod: (none)")
		# def folder label will be updated when we load a def

	def _prev_tab(self):
		i = self.tabs.index(self.tabs.select())
		if i > 0: self.tabs.select(i-1); self._update_nav()

	def _next_tab(self):
		i = self.tabs.index(self.tabs.select())
		if not self._validate_tab(i): return
		if i == 0 and not self._ensure_at_least_one_def(): return
		if i < self.tabs.index("end")-1:
			self.tabs.select(i+1); self._update_nav()

	def _validate_tab(self, i: int) -> bool:
		if i == 0:
			if self.about_name.get().strip() in ("","Music Expanded:"):
				messagebox.showerror(APP_TITLE, "Finish the Name after “Music Expanded: ”."); return False
			pkg = self.about_package.get().strip()
			if not pkg.startswith("musicexpanded.") or pkg == "musicexpanded.":
				messagebox.showerror(APP_TITLE, "Package ID must start with “musicexpanded.” and include a suffix."); return False
			if not any(v.get() for v in self.about_versions.values()):
				messagebox.showerror(APP_TITLE, "Select at least one Supported Version (1.3–2.0)."); return False
		if i == 1:
			d = self._curdef()
			if not d or not d.tracks:
				messagebox.showerror(APP_TITLE, "Load or add at least one track."); return False
		return True

	def _ensure_at_least_one_def(self) -> bool:
		if self.defs: return True
		while True:
			name = simpledialog.askstring(APP_TITLE, "Create your first Def (e.g., 'Fallout Sonora')", parent=self)
			if name is None:
				messagebox.showerror(APP_TITLE, "You must create a Def to proceed."); return False
			name = name.strip()
			if not name:
				messagebox.showerror(APP_TITLE, "Please enter a non-empty Def name."); continue
			if any(x.label_game.strip().lower() == name.lower() for x in self.defs):
				messagebox.showerror(APP_TITLE, "A Def with that name already exists."); continue
			pd = ProjectDef(name)
			self.defs.append(pd); self.cur_def_idx.set(0)
			self._refresh_all_def_combos(); self._load_def_into_fields(pd)
			return True

	# ---------- Project menu actions
	def _new_project(self):
		if not messagebox.askyesno(APP_TITLE, "Clear current project?"): return
		self.defs.clear(); self.cur_def_idx.set(-1); self.loaded_mod_dir = None
		self.about_name.set("Music Expanded: ")
		self.about_author.set("karbonpanzer")
		self.about_package.set("musicexpanded.")
		for v in self.about_versions.values(): v.set(False)
		self.about_versions["1.6"].set(True); self.about_versions["2.0"].set(True)
		self.about_load_after.set("musicexpanded.framework\nVanillaExpanded.VEE")
		self.preview_src.set(""); self.modicon_src.set("")
		self.game_label.set(""); self.game_code.set(""); self.content_folder.set(""); self.label_prefix.set("")
		self.icon_src.set(""); self.icon_base_var.set("")
		self._refresh_all_def_combos(); self._refresh_tracks_table(); self._refresh_all_previews()
		self._refresh_icon_preview(); self._update_overwrite_enabled()

	def _open_mod_folder(self):
		root = filedialog.askdirectory(title="Open MEF Mod Folder")
		if not root: return
		mod = Path(root)
		about_dir = mod / "About"
		defs_dir = mod / "Defs"
		textures_root = mod / "Textures" / "UI" / "Icons"
		if not about_dir.exists() or not defs_dir.exists():
			messagebox.showerror(APP_TITLE, "This doesn’t look like a MEF mod (missing About/ or Defs/)."); return

		info = parse_about_xml(about_dir)
		if info:
			self.about_name.set(info["name"] or "Music Expanded: ")
			self.about_author.set(info["author"] or "karbonpanzer")
			self.about_package.set(info["packageId"] or "musicexpanded.")
			for v in self.about_versions.values(): v.set(False)
			for v in info["versions"]:
				if v in self.about_versions: self.about_versions[v].set(True)
			self.about_load_after.set("\n".join(info["load_after"]) if info["load_after"] else "musicexpanded.framework\nVanillaExpanded.VEE")
			self.desc_txt.delete("1.0","end"); self.desc_txt.insert("1.0", info["description"] or "")
			if info["preview"]: self.preview_src.set(str(info["preview"]))
			if info["modicon"]: self.modicon_src.set(str(info["modicon"]))

		new_defs = []
		for child in sorted(defs_dir.iterdir()):
			if not child.is_dir(): continue
			if child.name.lower() == "patches": continue
			pd = parse_def_folder(child, textures_root)
			if pd:
				pd._src_def_dir = child
				new_defs.append(pd)

		if not new_defs:
			messagebox.showerror(APP_TITLE, "No valid Defs found (need Defs/<Something>/tracks.xml + theme.xml)."); return

		self.defs = new_defs; self.cur_def_idx.set(0); self.loaded_mod_dir = mod
		self._refresh_all_def_combos(); self._load_def_into_fields(self.defs[0])
		self._update_overwrite_enabled()
		messagebox.showinfo(APP_TITLE, f"Loaded {len(self.defs)} def(s) from:\n{mod}")

	# ---------- Def handling
	def _refresh_all_def_combos(self):
		names = [d.label_game for d in self.defs]
		# Defs tab
		self.def_combo.configure(values=names)
		if 0 <= self.cur_def_idx.get() < len(names):
			self.def_combo.current(self.cur_def_idx.get())
		elif names:
			self.cur_def_idx.set(0); self.def_combo.current(0)
		else:
			self.def_combo.set("")
		# Icon tab
		self.icon_def_combo.configure(values=names)
		if 0 <= self.cur_def_idx.get() < len(names):
			self.icon_def_combo.current(self.cur_def_idx.get())
		elif names:
			self.icon_def_combo.current(0)
		else:
			self.icon_def_combo.set("")

	def _on_def_combo_select(self, _evt=None):
		val = self.def_combo.get()
		for i, d in enumerate(self.defs):
			if d.label_game == val:
				self.cur_def_idx.set(i)
				self._load_def_into_fields(d)
				self.icon_def_combo.current(i)
				return

	def _on_icon_def_select(self, _evt=None):
		val = self.icon_def_combo.get()
		for i, d in enumerate(self.defs):
			if d.label_game == val:
				self.cur_def_idx.set(i)
				self._load_def_into_fields(d)
				self.def_combo.current(i)
				return

	def _load_def_into_fields(self, d: ProjectDef):
		# Defs tab fields
		self.game_label.set(d.label_game)
		self.game_code.set(d.game_code)
		self.content_folder.set(d.content_folder)
		self.label_prefix.set(d.label_prefix or d.label_game)
		# Icon tab fields
		self.icon_src.set(d.icon_src or "")
		self.icon_base_var.set(d.icon_base or d.content_folder or "")
		self._refresh_tracks_table(); self._refresh_all_previews()
		self._refresh_icon_preview()
		self.def_folder_lbl.configure(text=f"Def folder: {d._src_def_dir}" if d._src_def_dir else "Def folder: (new/not from disk)")

	def _add_def(self):
		name = simpledialog.askstring(APP_TITLE, "New Def name")
		if name is None: return
		name = name.strip()
		if not name:
			messagebox.showerror(APP_TITLE, "Please enter a non-empty Def name."); return
		if any(x.label_game.strip().lower() == name.lower() for x in self.defs):
			messagebox.showerror(APP_TITLE, "A Def with that name already exists."); return
		pd = ProjectDef(name)
		self.defs.append(pd)
		self.cur_def_idx.set(len(self.defs)-1)
		self._refresh_all_def_combos(); self._load_def_into_fields(pd)

	def _rename_def(self):
		d = self._curdef()
		if not d: return
		name = simpledialog.askstring(APP_TITLE, "Rename Def", initialvalue=d.label_game)
		if name is None: return
		name = name.strip()
		if not name:
			messagebox.showerror(APP_TITLE, "Please enter a non-empty Def name."); return
		if any(x is not d and x.label_game.strip().lower() == name.lower() for x in self.defs):
			messagebox.showerror(APP_TITLE, "A Def with that name already exists."); return
		d.label_game = name
		if not d.game_code: d.game_code = infer_game_code(name)
		if not d.content_folder: d.content_folder = sanitize_simple(name)
		if not d.icon_base: d.icon_base = d.content_folder
		if not d.label_prefix: d.label_prefix = d.label_game
		self._refresh_all_def_combos(); self._load_def_into_fields(d)

	def _delete_def(self):
		if not self.defs: return
		idx = self.cur_def_idx.get()
		name = self.defs[idx].label_game
		if not messagebox.askyesno(APP_TITLE, f"Delete Def “{name}”?"): return
		self.defs.pop(idx)
		if not self.defs:
			self.cur_def_idx.set(-1)
			self._refresh_all_def_combos()
			self.game_label.set(""); self.game_code.set(""); self.content_folder.set(""); self.label_prefix.set("")
			self.icon_src.set(""); self.icon_base_var.set("")
			self._refresh_tracks_table(); self._refresh_all_previews(); self._refresh_icon_preview()
			self.def_folder_lbl.configure(text="Def folder: (none)")
			return
		self.cur_def_idx.set(max(0, idx-1))
		self._refresh_all_def_combos(); self._load_def_into_fields(self.defs[self.cur_def_idx.get()])

	def _on_core_changed(self, *_):
		d = self._curdef()
		if not d: return
		d.label_game = self.game_label.get().strip() or d.label_game
		d.game_code = self.game_code.get().strip() or d.game_code
		d.content_folder = self.content_folder.get().strip() or d.content_folder
		d.label_prefix = (self.label_prefix.get().strip() or d.label_game)
		self._refresh_all_def_combos()
		self._load_def_into_fields(d)

	# ---------- file pickers & icon preview
	def _pick_out_root(self):
		p = filedialog.askdirectory(title="Pick output folder")
		if p: self.out_root.set(p)
	def _pick_preview(self):
		p = filedialog.askopenfilename(title="Pick Preview.png", filetypes=[("PNG","*.png")])
		if p: self.preview_src.set(p)
	def _pick_modicon(self):
		p = filedialog.askopenfilename(title="Pick modicon.png", filetypes=[("PNG","*.png")])
		if p: self.modicon_src.set(p)
	def _pick_def_icon(self):
		p = filedialog.askopenfilename(title="Pick Def icon (.png)", filetypes=[("PNG","*.png")])
		if not p: return
		self.icon_src.set(p)
		d = self._curdef()
		if d:
			d.icon_src = p
			self._refresh_icon_preview()

	def _refresh_icon_preview(self):
		# keep d.icon_base in sync with entry
		d = self._curdef()
		if d:
			base = self.icon_base_var.get().strip() or d.content_folder or d.icon_base
			d.icon_base = base
		p = self.icon_src.get().strip()
		if not p or not Path(p).exists():
			self.icon_preview.configure(image="", text="(No icon selected)", fg=CLR_FG, bg=CLR_ALT)
			return
		try:
			img = tk.PhotoImage(file=p)
			w, h = img.width(), img.height()
			f = max(w/256, h/256, 1); f = int(math.ceil(f))
			if f > 1: img = img.subsample(f, f)
			self._icon_photo = img
			self.icon_preview.configure(image=self._icon_photo, text="", bg=CLR_ALT)
		except Exception as e:
			self.icon_preview.configure(image="", text=f"(Preview failed: {e})", fg=CLR_FG, bg=CLR_ALT)

	# ---------- tracks loading
	def _add_tracks_from_folder(self):
		d = self._curdef()
		if not d:
			messagebox.showerror(APP_TITLE, "Create/select a Def first."); return
		root = filedialog.askdirectory(title="Add folder of .ogg files (recursive)")
		if not root: return
		files = sorted(Path(root).rglob("*.ogg"), key=lambda p: p.as_posix().lower())
		if not files:
			messagebox.showerror(APP_TITLE, "No .ogg found in that folder."); return
		start = max([t.idx for t in d.tracks], default=0) + 1
		for j, p in enumerate(files):
			disp = infer_title_from_filename(p.name, d.label_game, d.content_folder)
			filet = sanitize_component(disp)
			d.tracks.append(Track(start+j, p, disp, filet))
		self._refresh_tracks_table(); self._refresh_all_previews()

	def _add_track_files(self):
		d = self._curdef()
		if not d:
			messagebox.showerror(APP_TITLE, "Create/select a Def first."); return
		fs = filedialog.askopenfilenames(title="Add .ogg files", filetypes=[("OGG","*.ogg")])
		if not fs: return
		start = max([t.idx for t in d.tracks], default=0) + 1
		for j, fp in enumerate(fs):
			p = Path(fp)
			disp = infer_title_from_filename(p.name, d.label_game, d.content_folder)
			filet = sanitize_component(disp)
			d.tracks.append(Track(start+j, p, disp, filet))
		self._refresh_tracks_table(); self._refresh_all_previews()

	# ---------- table/editor sync
	def _refresh_tracks_table(self):
		for iid in self.tracks_tree.get_children(): self.tracks_tree.delete(iid)
		d = self._curdef()
		if not d: return
		for t in d.tracks:
			self.tracks_tree.insert("", "end",
				values=(f"{t.idx:03d}", t.path.name, t.display_title, ", ".join(u.summary() for u in t.uses)))

	def _on_track_select(self):
		t = self._current_track()
		if not t: return
		self.track_label.set(t.display_title)
		for b in self.biome_vars: self.biome_vars[b].set(False)

	def _current_track(self) -> Track|None:
		d = self._curdef(); sel = self.tracks_tree.selection()
		if not d or not sel: return None
		idx = int(self.tracks_tree.item(sel[0], "values")[0])
		for t in d.tracks:
			if t.idx == idx: return t
		return None

	def _collect_biomes_from_ui(self):
		return [b for b,v in self.biome_vars.items() if v.get()]

	# ---------- Apply Cue / Remove Cue
	def _apply_queue(self):
		t = self._current_track()
		if not t:
			messagebox.showinfo(APP_TITLE, "Select a track first."); return
		cue_disp = self.cue_choice.get()
		if cue_disp == "Ambient":
			new_use = TrackUse(None, "", self._collect_biomes_from_ui())
		elif cue_disp == "Custom":
			cd = self.cue_data.get().strip()
			if not cd:
				messagebox.showerror(APP_TITLE, "cueData required for Custom."); return
			new_use = TrackUse("Custom", cd, self._collect_biomes_from_ui())
		else:
			new_use = TrackUse(cue_disp, "", self._collect_biomes_from_ui())

		if self.replace_ambient.get() and len(t.uses)==1 and t.uses[0].cue_type is None and new_use.cue_type is not None:
			t.uses[0] = new_use
		else:
			def matches(u: TrackUse):
				if new_use.cue_type is None: return u.cue_type is None
				if new_use.cue_type == "Custom": return u.cue_type=="Custom" and u.cue_data==new_use.cue_data
				return u.cue_type == new_use.cue_type
			for i,u in enumerate(list(t.uses)):
				if matches(u):
					t.uses[i] = new_use
					break
			else:
				t.uses.append(new_use)

		t.display_title = self.track_label.get().strip() or t.display_title
		self._refresh_tracks_table(); self._refresh_all_previews()

	def _remove_queue(self):
		t = self._current_track()
		if not t:
			messagebox.showinfo(APP_TITLE, "Select a track first."); return
		cue_disp = self.cue_choice.get()
		def idx_for():
			if cue_disp == "Ambient":
				for i,u in enumerate(t.uses):
					if u.cue_type is None: return i
			elif cue_disp == "Custom":
				cd = self.cue_data.get().strip()
				for i,u in enumerate(t.uses):
					if u.cue_type=="Custom" and u.cue_data==cd: return i
			else:
				for i,u in enumerate(t.uses):
					if u.cue_type == cue_disp: return i
			return -1
		i = idx_for()
		if i < 0:
			messagebox.showinfo(APP_TITLE, "No matching cue on this track to remove."); return
		t.uses.pop(i)
		if not t.uses:
			t.uses = [TrackUse()]
		self._refresh_tracks_table(); self._refresh_all_previews()

	# ---------- previews
	def _refresh_tracks_preview(self):
		d = self._curdef()
		xml = build_tracks_xml(d) if d else "<!-- No Def selected -->\n"
		self.preview_tracks.configure(state="normal"); self.preview_tracks.delete("1.0","end"); self.preview_tracks.insert("1.0", xml); self.preview_tracks.configure(state="disabled")
	def _refresh_theme_preview(self):
		d = self._curdef()
		xml = build_theme_xml(d, f"{d.label_game} music integrated via the Music Expanded Framework.") if d else "<!-- No Def selected -->\n"
		self.preview_theme.configure(state="normal"); self.preview_theme.delete("1.0","end"); self.preview_theme.insert("1.0", xml); self.preview_theme.configure(state="disabled")
	def _refresh_all_previews(self):
		self._refresh_tracks_preview(); self._refresh_theme_preview()

	# ---------- helpers
	def _curdef(self) -> ProjectDef|None:
		idx = self.cur_def_idx.get()
		return self.defs[idx] if 0 <= idx < len(self.defs) else None

	# ---------- Build
	def _build(self):
		if self.about_name.get().strip() in ("","Music Expanded:"):
			messagebox.showerror(APP_TITLE, "About → Name: complete the title after “Music Expanded: ”."); return
		pkg = self.about_package.get().strip()
		if not pkg.startswith("musicexpanded.") or pkg == "musicexpanded.":
			messagebox.showerror(APP_TITLE, "About → Package ID must start with “musicexpanded.” and include a suffix."); return
		versions = [v for v,b in self.about_versions.items() if b.get()]
		if not versions:
			messagebox.showerror(APP_TITLE, "About → select at least one Supported Version."); return
		if not self._ensure_at_least_one_def(): return
		for d in self.defs:
			if not d.tracks:
				messagebox.showerror(APP_TITLE, f"Def “{d.label_game}” has no tracks loaded."); return

		about_modicon = Path(self.modicon_src.get().strip()) if self.modicon_src.get().strip() else None
		missing_icons = [d.label_game for d in self.defs if not (d.icon_src or about_modicon)]
		if missing_icons:
			messagebox.showerror(APP_TITLE, "Icon required.\nPick a per-Def icon on Icon tab OR set About/modicon.png.\nMissing for: " + ", ".join(missing_icons)); return

		outroot = Path(self.out_root.get().strip()); outroot.mkdir(parents=True, exist_ok=True)
		mod_name = simpledialog.askstring(APP_TITLE, "Name the output mod folder")
		if not mod_name: return
		mod_dir = outroot / sanitize_component(mod_name)
		if mod_dir.exists():
			if not messagebox.askyesno(APP_TITLE, f"Folder exists:\n{mod_dir}\n\nOverwrite?"): return
			shutil.rmtree(mod_dir)
		mod_dir.mkdir(parents=True, exist_ok=True)

		about_dir = mod_dir / "About"; about_dir.mkdir(parents=True, exist_ok=True)
		desc = self.desc_txt.get("1.0","end").strip()
		la_lines = [ln for ln in self.about_load_after.get().splitlines() if ln.strip()]
		about_xml = build_about_xml(self.about_name.get().strip(), desc, self.about_author.get().strip(), pkg, versions, la_lines)
		(about_dir / "About.xml").write_text(about_xml, encoding="utf-8", newline="\n")
		if self.preview_src.get().strip(): shutil.copy2(self.preview_src.get().strip(), about_dir / "Preview.png")
		if self.modicon_src.get().strip(): shutil.copy2(self.modicon_src.get().strip(), about_dir / "modicon.png")

		defs_root = mod_dir / "Defs"; defs_root.mkdir(parents=True, exist_ok=True)
		sounds_root = mod_dir / "Sounds" / "MusicExpanded"
		textures_root = mod_dir / "Textures" / "UI" / "Icons"; textures_root.mkdir(parents=True, exist_ok=True)

		dest_folders = set()
		for d in self.defs:
			dfolder_name = sanitize_simple(d.label_game) or d.content_folder or "Game"
			if dfolder_name in dest_folders:
				messagebox.showerror(APP_TITLE, f"Duplicate Def folder name would be created: {dfolder_name}\nRename one of your Defs."); return
			dest_folders.add(dfolder_name)

			dfolder = defs_root / dfolder_name
			dfolder.mkdir(parents=True, exist_ok=True)
			(dfolder / "tracks.xml").write_text(build_tracks_xml(d), encoding="utf-8", newline="\n")
			(dfolder / "theme.xml").write_text(build_theme_xml(d, f"{d.label_game} music integrated via the Music Expanded Framework."), encoding="utf-8", newline="\n")

			icon_target = textures_root / f"{d.icon_base}.png"
			if d.icon_src: shutil.copy2(d.icon_src, icon_target)
			elif self.modicon_src.get().strip(): shutil.copy2(self.modicon_src.get().strip(), icon_target)

			dest_folder = sounds_root / d.content_folder
			dest_folder.mkdir(parents=True, exist_ok=True)
			for t in d.tracks:
				target_name = f"{t.idx:03d}. {t.file_title}.ogg"
				try: shutil.copy2(t.path, dest_folder / target_name)
				except Exception as e: messagebox.showwarning(APP_TITLE, f"Failed to copy {t.path.name}: {e}")

		messagebox.showinfo(APP_TITLE, f"Build complete.\n\n{mod_dir}")

	# ---------- Overwrite (update XMLs in opened mod only)
	def _overwrite(self):
		if not self.loaded_mod_dir:
			messagebox.showerror(APP_TITLE, "Open a MEF mod first (Project → Open MEF Mod Folder…)."); return
		defs_dir = self.loaded_mod_dir / "Defs"
		if not defs_dir.exists():
			messagebox.showerror(APP_TITLE, "Opened mod has no Defs/ directory."); return

		if not messagebox.askyesno(APP_TITLE, "Overwrite tracks.xml and theme.xml for each Def in the opened mod?\n"
			"(Audio files and About.xml are NOT changed.)"):
		 return

		for d in self.defs:
			target = d._src_def_dir if d._src_def_dir else (defs_dir / (sanitize_simple(d.label_game) or d.content_folder or "Game"))
			target.mkdir(parents=True, exist_ok=True)
			(target / "tracks.xml").write_text(build_tracks_xml(d), encoding="utf-8", newline="\n")
			(target / "theme.xml").write_text(build_theme_xml(d, f"{d.label_game} music integrated via the Music Expanded Framework."), encoding="utf-8", newline="\n")

		messagebox.showinfo(APP_TITLE, f"Overwrite complete.\n\n{self.loaded_mod_dir}")

# ---------------- Run ----------------
if __name__ == "__main__":
	app = App()
	app.mainloop()
