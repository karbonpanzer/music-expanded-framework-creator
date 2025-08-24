#!/usr/bin/env python3
# mef_builder_gui_v3_2_0.py
#
# v3.2.0 — “Everything we talked about” merge
# - Tabs: About, Theme (incl. Def controls), Track.xml, Build
# - One live preview per page (Theme→theme.xml, Track→tracks.xml)
# - Track editor reflowed: never cuts off; tall, single-column Allowed Biomes
# - Multiline Supported Versions + Load After; auto-growing text areas
# - Import MEF mod: parses ALL Def folders; populates Theme + Track views
# - Build & Overwrite buttons in toolbar (always accessible)
# - Dark/Light mode fully themed (scrollbars troughs, text bg, etc.); toggle pinned far right
# - Tooltips on header buttons; keyboard shortcuts (Ctrl+N/L/S/I/B; Ctrl+Shift+O)
# - Bottom Previous/Next navigator across tabs
# - Label Prefix optional; Track Label edits apply immediately; automatic defNames
# - No Icon page; no clone/move-up/move-down; patches ignored
# - Dependencies switch to zal.mef for >= 1.5

import re, shutil, webbrowser, os, json, subprocess, sys, math
from pathlib import Path
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

APP_TITLE = "MEF Builder v3.2.0"

BATTLE_CUES = {"BattleSmall","BattleMedium","BattleLarge","BattleLegendary"}
DEFAULT_BIOMES = [
	"TemperateForest","BorealForest","Tundra","AridShrubland","Desert",
	"TropicalRainforest","TemperateSwamp","TropicalSwamp","IceSheet","SeaIce"
]
INVALID_FS = r'<>:"/\\|?*'

# ---- Dark / Light palettes
PAL_D = dict(bg="#1e1e1e", fg="#e6e6e6", alt="#252526", acc="#007acc", mid="#3c3c3c", sel="#094771", trough="#2a2a2a")
PAL_L = dict(bg="#f3f3f3", fg="#101010", alt="#ffffff", acc="#2b6cb0", mid="#d0d0d0", sel="#cfe7ff", trough="#e4e4e4")

def apply_palette(root: tk.Tk, dark: bool):
	p = PAL_D if dark else PAL_L
	style = ttk.Style(root)
	try: style.theme_use("clam")
	except: pass
	root.configure(bg=p["bg"])
	root._palette = p

	style.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["alt"], bordercolor=p["mid"], focuscolor=p["acc"])
	for n in ("TFrame","TLabelframe","TLabelframe.Label","TLabel","TButton","TEntry","TCheckbutton","TNotebook",
	          "TNotebook.Tab","TCombobox","TSeparator","TPanedwindow"):
		style.configure(n, background=p["bg"], foreground=p["fg"])
	style.configure("TNotebook", background=p["bg"], bordercolor=p["mid"])
	style.configure("TNotebook.Tab", background=p["alt"], lightcolor=p["alt"], bordercolor=p["mid"], padding=(10,5))
	style.map("TNotebook.Tab", background=[("selected", p["mid"])], foreground=[("selected", p["fg"])])

	style.configure("Treeview", background=p["alt"], fieldbackground=p["alt"], foreground=p["fg"], bordercolor=p["mid"])
	style.configure("Treeview.Heading", background=p["mid"], foreground=p["fg"])
	style.map("Treeview", background=[("selected", p["sel"])])

	for s in ("Vertical.TScrollbar","Horizontal.TScrollbar","TScrollbar"):
		style.configure(s, background=p["alt"], troughcolor=p["trough"], bordercolor=p["mid"], arrowcolor=p["fg"])

	root.option_add("*Menu*background", p["bg"])
	root.option_add("*Menu*foreground", p["fg"])
	root.option_add("*Menu*activeBackground", p["mid"])
	root.option_add("*Menu*activeForeground", p["fg"])

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
		tag = "Ambient" if self.cue_type is None else ("Custom" if self.cue_type=="Custom" else self.cue_type)
		if self.cue_type=="Custom" and self.cue_data: tag += f"[{self.cue_data}]"
		if self.allowed_biomes: tag += " [" + ",".join(self.allowed_biomes) + "]"
		return tag

class Track:
	def __init__(self, idx: int, path: Path, display_title: str, file_title: str):
		self.idx = idx
		self.path = Path(path)
		self.display_title = display_title     # shown in game (right part)
		self.file_title = file_title           # sanitized for clipPath/filename
		self.uses: list[TrackUse] = [TrackUse()]  # default Ambient

class ProjectDef:
	def __init__(self, label_game: str):
		self.label_game = label_game
		self.game_code = infer_game_code(label_game)
		self.content_folder = sanitize_simple(label_game)
		self.label_prefix = ""  # OPTIONAL global prefix for labels
		self.theme_description = f"{label_game} music integrated via the Music Expanded Framework."
		self.tracks: list[Track] = []
		self._src_def_dir: Path|None = None

# ---------------- XML builders ----------------
def build_about_xml(name, description_cdata, author, package_id, versions_lines, load_after_lines):
	versions = [ln.strip() for ln in versions_lines if ln.strip()]
	load_after = [ln.strip() for ln in load_after_lines if ln.strip()]
	lines = []
	lines.append('<?xml version="1.0" encoding="utf-8"?>')
	lines.append('<ModMetaData>')
	lines.append(f'\t<name>{name}</name>')
	lines.append('\t<description><![CDATA[' + description_cdata + ']]></description>')
	lines.append(f'\t<author>{author}</author>')
	lines.append(f'\t<packageId>{package_id}</packageId>')
	lines.append('\t\t<supportedVersions>')
	for v in versions:
		lines.append(f'\t\t\t<li>{v}</li>')
	lines.append('\t\t</supportedVersions>')
	lines.append('\t<loadAfter>')
	for la in load_after:
		lines.append(f'\t\t<li>{la}</li>')
	lines.append('\t</loadAfter>')
	lines.append('\t\t<modDependenciesByVersion>')
	for v in versions:
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

def _compose_label(prefix: str, right_part: str) -> str:
	prefix = (prefix or "").strip()
	right = (right_part or "").strip()
	return f"{prefix} – {right}" if prefix else right

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
			label = _compose_label(project_def.label_prefix, t.display_title or t.file_title)
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
	lines.append('\t<!-- Custom Cues (Base Game & DLC) -->')
	for e in sections["custom"]:
		lines.append(xml_trackdef(e["defname"], e["label"], e["clip"], e["cue"], e["cue_data"], e["biomes"]))
	lines.append('</Defs>')
	return "\n".join(lines) + "\n"

