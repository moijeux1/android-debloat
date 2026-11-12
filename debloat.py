#!/usr/bin/env python3
"""Android Debloat : retire (pour l'utilisateur 0) ou restaure des applications Android via adb.

Sans root. Réversible : `pm uninstall --user 0` masque l'application, `install-existing` la restaure.
Sans argument : interface graphique. Voir `debloat.py --help` pour le mode ligne de commande.
"""
import argparse
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys

if getattr(sys, "frozen", False):
    APP_DIR = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(sys.executable).parent))
    EXE_DIR = pathlib.Path(sys.executable).parent
else:
    APP_DIR = EXE_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = pathlib.Path.home() / ".android-debloat"  # journaux des suppressions

# Paquets qu'on refuse de retirer : y toucher peut casser les appels, l'écran ou le démarrage.
# Règle de prudence : tout ce qui commence par com.android. (AOSP) et les services Google de base
# sont protégés, quelle que soit la marque. Les paquets vitaux du téléphone sont ajoutés
# dynamiquement (voir dynamic_protected).
PROTECTED_EXACT = {"android", "com.google.android.gms", "com.google.android.gsf",
                   "com.android.vending", "com.sec.android.app.launcher",
                   "com.sec.phone", "com.sec.imsservice", "com.sec.epdg",
                   "com.samsung.android.honeyboard", "com.samsung.android.incallui",
                   "com.samsung.android.dialer", "com.sec.android.app.camera",
                   "com.google.android.webview", "com.google.android.packageinstaller",
                   "com.google.android.permissioncontroller", "com.google.android.setupwizard",
                   "com.sec.android.app.SecSetupWizard", "com.sec.android.app.setupwizard"}
PROTECTED_PREFIXES = ("com.android.", "com.qualcomm.", "com.mediatek.", "com.qti.", "org.codeaurora.",
                      "com.google.android.networkstack", "com.google.android.ext.",
                      "com.google.android.modulemetadata", "com.google.android.captiveportallogin",
                      "com.google.android.cellbroadcast", "com.google.android.overlay.",
                      "com.google.mainline.", "com.google.android.sdksandbox",
                      "com.samsung.android.knox", "com.samsung.android.providers.",
                      "com.samsung.android.app.telephonyui", "com.samsung.android.networkstack",
                      "com.sec.imsservice", "com.samsung.ims.", "com.samsung.android.mdm",
                      "com.miui.system", "com.huawei.systemserver", "com.oplus.battery")
DYNAMIC = set()  # paquets vitaux détectés sur le téléphone connecté


def is_protected(pkg):
    return pkg in DYNAMIC or pkg in PROTECTED_EXACT or pkg.startswith(PROTECTED_PREFIXES)


# ----------------------------------------------------------------- adb

def find_adb():
    for cand in (shutil.which("adb"),
                 EXE_DIR / "platform-tools" / "adb",
                 EXE_DIR / "platform-tools" / "adb.exe",
                 APP_DIR / "platform-tools" / "adb",
                 APP_DIR / "platform-tools" / "adb.exe"):
        if cand and pathlib.Path(cand).exists():
            return str(cand)
    return None


def adb(args, serial=None, timeout=60):
    exe = find_adb()
    if not exe:
        raise RuntimeError("adb introuvable. Installe « platform-tools » de Google "
                           "ou place le dossier platform-tools à côté du programme.")
    cmd = [exe] + (["-s", serial] if serial else []) + list(args)
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL, **kw)
    return (r.stdout + r.stderr).replace("\r", "").strip()


def devices():
    """[(serial, état, modèle)]. Seul l'état « device » est utilisable."""
    out = adb(["devices", "-l"])
    res = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and not line.startswith("*"):
            model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "?")
            res.append((parts[0], parts[1], model))
    return res


def _pkgs(serial, *flags):
    out = adb(["shell", "pm", "list", "packages", *flags], serial)
    return {l[len("package:"):].strip() for l in out.splitlines() if l.startswith("package:")}


def list_packages(serial):
    """Retourne {paquet: {"system": bool, "disabled": bool, "removed": bool}}."""
    installed = _pkgs(serial, "--user", "0")
    user = _pkgs(serial, "-3", "--user", "0")
    disabled = _pkgs(serial, "-d", "--user", "0")
    everything = _pkgs(serial, "-u")  # inclut les paquets retirés pour l'utilisateur 0
    res = {}
    for p in everything:
        res[p] = {"system": p not in user, "disabled": p in disabled,
                  "removed": p not in installed}
    return res


