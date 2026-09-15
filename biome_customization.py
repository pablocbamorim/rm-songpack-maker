from __future__ import annotations
import colorsys, json, os, tempfile, tkinter as tk
from tkinter import colorchooser, messagebox, ttk
CONFIG_FILENAME = "biome_customization.json"
def _color(name, tag=False):
    h=(sum((i+1)*ord(c) for i,c in enumerate(name))%360)/360
    r,g,b=colorsys.hsv_to_rgb(h,0.62 if tag else 0.58,0.92)
    return "#%02x%02x%02x"%(round(r*255),round(g*255),round(b*255))
def _valid(v):
    if not isinstance(v,str) or len(v)!=7 or v[0]!="#": return False
    try: int(v[1:],16); return True
    except ValueError: return False
def _load(folder):
    try:
        with open(os.path.join(folder,CONFIG_FILENAME),encoding="utf-8") as f: d=json.load(f)
        b=d.get("biomes",{}) if isinstance(d,dict) else {}; t=d.get("biome_tags",{}) if isinstance(d,dict) else {}
        return ({str(k):str(v) for k,v in b.items() if _valid(v)}, {str(k):str(v) for k,v in t.items() if _valid(v)})
    except (OSError,ValueError,TypeError): return {},{}
def _save(folder,b,t):
    target=os.path.join(folder,CONFIG_FILENAME); fd,tmp=tempfile.mkstemp(prefix=".biome_",suffix=".tmp",dir=folder)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump({"version":1,"biomes":dict(sorted(b.items(),key=lambda x:x[0].lower())),"biome_tags":dict(sorted(t.items(),key=lambda x:x[0].lower()))},f,indent=2,ensure_ascii=False); f.write("\n")
        os.replace(tmp,target)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
def install(app):
    import constants as C
    bcolors={n:_color(n) for n in C.COMMON_BIOMES}; tcolors={n:_color(n,True) for n in C.COMMON_BIOME_TAGS}; custom_b={}; custom_t={}
    def catalog(tag):
        base=C.COMMON_BIOME_TAGS if tag else C.COMMON_BIOMES; custom=custom_t if tag else custom_b; colors=tcolors if tag else bcolors
        names=list(dict.fromkeys(list(base)+list(custom))); return names,{n:custom.get(n,colors.get(n,_color(n,tag))) for n in names}
    def load(folder):
        nonlocal custom_b,custom_t; custom_b,custom_t=_load(folder)
    def recolor(lib):
        lb=getattr(lib,"biome_listbox",None)
        if lb is None or not lib.selected_entry_id:return
        for i,c in enumerate(app.pack.find(lib.selected_entry_id).biomes): lb.itemconfig(i,foreground=catalog(c.is_tag)[1].get(c.value,_color(c.value,c.is_tag)))
    original_build=app.library_tab._build_editor_for
    def build(entry):
        def available(e,tag):
            names,_=catalog(tag); used={b.value for b in e.biomes if b.is_tag==tag}; return [x for x in names if x not in used]
        app.library_tab._available_biome_values=available; original_build(entry); recolor(app.library_tab)
        try:
            frame=next(w for w in app.library_tab.editor_frame.winfo_children() if isinstance(w,ttk.LabelFrame) and w.cget("text")=="Biome")
            ttk.Button(frame.winfo_children()[0],text="Add custom…",command=add_dialog).pack(side="left",padx=4)
        except Exception: pass
    def add_dialog():
        win=tk.Toplevel(app); win.title("Add Custom Biome"); win.resizable(False,False); win.transient(app); win.grab_set()
        n=tk.StringVar(); typ=tk.StringVar(value="Biome"); col=tk.StringVar(value="#66ccff")
        body=ttk.Frame(win); body.pack(padx=14,pady=14)
        ttk.Label(body,text="Name / identifier:").grid(row=0,column=0,padx=6,pady=5); ttk.Entry(body,textvariable=n,width=34).grid(row=0,column=1,columnspan=2)
        ttk.Label(body,text="Type:").grid(row=1,column=0,padx=6,pady=5); ttk.Combobox(body,textvariable=typ,values=("Biome","Biome Tag"),state="readonly",width=14).grid(row=1,column=1,sticky="w")
        ttk.Label(body,text="Text color:").grid(row=2,column=0,padx=6,pady=5); sw=tk.Label(body,text="      ",bg=col.get(),relief="sunken"); sw.grid(row=2,column=1,sticky="w")
        def choose():
            x=colorchooser.askcolor(color=col.get(),parent=win,title="Biome text color")
            if x[1]: col.set(x[1]); sw.configure(bg=x[1])
        ttk.Button(body,text="Choose…",command=choose).grid(row=2,column=2)
        def add():
            name=n.get().strip(); color=col.get().lower(); tag=typ.get()=="Biome Tag"
            if not name or not _valid(color): messagebox.showwarning("Custom biome","Enter a name and choose a valid color.",parent=win); return
            (custom_t if tag else custom_b)[name]=color; win.destroy()
            if app.library_tab.selected_entry_id:
                app.library_tab._build_editor_for(app.pack.find(app.library_tab.selected_entry_id)); app.library_tab.biome_search_var.set(name)
        ttk.Button(body,text="Cancel",command=win.destroy).grid(row=3,column=1); ttk.Button(body,text="Add",command=add).grid(row=3,column=2)
    app.library_tab._build_editor_for=build
    old_load=app.action_load_config; old_save=app.action_save_config; old_new=app.action_new_songpack
    def load_config():
        old_load(); folder=getattr(app,"current_save_folder",None)
        if folder:
            load(folder)
            if app.library_tab.selected_entry_id: app.library_tab._build_editor_for(app.pack.find(app.library_tab.selected_entry_id))
    def save_config():
        old_save(); folder=getattr(app,"current_save_folder",None)
        if folder:
            try: _save(folder,custom_b,custom_t)
            except OSError as e: messagebox.showerror("Biome customization",f"Could not save biome customization:\n{e}")
    def new():
        nonlocal custom_b,custom_t; old_new(); custom_b={}; custom_t={}
    app.action_load_config=load_config; app.action_save_config=save_config; app.action_new_songpack=new
    if getattr(app,"current_save_folder",None): load(app.current_save_folder)