def build_theme_xml(project_def: ProjectDef):
	def next_defname():
		i = 0
		while True:
			i += 1
			yield f"ME_{project_def.game_code}_{i:03d}"
	gen = next_defname()
	defnames = []
	for t in project_def.tracks:
		for _use in t.uses:
			defnames.append(next(gen))

	lines = ['<?xml version="1.0" encoding="utf-8"?>', '<Defs>']
	lines.append('\t<MusicExpanded.ThemeDef>')
	lines.append(f'\t\t<defName>ME_{project_def.game_code}</defName>')
	lines.append(f'\t\t<label>Music Expanded: {project_def.label_game}</label>')
	lines.append(f'\t\t<description>{project_def.theme_description}</description>')
	lines.append('\t\t<tracks>')
	lines.append('\t\t\t<!-- tracks listed in the same sequence as tracks.xml -->')
	for dn in defnames:
		lines.append(f'\t\t\t<li>{dn}</li>')
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

def parse_tracks_xml_root(root, into_pd: ProjectDef):
	nodes = root.findall(".//MusicExpanded.TrackDef")
	if not nodes: return False
	group = {}; prefix_candidates = []; content_folder = None
	for tdnode in nodes:
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

		key = clip or file_title
		if key not in group:
			group[key] = {"idx": idx, "file_title": file_title, "display": display_right, "uses": []}
		group[key]["uses"].append(TrackUse(cue, cue_data, allowed_biomes))

	if content_folder:
		into_pd.content_folder = content_folder
	if prefix_candidates:
		from collections import Counter
		into_pd.label_prefix = Counter(prefix_candidates).most_common(1)[0][0]

	items = list(group.items())
	def _sortkey(it):
		_, rec = it
		return (rec["idx"] if isinstance(rec["idx"], int) else 9999, rec["file_title"])
	items.sort(key=_sortkey)

	into_pd.tracks = []
	for i, (_k, rec) in enumerate(items, start=1):
		idx = rec["idx"] if isinstance(rec["idx"], int) else i
		fake_path = Path(f"{rec['file_title']}.ogg")
		t = Track(idx, fake_path, rec["display"], rec["file_title"])
		seen = set(); uses = []
		for u in rec["uses"]:
			key2 = (u.cue_type, u.cue_data, tuple(sorted(u.allowed_biomes)))
			if key2 in seen: continue
			seen.add(key2); uses.append(u)
		t.uses = uses if uses else [TrackUse()]
		into_pd.tracks.append(t)
	return True

def parse_theme_xml_root(root, into_pd: ProjectDef):
	td = root.find(".//MusicExpanded.ThemeDef")
	if td is None: return False
	label_node = td.find("label")
	if label_node is not None and label_node.text:
		into_pd.label_game = re.sub(r'^\s*Music Expanded:\s*', '', label_node.text.strip())
	defname_node = td.find("defName")
	if defname_node is not None and defname_node.text:
		m = re.match(r'^\s*ME_([A-Z0-9]+)\s*$', defname_node.text.strip())
		if m: into_pd.game_code = m.group(1)
	desc_node = td.find("description")
	if desc_node is not None and desc_node.text is not None:
		into_pd.theme_description = desc_node.text
	return True

def parse_def_folder(def_folder: Path) -> ProjectDef|None:
	tracks_xml = def_folder / "tracks.xml"
	theme_xml = def_folder / "theme.xml"
	if not tracks_xml.exists() or not theme_xml.exists():
		return None
	try:
		root_theme = ET.parse(theme_xml).getroot()
		root_tracks = ET.parse(tracks_xml).getroot()
	except Exception:
		return None
	pd = ProjectDef(def_folder.name)
	if not parse_theme_xml_root(root_theme, pd): return None
	if not parse_tracks_xml_root(root_tracks, pd): return None
	pd._src_def_dir = def_folder
	return pd