def _first_pkg(text):
    for tok in text.replace(",", " ").split():
        pkg = tok.split("/")[0].strip()
        if pkg.count(".") >= 1 and all(c.isalnum() or c in "._" for c in pkg):
            return pkg
    return None


def dynamic_protected(serial):
    """Détecte les paquets vitaux du téléphone : lanceur, téléphone, SMS, clavier, assistant."""
    found = set()
    for role in ("HOME", "DIALER", "SMS", "ASSISTANT"):
        out = adb(["shell", "cmd", "role", "get-role-holders", f"android.app.role.{role}"], serial)
        p = _first_pkg(out)
        if p:
            found.add(p)
    out = adb(["shell", "settings", "get", "secure", "default_input_method"], serial)
    if _first_pkg(out):
        found.add(_first_pkg(out))
    out = adb(["shell", "cmd", "package", "resolve-activity", "--brief", "-a",
               "android.intent.action.MAIN", "-c", "android.intent.category.HOME"], serial)
    if out.strip() and _first_pkg(out.splitlines()[-1]):
        found.add(_first_pkg(out.splitlines()[-1]))
    return found


def device_info(serial):
    g = lambda k: adb(["shell", "getprop", k], serial)
    return {"brand": g("ro.product.manufacturer").lower(), "model": g("ro.product.model"),
            "android": g("ro.build.version.release")}


def remove(serial, pkg):
    out = adb(["shell", "pm", "uninstall", "--user", "0", pkg], serial)
    return out.strip().endswith("Success"), out


def restore(serial, pkg):
    out = adb(["shell", "cmd", "package", "install-existing", "--user", "0", pkg], serial)
    return "installed for user" in out, out