# ---------------- GUI ----------------
class App(tk.Tk):
	def __init__(self):
		super().__init__()
		self.title(APP_TITLE); self.geometry("1360x900"); self.minsize(1120, 780)

		self._dark = True

		# About state
		self.about_name = tk.StringVar(value="Music Expanded: ")
		self.about_author = tk.StringVar(value="karbonpanzer")
		self.about_package = tk.StringVar(value="musicexpanded.")
		self.about_versions_text_default = "1.6\n2.0"
		self.about_load_after_default = "musicexpanded.framework\nVanillaExpanded.VEE"
		self.preview_src = tk.StringVar(value="")
		self.modicon_src = tk.StringVar(value="")

		# Project state
		self.defs: list[ProjectDef] = []
		self.cur_def_idx = tk.IntVar(value=-1)
		self.loaded_mod_dir: Path|None = None

		# Output
		self.out_root = tk.StringVar(value=str(Path.cwd() / "out"))

		# track/theme text widgets for palette/auto-size
		self._tk_texts: list[tk.Text] = []
		self._auto_grow_map: dict[tk.Text, tuple[int,int]] = {}

		self._build_ui()
		apply_palette(self, self._dark)
		self._repaint_texts()
		self._refresh_previews()
		self._update_toolbar_states()

	# ---------- UI
	def _build_ui(self):
		# Toolbar (left actions, right theme toggle)
		bar = ttk.Frame(self, padding=(10,6,10,0)); bar.pack(fill="x")
		for i in range(16): bar.columnconfigure(i, weight=0)
		bar.columnconfigure(14, weight=1)

		def make_btn(txt, cb, tip=""):
			b = ttk.Button(bar, text=txt, command=cb)
			if tip: self._tooltip(b, tip)
			return b

		self.btn_new     = make_btn("🆕 New",   self._new_project, "Start a new project (.mefproj) — Ctrl+N")
		self.btn_load    = make_btn("📂 Load",  self._open_project_file, "Load project (.mefproj) — Ctrl+L")
		self.btn_save    = make_btn("💾 Save",  self._save_project, "Save project — Ctrl+S")
		self.btn_import  = make_btn("📥 Import", self._open_mod_folder, "Import existing MEF mod folder — Ctrl+I")
		self.btn_overwr  = make_btn("🔧 Overwrite", self._overwrite, "Overwrite XMLs in imported mod — Ctrl+Shift+O")
		self.btn_build   = make_btn("🛠 Build", self._build, "Build a new mod folder — Ctrl+B")
		self.theme_btn   = ttk.Button(bar, text="🌙", width=3, command=self._toggle_theme)
		self._tooltip(self.theme_btn, "Toggle light/dark theme")

		for i, b in enumerate((self.btn_new,self.btn_load,self.btn_save,self.btn_import,self.btn_overwr,self.btn_build)):
			b.grid(row=0, column=i, padx=(0 if i==0 else 6, 6), ipady=2)
		ttk.Label(bar, text="").grid(row=0, column=14, sticky="ew")  # spacer
		self.theme_btn.grid(row=0, column=15, sticky="e")            # pinned far right

		# Keyboard shortcuts
		self.bind_all("<Control-n>", lambda e: self._new_project())
		self.bind_all("<Control-l>", lambda e: self._open_project_file())
		self.bind_all("<Control-s>", lambda e: self._save_project())
		self.bind_all("<Control-i>", lambda e: self._open_mod_folder())
		self.bind_all("<Control-b>", lambda e: self._build())
		self.bind_all("<Control-O>", lambda e: self._overwrite())   # Shift+O

		# Notebook
		self.nb = ttk.Notebook(self); self.nb.pack(fill="both", expand=True, padx=10, pady=(6,8))
		self.tab_about = ttk.Frame(self.nb, padding=10)
		self.tab_theme = ttk.Frame(self.nb, padding=10)
		self.tab_tracks= ttk.Frame(self.nb, padding=10)
		self.tab_build = ttk.Frame(self.nb, padding=10)
		self.nb.add(self.tab_about, text="About")
		self.nb.add(self.tab_theme, text="Theme")
		self.nb.add(self.tab_tracks, text="Track.xml")
		self.nb.add(self.tab_build, text="Build")

		self._build_about_tab(self.tab_about)
		self._build_theme_tab(self.tab_theme)
		self._build_tracks_tab(self.tab_tracks)
		self._build_build_tab(self.tab_build)

		# Bottom nav (Prev/Next)
		nav = ttk.Frame(self, padding=(10,0,10,8)); nav.pack(fill="x")
		nav.columnconfigure(0, weight=1)
		self.prev_btn = ttk.Button(nav, text="◀ Previous", command=self._prev_tab)
		self.next_btn = ttk.Button(nav, text="Next ▶", command=self._next_tab)
		self.prev_btn.pack(side="left")
		self.next_btn.pack(side="right")
		self._update_nav()

	# ---------- About tab
	def _build_about_tab(self, tab):
		tab.columnconfigure(1, weight=1)
		for r in (7,): tab.rowconfigure(r, weight=1)

		r1 = ttk.Frame(tab); r1.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,6))
		ttk.Label(r1, text="Name:").pack(side="left")
		ttk.Entry(r1, textvariable=self.about_name, width=44).pack(side="left", padx=6)
		self.name_hint = ttk.Label(r1, text="← finish after “Music Expanded: ”"); self.name_hint.pack(side="left")

		r2 = ttk.Frame(tab); r2.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0,6))
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

		# Versions (auto-grow)
		ttk.Label(tab, text="Supported Versions (one per line, e.g., 1.6):").grid(row=2, column=0, sticky="w")
		self.vers_txt = tk.Text(tab, height=3)
		self.vers_txt.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2,6))
		self._track_text(self.vers_txt); self.vers_txt.insert("1.0", self.about_versions_text_default)
		self._auto_grow(self.vers_txt, min_rows=3, max_rows=14)

		# Load After (auto-grow)
		ttk.Label(tab, text="Load After (one per line):").grid(row=4, column=0, sticky="w")
		self.load_after_txt = tk.Text(tab, height=3)
		self.load_after_txt.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(2,6))
		self._track_text(self.load_after_txt); self.load_after_txt.insert("1.0", self.about_load_after_default)
		self._auto_grow(self.load_after_txt, min_rows=3, max_rows=12)

		# Description
		ttk.Label(tab, text="Description (CDATA):").grid(row=6, column=0, sticky="w")
		self.desc_txt = tk.Text(tab, height=8, wrap="word")
		self.desc_txt.grid(row=7, column=0, columnspan=2, sticky="nsew", pady=(2,0))
		self._track_text(self.desc_txt)

		# Images
		imgs = ttk.Frame(tab); imgs.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8,0))
		imgs.columnconfigure(1, weight=1)
		ttk.Label(imgs, text="Preview.png:").grid(row=0, column=0, sticky="w")
		ttk.Entry(imgs, textvariable=self.preview_src).grid(row=0, column=1, sticky="ew", padx=6)
		ttk.Button(imgs, text="Choose…", command=self._pick_preview).grid(row=0, column=2)
		ttk.Label(imgs, text="modicon.png:").grid(row=1, column=0, sticky="w", pady=(6,0))
		ttk.Entry(imgs, textvariable=self.modicon_src).grid(row=1, column=1, sticky="ew", padx=6, pady=(6,0))
		ttk.Button(imgs, text="Choose…", command=self._pick_modicon).grid(row=1, column=2, pady=(6,0))

	# ---------- Theme tab (with preview on right)
	def _build_theme_tab(self, tab):
		tab.columnconfigure(0, weight=2)
		tab.columnconfigure(1, weight=3)
		tab.rowconfigure(1, weight=1)

		# Left column: def controls + fields + description
		left = ttk.Frame(tab); left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0,8))
		for c in (1,3,5,7): left.columnconfigure(c, weight=1)
		left.rowconfigure(5, weight=1)

		# Def management
		h = ttk.Frame(left); h.grid(row=0, column=0, columnspan=8, sticky="ew", pady=(0,6))
		ttk.Label(h, text="Def:").pack(side="left")
		self.def_combo = ttk.Combobox(h, state="readonly", width=32, values=[])
		self.def_combo.bind("<<ComboboxSelected>>", self._on_def_combo_select)
		self.def_combo.pack(side="left", padx=6)
		ttk.Button(h, text="Add…", command=self._add_def).pack(side="left", padx=(6,2))
		ttk.Button(h, text="Duplicate", command=self._dup_def).pack(side="left", padx=2)
		ttk.Button(h, text="Rename…", command=self._rename_def).pack(side="left", padx=2)
		ttk.Button(h, text="Delete", command=self._delete_def).pack(side="left", padx=2)
		self.def_folder_lbl = ttk.Label(left, text="Def folder: (none)")
		self.def_folder_lbl.grid(row=1, column=0, columnspan=8, sticky="w")

		# Core fields
		self.game_label = tk.StringVar(value="")
		self.game_code  = tk.StringVar(value="")
		self.content_folder = tk.StringVar(value="")
		self.label_prefix = tk.StringVar(value="")
		ttk.Label(left, text="Game Name:").grid(row=2, column=0, sticky="w")
		ttk.Entry(left, textvariable=self.game_label).grid(row=2, column=1, sticky="ew", padx=6)
		ttk.Label(left, text="Game Code:").grid(row=2, column=2, sticky="w")
		ttk.Entry(left, textvariable=self.game_code, width=10).grid(row=2, column=3, sticky="w", padx=6)
		ttk.Label(left, text="Content folder:").grid(row=2, column=4, sticky="w")
		ttk.Entry(left, textvariable=self.content_folder).grid(row=2, column=5, sticky="ew", padx=6)
		ttk.Label(left, text="Label Prefix (optional):").grid(row=2, column=6, sticky="w")
		ttk.Entry(left, textvariable=self.label_prefix).grid(row=2, column=7, sticky="ew", padx=6)
		for var in (self.game_label, self.game_code, self.content_folder, self.label_prefix):
			var.trace_add("write", self._on_core_changed)

		# Theme description
		ttk.Label(left, text="Theme description:").grid(row=3, column=0, columnspan=8, sticky="w", pady=(6,2))
		self.theme_desc_txt = tk.Text(left, height=10, wrap="word")
		self.theme_desc_txt.grid(row=4, column=0, columnspan=8, sticky="nsew")
		self._track_text(self.theme_desc_txt)
		self._auto_grow(self.theme_desc_txt, min_rows=6, max_rows=20)

		# Right column: theme preview + regenerate
		right = ttk.Frame(tab); right.grid(row=0, column=1, rowspan=2, sticky="nsew")
		right.rowconfigure(0, weight=1); right.columnconfigure(0, weight=1)

		self.theme_preview = tk.Text(right, wrap="none")
		self._track_text(self.theme_preview)
		thy = ttk.Scrollbar(right, orient="vertical", command=self.theme_preview.yview)
		thx = ttk.Scrollbar(right, orient="horizontal", command=self.theme_preview.xview)
		self.theme_preview.configure(yscrollcommand=thy.set, xscrollcommand=thx.set, state="disabled")
		self.theme_preview.grid(row=0, column=0, sticky="nsew")
		thy.grid(row=0, column=1, sticky="ns")
		thx.grid(row=1, column=0, sticky="ew")
		ttk.Button(right, text="Regenerate Preview", command=self._refresh_theme_preview).grid(row=2, column=0, pady=(8,0))

	# ---------- Track.xml tab (editor left, preview right)
	def _build_tracks_tab(self, tab):
		tab.columnconfigure(0, weight=2)
		tab.columnconfigure(1, weight=3)
		tab.rowconfigure(0, weight=1)

		# LEFT: table + scrollable editor (vertical split)
		left = ttk.Panedwindow(tab, orient="vertical"); left.grid(row=0, column=0, sticky="nsew", padx=(0,8))
		# a) track table
		table_frame = ttk.Frame(left)
		table_frame.rowconfigure(0, weight=1); table_frame.columnconfigure(0, weight=1)
		self.tracks_tree = ttk.Treeview(table_frame, columns=("idx","file","label","uses"), show="headings", selectmode="extended")
		for c,w in (("idx",70),("file",340),("label",340),("uses",320)):
			self.tracks_tree.heading(c, text=c.upper()); self.tracks_tree.column(c, width=w, anchor="w", stretch=True)
		ys = ttk.Scrollbar(table_frame, orient="vertical", command=self.tracks_tree.yview)
		xs = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tracks_tree.xview)
		self.tracks_tree.configure(yscroll=ys.set, xscroll=xs.set)
		self.tracks_tree.grid(row=0, column=0, sticky="nsew")
		ys.grid(row=0, column=1, sticky="ns")
		xs.grid(row=1, column=0, sticky="ew")
		self.tracks_tree.bind("<<TreeviewSelect>>", lambda e: self._on_track_select())
		left.add(table_frame, weight=3)

		# b) scrollable editor
		editor_holder = ttk.Frame(left)
		editor_holder.rowconfigure(0, weight=1); editor_holder.columnconfigure(0, weight=1)
		canvas = tk.Canvas(editor_holder, highlightthickness=0, bd=0, relief="flat", bg=self._palette_color("alt"))
		vs = ttk.Scrollbar(editor_holder, orient="vertical", command=canvas.yview)
		canvas.configure(yscrollcommand=vs.set)
		canvas.grid(row=0, column=0, sticky="nsew")
		vs.grid(row=0, column=1, sticky="ns")
		editor = ttk.Frame(canvas)
		canvas_id = canvas.create_window((0,0), window=editor, anchor="nw")

		def _sync_scroll(_evt=None):
			canvas.configure(scrollregion=canvas.bbox("all"))
			canvas.itemconfigure(canvas_id, width=canvas.winfo_width())
		editor.bind("<Configure>", _sync_scroll)
		canvas.bind("<Configure>", _sync_scroll)

		# Adders
		srcrow = ttk.Frame(editor); srcrow.grid(row=0, column=0, columnspan=6, sticky="w", pady=(8,8))
		ttk.Button(srcrow, text="Add files…", command=self._add_track_files).pack(side="left")
		ttk.Button(srcrow, text="Add folder…", command=self._add_tracks_from_folder).pack(side="left", padx=6)

		# Compact two columns + tall, single-column biomes
		for c in (0,1,2): editor.columnconfigure(c, weight=1)

		# Left column: cue + cueData + replace
		colL = ttk.Frame(editor); colL.grid(row=1, column=0, sticky="nsew", padx=(0,12))
		colL.columnconfigure(1, weight=1)
		ttk.Label(colL, text="Cue:").grid(row=0, column=0, sticky="w", padx=6, pady=(0,2))
		self.cue_choice = ttk.Combobox(colL, state="readonly", width=22,
			values=["Ambient","MainMenu","Credits","BattleSmall","BattleMedium","BattleLarge","BattleLegendary","Custom"])
		self.cue_choice.current(0); self.cue_choice.grid(row=0, column=1, sticky="ew", padx=6, pady=(0,2))
		ttk.Label(colL, text="cueData (Custom):").grid(row=1, column=0, sticky="w", padx=6)
		self.cue_data = tk.StringVar(value="")
		ttk.Entry(colL, textvariable=self.cue_data).grid(row=1, column=1, sticky="ew", padx=6)
		self.replace_ambient = tk.BooleanVar(value=True)
		ttk.Checkbutton(colL, text="Replace default Ambient if first non-ambient is added",
		                variable=self.replace_ambient).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(6,0))

		# Middle column: labels
		colM = ttk.Frame(editor); colM.grid(row=1, column=1, sticky="nsew", padx=(0,12))
		colM.columnconfigure(1, weight=1)
		ttk.Label(colM, text="Label Prefix (optional, global):").grid(row=0, column=0, sticky="w", padx=6, pady=(0,2))
		self.label_prefix_entry = ttk.Entry(colM, textvariable=self.label_prefix)
		self.label_prefix_entry.grid(row=0, column=1, sticky="ew", padx=6)
		ttk.Label(colM, text="Label (right part):").grid(row=1, column=0, sticky="w", padx=6, pady=(6,2))
		self.track_label = tk.StringVar(value="")
		ttk.Entry(colM, textvariable=self.track_label).grid(row=1, column=1, sticky="ew", padx=6)
		self.track_label.trace_add("write", self._on_track_label_changed)

		# Right column: tall, vertical Allowed Biomes (single column)
		colR = ttk.Frame(editor); colR.grid(row=1, column=2, sticky="nsew")
		colR.columnconfigure(0, weight=1)
		ttk.Label(colR, text="Allowed Biomes:").grid(row=0, column=0, sticky="w", padx=6, pady=(0,2))
		ab_box = ttk.Frame(colR); ab_box.grid(row=1, column=0, sticky="nsew")
		ab_box.columnconfigure(0, weight=1)
		self.biome_vars = {}
		for i, b in enumerate(DEFAULT_BIOMES):
			var = tk.BooleanVar(value=False); self.biome_vars[b] = var
			ttk.Checkbutton(ab_box, text=b, variable=var).grid(row=i, column=0, sticky="w", padx=6, pady=2)

		# Buttons
		bbar = ttk.Frame(editor); bbar.grid(row=2, column=0, columnspan=3, sticky="e", padx=6, pady=(10,8))
		ttk.Button(bbar, text="Apply Cue",  command=self._apply_queue).pack(side="left")
		ttk.Button(bbar, text="Remove Cue", command=self._remove_queue).pack(side="left", padx=8)

		left.add(editor_holder, weight=2)

		# RIGHT: track preview + regenerate
		right = ttk.Frame(tab); right.grid(row=0, column=1, sticky="nsew")
		right.rowconfigure(0, weight=1); right.columnconfigure(0, weight=1)
		self.tracks_preview = tk.Text(right, wrap="none")
		self._track_text(self.tracks_preview)
		tpy = ttk.Scrollbar(right, orient="vertical", command=self.tracks_preview.yview)
		tpx = ttk.Scrollbar(right, orient="horizontal", command=self.tracks_preview.xview)
		self.tracks_preview.configure(yscrollcommand=tpy.set, xscrollcommand=tpx.set, state="disabled")
		self.tracks_preview.grid(row=0, column=0, sticky="nsew")
		tpy.grid(row=0, column=1, sticky="ns")
		tpx.grid(row=1, column=0, sticky="ew")
		ttk.Button(right, text="Regenerate Preview", command=self._refresh_tracks_preview).grid(row=2, column=0, pady=(8,0))

	# ---------- Build tab
	def _build_build_tab(self, tab):
		tab.columnconfigure(0, weight=1); tab.rowconfigure(1, weight=1)
		ttk.Label(tab, text="Preflight / Steam Workshop Rules (read before uploading)").grid(row=0, column=0, sticky="w")
		self.build_info = tk.Text(tab, wrap="word")
		self._track_text(self.build_info)
		self.build_info.grid(row=1, column=0, sticky="nsew", pady=(6,0))
		self._update_build_panel()
		row = ttk.Frame(tab); row.grid(row=2, column=0, sticky="e", pady=(8,0))
		ttk.Button(row, text="🔧 Overwrite (if imported)", command=self._overwrite).pack(side="left", padx=(0,8))
		ttk.Button(row, text="🛠 Build", command=self._build).pack(side="left")

	# ---------- Utilities (palette/tooltip/auto-grow/nav)
	def _palette_color(self, key): return getattr(self, "_palette", PAL_D).get(key, "#222")
	def _track_text(self, w: tk.Text):
		self._tk_texts.append(w)
		p = getattr(self, "_palette", PAL_D)
		try: w.configure(bg=p["alt"], fg=p["fg"], insertbackground=p["fg"])
		except: pass
	def _repaint_texts(self):
		p = getattr(self, "_palette", PAL_D)
		for w in self._tk_texts:
			try: w.configure(bg=p["alt"], fg=p["fg"], insertbackground=p["fg"])
			except: pass
	def _tooltip(self, widget, text: str):
		tip = tk.Toplevel(widget); tip.withdraw(); tip.overrideredirect(True)
		lbl = tk.Label(tip, text=text, background="#111", foreground="#eee", bd=1, relief="solid", padx=6, pady=3)
		lbl.pack()
		def enter(_):
			tip.deiconify()
			x = widget.winfo_rootx() + widget.winfo_width()//2
			y = widget.winfo_rooty() + widget.winfo_height() + 8
			tip.geometry(f"+{x}+{y}")
		def leave(_): tip.withdraw()
		widget.bind("<Enter>", enter); widget.bind("<Leave>", leave)

	def _auto_grow(self, txt: tk.Text, min_rows=3, max_rows=12):
		self._auto_grow_map[txt] = (min_rows, max_rows)
		def _fit(_evt=None):
			lines = int(float(txt.index("end-1c").split(".")[0]))
			txt.configure(height=max(min_rows, min(max_rows, lines)))
		txt.bind("<KeyRelease>", _fit)
		txt.bind("<<Paste>>", _fit)
		self.after(50, _fit)

	def _toggle_theme(self):
		self._dark = not self._dark
		self.theme_btn.configure(text="🌙" if self._dark else "☀")  # moon = dark, sun = light
		apply_palette(self, self._dark)
		self._repaint_texts()
		self._refresh_previews()

	def _prev_tab(self):
		i = self.nb.index(self.nb.select())
		if i > 0: self.nb.select(i-1)
		self._update_nav()
	def _next_tab(self):
		i = self.nb.index(self.nb.select())
		if i < self.nb.index("end")-1: self.nb.select(i+1)
		self._update_nav()
	def _update_nav(self):
		i = self.nb.index(self.nb.select())
		self.prev_btn.configure(state=("disabled" if i == 0 else "normal"))
		self.next_btn.configure(state=("disabled" if i >= self.nb.index("end")-1 else "normal"))

	# ---------- About helpers
	def _get_versions_lines(self):
		return self.vers_txt.get("1.0","end").splitlines()
	def _get_load_after_lines(self):
		return self.load_after_txt.get("1.0","end").splitlines()

	# ---------- Def controls (in Theme tab)
	def _refresh_all_def_controls(self):
		names = [d.label_game for d in self.defs]
		self.def_combo.configure(values=names)
		if 0 <= self.cur_def_idx.get() < len(names):
			self.def_combo.current(self.cur_def_idx.get())
		elif names:
			self.cur_def_idx.set(0); self.def_combo.current(0)
		else:
			self.def_combo.set("")

		d = self._curdef()
		if d:
			self.game_label.set(d.label_game)
			self.game_code.set(d.game_code)
			self.content_folder.set(d.content_folder)
			self.label_prefix.set(d.label_prefix)
			self.theme_desc_txt.delete("1.0","end"); self.theme_desc_txt.insert("1.0", d.theme_description)
			self.def_folder_lbl.configure(text=f"Def folder: {d._src_def_dir}" if d._src_def_dir else "Def folder: (new/not from disk)")
		else:
			self.game_label.set(""); self.game_code.set(""); self.content_folder.set(""); self.label_prefix.set("")
			self.theme_desc_txt.delete("1.0","end"); self.def_folder_lbl.configure(text="Def folder: (none)")

		self._refresh_tracks_table(); self._refresh_previews()
		self._update_toolbar_states()

	def _on_def_combo_select(self, _evt=None):
		val = self.def_combo.get()
		for i, d in enumerate(self.defs):
			if d.label_game == val:
				self.cur_def_idx.set(i)
				self._refresh_all_def_controls()
				return

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
		self._refresh_all_def_controls()

	def _dup_def(self):
		d = self._curdef()
		if not d: return
		import copy
		new = copy.deepcopy(d)
		new.label_game = d.label_game + " (Copy)"
		self.defs.append(new)
		self.cur_def_idx.set(len(self.defs)-1)
		self._refresh_all_def_controls()

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
		self._refresh_all_def_controls()

	def _delete_def(self):
		if not self.defs: return
		idx = self.cur_def_idx.get()
		name = self.defs[idx].label_game
		if not messagebox.askyesno(APP_TITLE, f"Delete Def “{name}”?"): return
		self.defs.pop(idx)
		self.cur_def_idx.set(max(0, idx-1) if self.defs else -1)
		self._refresh_all_def_controls()

	def _on_core_changed(self, *_):
		d = self._curdef()
		if not d: return
		d.label_game = self.game_label.get().strip() or d.label_game
		d.game_code = self.game_code.get().strip() or d.game_code
		d.content_folder = self.content_folder.get().strip() or d.content_folder
		d.label_prefix = self.label_prefix.get()
		d.theme_description = self.theme_desc_txt.get("1.0","end").strip() or d.theme_description
		self._refresh_previews()

	# ---------- Tracks
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
		self._refresh_tracks_table(); self._refresh_previews()

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
		self._refresh_tracks_table(); self._refresh_previews()

	def _refresh_tracks_table(self):
		if not hasattr(self, "tracks_tree"): return
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
		d = self._curdef(); sel = self.tracks_tree.selection() if hasattr(self, "tracks_tree") else []
		if not d or not sel: return None
		idx = int(self.tracks_tree.item(sel[0], "values")[0])
		for t in d.tracks:
			if t.idx == idx: return t
		return None

	def _selected_tracks(self):
		d = self._curdef()
		if not d or not hasattr(self, "tracks_tree"): return []
		sels = self.tracks_tree.selection()
		if not sels:
			t = self._current_track()
			return [t] if t else []
		idxs = {int(self.tracks_tree.item(i, "values")[0]) for i in sels}
		return [t for t in d.tracks if t.idx in idxs]

	def _collect_biomes_from_ui(self):
		return [b for b,v in self.biome_vars.items() if v.get()]

	def _on_track_label_changed(self, *_):
		txt = self.track_label.get().strip()
		if not txt: return
		for t in self._selected_tracks():
			t.display_title = txt
		self._refresh_tracks_table(); self._refresh_previews()

	def _apply_queue(self):
		targets = self._selected_tracks()
		if not targets:
			messagebox.showinfo(APP_TITLE, "Select one or more tracks."); return
		cue_disp = self.cue_choice.get()
		if cue_disp == "Ambient":
			new_use_proto = TrackUse(None, "", self._collect_biomes_from_ui())
		elif cue_disp == "Custom":
			cd = self.cue_data.get().strip()
			if not cd:
				messagebox.showerror(APP_TITLE, "cueData required for Custom."); return
			new_use_proto = TrackUse("Custom", cd, self._collect_biomes_from_ui())
		else:
			new_use_proto = TrackUse(cue_disp, "", self._collect_biomes_from_ui())

		new_right_label = self.track_label.get().strip()

		for t in targets:
			new_use = TrackUse(new_use_proto.cue_type, new_use_proto.cue_data, list(new_use_proto.allowed_biomes))
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
			if new_right_label:
				t.display_title = new_right_label

		self._refresh_tracks_table(); self._refresh_previews()

	def _remove_queue(self):
		targets = self._selected_tracks()
		if not targets:
			messagebox.showinfo(APP_TITLE, "Select one or more tracks."); return
		cue_disp = self.cue_choice.get(); cd = self.cue_data.get().strip()
		for t in targets:
			def idx_for():
				if cue_disp == "Ambient":
					for i,u in enumerate(t.uses):
						if u.cue_type is None: return i
				elif cue_disp == "Custom":
					for i,u in enumerate(t.uses):
						if u.cue_type=="Custom" and u.cue_data==cd: return i
				else:
					for i,u in enumerate(t.uses):
						if u.cue_type == cue_disp: return i
				return -1
			i = idx_for()
			if i >= 0:
				t.uses.pop(i)
				if not t.uses:
					t.uses = [TrackUse()]
		self._refresh_tracks_table(); self._refresh_previews()

	# ---------- Previews
	def _refresh_tracks_preview(self):
		d = self._curdef()
		xml = build_tracks_xml(d) if d else "<!-- No Def selected -->\n"
		self.tracks_preview.configure(state="normal"); self.tracks_preview.delete("1.0","end"); self.tracks_preview.insert("1.0", xml); self.tracks_preview.configure(state="disabled")
	def _refresh_theme_preview(self):
		d = self._curdef()
		xml = build_theme_xml(d) if d else "<!-- No Def selected -->\n"
		self.theme_preview.configure(state="normal"); self.theme_preview.delete("1.0","end"); self.theme_preview.insert("1.0", xml); self.theme_preview.configure(state="disabled")
	def _refresh_previews(self):
		if hasattr(self, "tracks_preview"): self._refresh_tracks_preview()
		if hasattr(self, "theme_preview"):  self._refresh_theme_preview()
		self._update_build_panel()

	# ---------- Build panel
	def _update_build_panel(self):
		lines = []
		lines.append("BUILD PREFLIGHT SUMMARY\n")
		if not self.defs:
			lines.append("- No Defs created.\n")
		else:
			for d in self.defs:
				a=m=b=cu=0
				for t in d.tracks:
					for u in t.uses:
						if u.cue_type is None: a+=1
						elif u.cue_type in ("MainMenu","Credits"): m+=1
						elif u.cue_type in BATTLE_CUES: b+=1
						elif u.cue_type=="Custom": cu+=1
				lines.append(f"- {d.label_game}: ambient {a}, main/credits {m}, battle {b}, custom {cu}\n")
		lines.append("\nSTEAM WORKSHOP CONTENT & COMMUNITY RULES (brief)\n")
		lines.append("• Only upload content you own or have permission to use.\n")
		lines.append("• No malware, scams, or illegal content; respect local laws.\n")
		lines.append("• No harassment/hate speech; follow DMCA takedowns.\n")
		lines.append("• Provide accurate descriptions/tags; avoid spam.\n")
		self.build_info.configure(state="normal"); self.build_info.delete("1.0","end"); self.build_info.insert("1.0","".join(lines)); self.build_info.configure(state="disabled")

	# ---------- Project save/open
	def _serialize(self):
		return {
			"about": {
				"name": self.about_name.get(),
				"author": self.about_author.get(),
				"package": self.about_package.get(),
				"versions_text": self.vers_txt.get("1.0","end"),
				"load_after_text": self.load_after_txt.get("1.0","end"),
				"description": self.desc_txt.get("1.0","end"),
				"preview": self.preview_src.get(),
				"modicon": self.modicon_src.get(),
			},
			"defs": [{
				"label_game": d.label_game,
				"game_code": d.game_code,
				"content_folder": d.content_folder,
				"label_prefix": d.label_prefix,
				"theme_description": d.theme_description,
				"tracks": [{
					"idx": t.idx,
					"path": str(t.path),
					"display_title": t.display_title,
					"file_title": t.file_title,
					"uses": [{
						"cue_type": u.cue_type,
						"cue_data": u.cue_data,
						"allowed_biomes": u.allowed_biomes
					} for u in t.uses]
				} for t in d.tracks]
			} for d in self.defs]
		}

	def _load_from_dict(self, data: dict):
		a = data.get("about", {})
		self.about_name.set(a.get("name","Music Expanded: "))
		self.about_author.set(a.get("author",""))
		self.about_package.set(a.get("package","musicexpanded."))
		self.vers_txt.delete("1.0","end"); self.vers_txt.insert("1.0", a.get("versions_text", self.about_versions_text_default))
		self.load_after_txt.delete("1.0","end"); self.load_after_txt.insert("1.0", a.get("load_after_text", self.about_load_after_default))
		self.desc_txt.delete("1.0","end"); self.desc_txt.insert("1.0", a.get("description",""))
		self.preview_src.set(a.get("preview","")); self.modicon_src.set(a.get("modicon",""))

		self.defs.clear()
		for d in data.get("defs", []):
			pd = ProjectDef(d.get("label_game",""))
			pd.game_code = d.get("game_code", pd.game_code)
			pd.content_folder = d.get("content_folder", pd.content_folder)
			pd.label_prefix = d.get("label_prefix","")
			pd.theme_description = d.get("theme_description", pd.theme_description)
			for t in d.get("tracks", []):
				tr = Track(t["idx"], Path(t["path"]), t["display_title"], t["file_title"])
				tr.uses = [TrackUse(u.get("cue_type"), u.get("cue_data",""), u.get("allowed_biomes",[])) for u in t.get("uses",[])]
				if not tr.uses: tr.uses=[TrackUse()]
				pd.tracks.append(tr)
			self.defs.append(pd)
		self.cur_def_idx.set(0 if self.defs else -1)
		self._refresh_all_def_controls()

	def _save_project(self):
		p = filedialog.asksaveasfilename(defaultextension=".mefproj", filetypes=[("MEF Project",".mefproj")])
		if not p: return
		Path(p).write_text(json.dumps(self._serialize(), indent=2), encoding="utf-8")
		messagebox.showinfo(APP_TITLE, "Project saved.")

	def _open_project_file(self):
		p = filedialog.askopenfilename(filetypes=[("MEF Project",".mefproj"), ("JSON",".json"), ("All","*.*")])
		if not p: return
		try:
			data = json.loads(Path(p).read_text(encoding="utf-8"))
			self._load_from_dict(data)
			messagebox.showinfo(APP_TITLE, "Project loaded.")
		except Exception as e:
			messagebox.showerror(APP_TITLE, f"Failed to load project:\n{e}")

	# ---------- New/Open Mod
	def _new_project(self):
		if not messagebox.askyesno(APP_TITLE, "Clear current project?"): return
		self.defs.clear(); self.cur_def_idx.set(-1); self.loaded_mod_dir = None
		self.about_name.set("Music Expanded: ")
		self.about_author.set("karbonpanzer")
		self.about_package.set("musicexpanded.")
		self.vers_txt.delete("1.0","end"); self.vers_txt.insert("1.0", self.about_versions_text_default)
		self.load_after_txt.delete("1.0","end"); self.load_after_txt.insert("1.0", self.about_load_after_default)
		self.desc_txt.delete("1.0","end"); self.desc_txt.insert("1.0", "Put your About description here (wrapped in CDATA).")
		self.preview_src.set(""); self.modicon_src.set("")
		self._refresh_all_def_controls()

	def _open_mod_folder(self):
		root = filedialog.askdirectory(title="Import MEF Mod Folder")
		if not root: return
		mod = Path(root)
		about_dir = mod / "About"
		defs_dir = mod / "Defs"
		if not about_dir.exists() or not defs_dir.exists():
			messagebox.showerror(APP_TITLE, "This doesn’t look like a MEF mod (missing About/ or Defs/)."); return

		info = parse_about_xml(about_dir)
		if info:
			self.about_name.set(info["name"] or "Music Expanded: ")
			self.about_author.set(info["author"] or "karbonpanzer")
			self.about_package.set(info["packageId"] or "musicexpanded.")
			self.vers_txt.delete("1.0","end"); self.vers_txt.insert("1.0", "\n".join(info["versions"]) if info["versions"] else self.about_versions_text_default)
			self.load_after_txt.delete("1.0","end"); self.load_after_txt.insert("1.0", "\n".join(info["load_after"]) if info["load_after"] else self.about_load_after_default)
			self.desc_txt.delete("1.0","end"); self.desc_txt.insert("1.0", info["description"] or "")

		new_defs = []
		for child in sorted(defs_dir.iterdir()):
			if not child.is_dir(): continue
			if child.name.lower() == "patches": continue
			pd = parse_def_folder(child)
			if pd: new_defs.append(pd)

		if not new_defs:
			messagebox.showerror(APP_TITLE, "No valid Defs found (need Defs/<Something>/tracks.xml + theme.xml)."); return

		self.defs = new_defs; self.cur_def_idx.set(0); self.loaded_mod_dir = mod
		self._refresh_all_def_controls()
		self._update_toolbar_states()
		messagebox.showinfo(APP_TITLE, f"Loaded {len(self.defs)} def(s) from:\n{mod}")

	# ---------- Build & Overwrite
	def _preflight_ok(self, overwrite=False):
		issues = []
		if self.about_name.get().strip() in ("","Music Expanded:"):
			issues.append("About: Name incomplete.")
		pkg = self.about_package.get().strip()
		if not pkg.startswith("musicexpanded.") or pkg == "musicexpanded.":
			issues.append("About: Package ID invalid (must start with musicexpanded.).")
		vers = [v.strip() for v in self._get_versions_lines() if v.strip()]
		if not vers: issues.append("About: No supported versions entered.")
		if not self.defs: issues.append("No Defs created.")
		for d in self.defs:
			if not d.tracks: issues.append(f"Def '{d.label_game}': no tracks.")
		if issues:
			return messagebox.askyesno(APP_TITLE, "Issues:\n- " + "\n- ".join(issues) + "\n\nProceed anyway?")
		return True

	def _build(self):
		if not self._preflight_ok(False): return
		outroot = Path(self.out_root.get().strip()); outroot.mkdir(parents=True, exist_ok=True)
		mod_name = simpledialog.askstring(APP_TITLE, "Name the output mod folder")
		if not mod_name: return
		mod_dir = outroot / sanitize_component(mod_name)
		if mod_dir.exists():
			if not messagebox.askyesno(APP_TITLE, f"Folder exists:\n{mod_dir}\n\nOverwrite?"): return
			shutil.rmtree(mod_dir)
		mod_dir.mkdir(parents=True, exist_ok=True)

		# About
		about_dir = mod_dir / "About"; about_dir.mkdir(parents=True, exist_ok=True)
		desc = self.desc_txt.get("1.0","end").strip()
		vers_lines = self._get_versions_lines()
		la_lines = self._get_load_after_lines()
		about_xml = build_about_xml(self.about_name.get().strip(), desc, self.about_author.get().strip(),
			self.about_package.get().strip(), vers_lines, la_lines)
		(about_dir / "About.xml").write_text(about_xml, encoding="utf-8", newline="\n")
		if self.preview_src.get().strip(): shutil.copy2(self.preview_src.get().strip(), about_dir / "Preview.png")
		if self.modicon_src.get().strip(): shutil.copy2(self.modicon_src.get().strip(), about_dir / "modicon.png")

		# Folders
		defs_root = mod_dir / "Defs"; defs_root.mkdir(parents=True, exist_ok=True)
		sounds_root = mod_dir / "Sounds" / "MusicExpanded"; sounds_root.mkdir(parents=True, exist_ok=True)

		dest_folders = set()
		for d in self.defs:
			dfolder_name = sanitize_simple(d.label_game) or d.content_folder or "Game"
			if dfolder_name in dest_folders:
				messagebox.showerror(APP_TITLE, f"Duplicate Def folder would be created: {dfolder_name}\nRename one of your Defs."); return
			dest_folders.add(dfolder_name)

			dfolder = defs_root / dfolder_name
			dfolder.mkdir(parents=True, exist_ok=True)
			(dfolder / "tracks.xml").write_text(build_tracks_xml(d), encoding="utf-8", newline="\n")
			(dfolder / "theme.xml").write_text(build_theme_xml(d), encoding="utf-8", newline="\n")

			dest_folder = sounds_root / d.content_folder
			dest_folder.mkdir(parents=True, exist_ok=True)
			for t in d.tracks:
				target_name = f"{t.idx:03d}. {t.file_title}.ogg"
				try: shutil.copy2(t.path, dest_folder / target_name)
				except Exception as e: messagebox.showwarning(APP_TITLE, f"Failed to copy {t.path.name}: {e}")

		messagebox.showinfo(APP_TITLE, f"Build complete.\n\n{mod_dir}")
		self._open_folder(mod_dir)

	def _overwrite(self):
		if not self.loaded_mod_dir:
			messagebox.showerror(APP_TITLE, "Import a MEF mod first (📥 Import)."); return
		if not self._preflight_ok(True): return
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
			(target / "theme.xml").write_text(build_theme_xml(d), encoding="utf-8", newline="\n")

		messagebox.showinfo(APP_TITLE, f"Overwrite complete.\n\n{self.loaded_mod_dir}")
		self._open_folder(self.loaded_mod_dir)

	def _update_toolbar_states(self):
		state = ("normal" if self.loaded_mod_dir else "disabled")
		try:
			self.btn_overwr.configure(state=state)
		except Exception:
			pass

	# ---------- Misc helpers
	def _pick_out_root(self):
		p = filedialog.askdirectory(title="Pick output folder")
		if p: self.out_root.set(p)
	def _pick_preview(self):
		p = filedialog.askopenfilename(title="Pick Preview.png", filetypes=[("PNG","*.png")])
		if p: self.preview_src.set(p)
	def _pick_modicon(self):
		p = filedialog.askopenfilename(title="Pick modicon.png", filetypes=[("PNG","*.png")])
		if p: self.modicon_src.set(p)
	def _curdef(self) -> ProjectDef|None:
		idx = self.cur_def_idx.get()
		return self.defs[idx] if 0 <= idx < len(self.defs) else None
	def _open_folder(self, path: Path|None):
		if not path: return
		try:
			if sys.platform.startswith("win"): os.startfile(path)        # type: ignore
			elif sys.platform == "darwin": subprocess.run(["open", str(path)], check=False)
			else: subprocess.run(["xdg-open", str(path)], check=False)
		except Exception:
			pass

# ---------------- Run ----------------
if __name__ == "__main__":
	app = App()
	app.mainloop()