def write_log(serial, model, removed):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = DATA_DIR / f"removed_{stamp}.json"
    path.write_text(json.dumps({"date": stamp, "serial": serial, "model": model,
                                "removed": removed}, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load_presets(brand=None):
    """{nom: [paquets]}. Si brand est donné, seulement les préréglages de cette marque
    (ou sans marque). Les entrées sont {"brands": [...], "tested": "...", "packages": [...]}."""
    for base in (APP_DIR, EXE_DIR):
        f = base / "presets.json"
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            return {k: v["packages"] for k, v in data.items()
                    if not brand or not v.get("brands") or brand in v["brands"]}
    return {}


# ----------------------------------------------------------------- CLI

def pick_device(wanted=None):
    ok = [d for d in devices() if d[1] == "device"]
    if wanted:
        ok = [d for d in ok if d[0] == wanted]
    if not ok:
        raise RuntimeError("Aucun téléphone prêt (débogage USB activé et autorisé ?).")
    if len(ok) > 1:
        raise RuntimeError("Plusieurs appareils : précise --serial parmi "
                           + ", ".join(d[0] for d in ok))
    return ok[0]


def read_names(args):
    names = list(args.packages)
    if args.file:
        names += [l.strip() for l in pathlib.Path(args.file).read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.startswith("#")]
    if getattr(args, "preset", None):
        presets = load_presets()
        for p in args.preset:
            if p not in presets:
                raise RuntimeError(f"Préréglage inconnu : {p}. Disponibles : {', '.join(presets)}")
            names += presets[p]
    return list(dict.fromkeys(names))


def cli(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--serial", help="numéro de série adb (si plusieurs appareils)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="interface graphique (par défaut)")
    l = sub.add_parser("list", help="liste les paquets")
    l.add_argument("--removed", action="store_true", help="seulement les paquets retirés")
    l.add_argument("--user", action="store_true", help="seulement tes applications")
    for name, helptxt in (("remove", "retire des paquets"), ("restore", "restaure des paquets")):
        s = sub.add_parser(name, help=helptxt)
        s.add_argument("packages", nargs="*")
        s.add_argument("--file", help="fichier texte, un paquet par ligne")
        if name == "remove":
            s.add_argument("--preset", action="append", help="nom d'un préréglage (répétable)")
        s.add_argument("--apply", action="store_true", help="exécuter vraiment (sinon simulation)")
    sub.add_parser("presets", help="liste les préréglages")
    args = ap.parse_args(argv)

    if args.cmd in (None, "gui"):
        return gui()
    if args.cmd == "presets":
        for k, v in load_presets().items():
            print(f"{k} ({len(v)})")
        return 0

    serial, _, model = pick_device(args.serial)
    DYNAMIC.update(dynamic_protected(serial))
    pk = list_packages(serial)
    if args.cmd == "list":
        for p in sorted(pk):
            i = pk[p]
            if args.removed and not i["removed"]:
                continue
            if args.user and i["system"]:
                continue
            print(f"{'RETIRE ' if i['removed'] else '       '}"
                  f"{'sys ' if i['system'] else 'user'} {p}{'  [protégé]' if is_protected(p) else ''}")
        return 0

    names = read_names(args)
    if not names:
        print("Rien à faire : donne des paquets, --file ou --preset.")
        return 1
    done, log = 0, []
    for p in names:
        if args.cmd == "remove":
            if is_protected(p):
                print(f"REFUSÉ   {p} (protégé)"); continue
            if p not in pk or pk[p]["removed"]:
                print(f"IGNORÉ   {p} (absent ou déjà retiré)"); continue
            if not args.apply:
                print(f"SIMULÉ   {p}"); continue
            ok, msg = remove(serial, p)
        else:
            if not args.apply:
                print(f"SIMULÉ   {p}"); continue
            ok, msg = restore(serial, p)
        print(f"{'OK      ' if ok else 'ÉCHEC   '} {p}" + ("" if ok else f" : {msg}"))
        if ok:
            done += 1
            log.append(p)
    if args.cmd == "remove" and args.apply and log:
        print("Journal :", write_log(serial, model, log))
    if not args.apply:
        print("\nSimulation seulement. Ajoute --apply pour exécuter.")
    return 0


# ----------------------------------------------------------------- GUI

def gui():
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("Android Debloat")
    try:  # icône de la fenêtre (PNG partout, .ico en plus sous Windows)
        root._icon = tk.PhotoImage(file=str(APP_DIR / "assets" / "icon-256.png"))
        root.iconphoto(True, root._icon)
        if os.name == "nt":
            root.iconbitmap(str(APP_DIR / "assets" / "icon.ico"))
    except Exception:
        pass  # sans icône, le programme fonctionne quand même
    root.geometry("900x620")
    state = {"serial": None, "model": "", "pk": {}, "checked": set()}
    presets = load_presets()

    top = ttk.Frame(root, padding=6)
    top.pack(fill="x")
    dev_lbl = ttk.Label(top, text="Aucun téléphone")
    dev_lbl.pack(side="left")
    mode = tk.StringVar(value="installed")
    ttk.Radiobutton(top, text="Installées", variable=mode, value="installed",
                    command=lambda: refresh_view()).pack(side="left", padx=(20, 4))
    ttk.Radiobutton(top, text="Retirées", variable=mode, value="removed",
                    command=lambda: refresh_view()).pack(side="left", padx=4)
    only_sys = tk.BooleanVar(value=True)
    ttk.Checkbutton(top, text="Système seulement", variable=only_sys,
                    command=lambda: refresh_view()).pack(side="left", padx=12)
    ttk.Button(top, text="Actualiser", command=lambda: load()).pack(side="right")

    bar = ttk.Frame(root, padding=(6, 0))
    bar.pack(fill="x")
    ttk.Label(bar, text="Filtre :").pack(side="left")
    flt = tk.StringVar()
    flt.trace_add("write", lambda *a: refresh_view())
    ttk.Entry(bar, textvariable=flt, width=28).pack(side="left", padx=4)
    ttk.Label(bar, text="Préréglage :").pack(side="left", padx=(16, 4))
    pre = tk.StringVar()
    cb = ttk.Combobox(bar, textvariable=pre, values=list(presets), state="readonly", width=36)
    cb.pack(side="left")
    ttk.Button(bar, text="Cocher", command=lambda: check_preset()).pack(side="left", padx=4)
    ttk.Button(bar, text="Tout décocher", command=lambda: (state["checked"].clear(), refresh_view())
               ).pack(side="left", padx=4)

    cols = ("sel", "pkg", "type", "etat")
    tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="browse")
    for c, t, w in (("sel", "", 40), ("pkg", "Paquet", 520), ("type", "Type", 90), ("etat", "État", 160)):
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor="w" if c == "pkg" else "center")
    sb = ttk.Scrollbar(root, command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True, padx=6, pady=6)

    foot = ttk.Frame(root, padding=6)
    foot.pack(fill="x")
    dry = tk.BooleanVar(value=True)
    ttk.Checkbutton(foot, text="Simulation (ne rien exécuter)", variable=dry).pack(side="left")
    status = ttk.Label(foot, text="")
    status.pack(side="left", padx=16)
    act = ttk.Button(foot, text="Appliquer")
    act.pack(side="right")

    def load():
        try:
            devs = [d for d in devices() if d[1] == "device"]
            if not devs:
                bad = devices()
                dev_lbl.config(text="Aucun téléphone prêt" + (f" ({bad[0][1]})" if bad else ""))
                state.update(serial=None, pk={})
                refresh_view()
                return
            state["serial"], _, state["model"] = devs[0]
            info = device_info(state["serial"])
            DYNAMIC.clear()
            DYNAMIC.update(dynamic_protected(state["serial"]))
            presets.clear()
            presets.update(load_presets(info["brand"]))
            cb.config(values=list(presets))
            dev_lbl.config(text=f"{info['brand']} {info['model']} · Android {info['android']}"
                                f"  ({state['serial']})")
            status.config(text="Lecture des paquets…")
            root.update_idletasks()
            state["pk"] = list_packages(state["serial"])
            state["checked"].clear()
            status.config(text=f"{len(state['pk'])} paquets")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))
        refresh_view()

    def refresh_view():
        tree.delete(*tree.get_children())
        want_removed = mode.get() == "removed"
        act.config(text="Restaurer la sélection" if want_removed else "Retirer la sélection")
        q = flt.get().lower()
        for p in sorted(state["pk"]):
            i = state["pk"][p]
            if i["removed"] != want_removed:
                continue
            if only_sys.get() and not i["system"] and not want_removed:
                continue
            if q and q not in p.lower():
                continue
            prot = is_protected(p) and not want_removed
            mark = "🔒" if prot else ("☑" if p in state["checked"] else "☐")
            etat = "protégé" if prot else ("désactivé" if i["disabled"] else "")
            tree.insert("", "end", iid=p, values=(mark, p, "système" if i["system"] else "utilisateur", etat))

    def on_click(ev):
        if tree.identify_region(ev.x, ev.y) != "cell":
            return
        p = tree.identify_row(ev.y)
        if not p or (is_protected(p) and mode.get() == "installed"):
            return
        state["checked"] ^= {p}
        tree.set(p, "sel", "☑" if p in state["checked"] else "☐")
        status.config(text=f"{len(state['checked'])} cochés")

    tree.bind("<Button-1>", on_click)

    def check_preset():
        n = pre.get()
        if not n:
            return
        for p in presets[n]:
            if p in state["pk"] and not is_protected(p) and not state["pk"][p]["removed"]:
                state["checked"].add(p)
        mode.set("installed")
        only_sys.set(False)
        refresh_view()
        status.config(text=f"{len(state['checked'])} cochés")

    def apply():
        if not state["serial"]:
            return
        todo = sorted(state["checked"])
        restoring = mode.get() == "removed"
        if not todo:
            messagebox.showinfo("Rien à faire", "Coche d'abord des paquets.")
            return
        verb = "restaurer" if restoring else "retirer"
        if not dry.get() and not messagebox.askyesno(
                "Confirmer", f"{len(todo)} paquet(s) à {verb} sur {state['model']}.\n"
                             "C'est réversible, mais fais une sauvegarde avant. Continuer ?"):
            return
        ok_list, fails = [], []
        for n, p in enumerate(todo, 1):
            status.config(text=f"{n}/{len(todo)} {p}")
            root.update_idletasks()
            if dry.get():
                ok_list.append(p)
                continue
            ok, msg = (restore if restoring else remove)(state["serial"], p)
            (ok_list if ok else fails).append(p if ok else f"{p} : {msg}")
        if not dry.get() and ok_list and not restoring:
            write_log(state["serial"], state["model"], ok_list)
        txt = f"{len(ok_list)} {'simulés' if dry.get() else 'réussis'}"
        if fails:
            txt += f", {len(fails)} échec(s) :\n" + "\n".join(fails[:10])
        messagebox.showinfo("Terminé", txt)
        if not dry.get():
            load()

    act.config(command=apply)
    root.after(200, load)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(cli(sys.argv[1:]))
    except RuntimeError as e:
        print("Erreur :", e, file=sys.stderr)
        sys.exit(2)
