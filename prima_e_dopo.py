#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prima e dopo (versione 1.10) – finestra e comandi
© 2026 Edoardo Battistel

Lo stesso oggetto del cielo a anni di distanza: animazioni (GIF, MP4, pagina con
cursore) e misura del movimento (espansione di M 1, moto proprio della stella di Barnard).

Uso:
  prima_e_dopo.py                         apre la finestra
  prima_e_dopo.py --autotest              prova senza rete (dati simulati), per la compilazione
  prima_e_dopo.py --diagnostica           prova gli archivi in rete
  prima_e_dopo.py --fai M1_ottico         cerca le epoche e fa tutto da riga di comando
                  (chiavi: M1_ottico, M1_raggiX, EtaCar_Hubble, CasA_raggiX, Barnard, Groombridge1830,
                  61Cygni, Lalande21185, NGC2261, NGC1555)
I risultati vanno in ~/Scrivania/Astronomia/Prima_e_dopo/<oggetto>/.
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

import motore_pd as M

VERSIONE = M.VERSIONE
FILE_IMPOSTAZIONI = Path.home() / ".prima_e_dopo.json"
SCALE = [1.0, 1.25, 1.5, 1.75, 2.0]          # tendina «Dimensione testo»
SCALA_PREDEFINITA = 1.5
ICONA = "prima_e_dopo.png"


def leggi_impostazioni():
    try:
        d = json.loads(FILE_IMPOSTAZIONI.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def scrivi_impostazioni(d):
    try:
        FILE_IMPOSTAZIONI.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def apri_esterno(percorso):
    try:
        subprocess.Popen(["xdg-open", str(percorso)], env=M.ambiente_esterno())
        return True
    except Exception:
        try:
            import webbrowser
            webbrowser.open(Path(percorso).as_uri())
            return True
        except Exception:
            return False


# =========================================================================== finestra
def crea_finestra(base=None, autotest=False):
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, simpledialog
    import tkinter.font as tkfont
    from PIL import Image, ImageTk

    class App:
        def __init__(self, root):
            self.root = root
            self.base = base
            self.imp = leggi_impostazioni()
            self.scala = float(self.imp.get("scala", SCALA_PREDEFINITA))
            if self.scala not in SCALE:
                self.scala = SCALA_PREDEFINITA
            self.coda = queue.Queue()
            self.ferma = threading.Event()
            self.occupato = False
            self.ogg = None
            self.epoche = []
            self.ris = None
            self.foto = []          # immagini PIL delle epoche (anteprima)
            self.sopra = None
            self._tk_img = None
            self._tk_mis = None
            self._timer = None
            self._stile()
            self._costruisci()
            root.after(100, self._leggi_coda)
            i = int(self.imp.get("oggetto", 0))
            self.lista.selection_set(min(max(i, 0), len(M.OGGETTI) - 1))
            self._oggetto_scelto()

        # ---------------------------------------------------------- aspetto
        def _stile(self):
            self.font_titolo = tkfont.Font(name="FontTitoloPD", weight="bold")
            self.font_grande = tkfont.Font(name="FontGrandePD", weight="bold")
            self.font_mono = tkfont.Font(name="FontMonoPD", family="DejaVu Sans Mono")
            st = ttk.Style()
            try:
                st.theme_use("clam")
            except tk.TclError:
                pass
            st.configure(".", font="TkDefaultFont")
            st.configure("Grande.TButton", font=self.font_grande)
            st.configure("Vai.TButton", font=self.font_grande, foreground="#ffffff", background="#1d4ed8")
            st.map("Vai.TButton", background=[("active", "#2563eb"), ("disabled", "#9ca3af")])
            st.configure("Titolo.TLabel", font=self.font_titolo)
            st.configure("TNotebook.Tab", font="TkDefaultFont")
            st.configure("Treeview.Heading", font=self.font_grande)
            self.root.option_add("*TCombobox*Listbox.font", "TkDefaultFont")
            self._applica_dimensioni()

        def _applica_dimensioni(self):
            base_px = int(round(11 * self.scala))
            for nome in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont",
                         "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
                try:
                    tkfont.nametofont(nome).configure(size=base_px)
                except tk.TclError:
                    pass
            self.font_titolo.configure(size=int(round(base_px * 1.35)))
            self.font_grande.configure(size=int(round(base_px * 1.1)))
            self.font_mono.configure(size=base_px - 1)
            st = ttk.Style()
            p = int(round(6 * self.scala))
            st.configure("TButton", padding=(p + 4, p))
            st.configure("Grande.TButton", padding=(p + 8, p + 2))
            st.configure("Vai.TButton", padding=(p + 8, p + 3))
            st.configure("TNotebook.Tab", padding=(p * 2 + 4, p))
            st.configure("TCombobox", arrowsize=int(14 * self.scala))
            st.configure("TCheckbutton", indicatorsize=int(14 * self.scala))
            alt = tkfont.nametofont("TkDefaultFont").metrics("linespace")
            st.configure("Treeview", rowheight=int(alt * 1.45))
            for o in ("Vertical", "Horizontal"):
                st.configure(f"{o}.TScrollbar", arrowsize=int(16 * self.scala), width=int(16 * self.scala))
            st.configure("TProgressbar", thickness=int(12 * self.scala))
            if getattr(self, "sc_tempo", None) is not None:
                self.sc_tempo.configure(width=int(18 * self.scala), sliderlength=int(30 * self.scala))
            if getattr(self, "lista", None) is not None:
                self.lista.configure(font="TkDefaultFont")

        # ---------------------------------------------------------- costruzione
        def _costruisci(self):
            r = self.root
            alto = ttk.Frame(r, padding=(12, 8))
            alto.pack(side="top", fill="x")
            ttk.Label(alto, text="Prima e dopo", style="Titolo.TLabel").pack(side="left")
            ttk.Label(alto, text="  lo stesso oggetto a anni di distanza", foreground="#555").pack(side="left")
            ttk.Button(alto, text="📂 Cartella dei risultati", command=self.apri_cartella).pack(side="right")
            self.var_scala = tk.StringVar(value=f"{int(self.scala * 100)} %")
            cb = ttk.Combobox(alto, textvariable=self.var_scala, state="readonly", width=6,
                              values=[f"{int(v * 100)} %" for v in SCALE])
            cb.pack(side="right", padx=(4, 18))
            cb.bind("<<ComboboxSelected>>", lambda e: self._cambia_scala())
            ttk.Label(alto, text="Dimensione testo").pack(side="right")

            basso = ttk.Frame(r, padding=(12, 4))
            basso.pack(side="bottom", fill="x")
            self.var_stato = tk.StringVar(value="Scegli un oggetto, poi «1. Cerca le epoche».")
            ttk.Label(basso, textvariable=self.var_stato).pack(side="left", fill="x", expand=True)
            self.barra = ttk.Progressbar(basso, length=280, mode="determinate", maximum=1.0)
            self.barra.pack(side="right")
            ttk.Label(basso, text=f"{M.FIRMA} · v{VERSIONE}", foreground="#666").pack(side="right", padx=12)

            corpo = ttk.PanedWindow(r, orient="horizontal")
            corpo.pack(side="top", fill="both", expand=True, padx=8, pady=4)

            # --- sinistra: lista degli oggetti e comandi
            sx = ttk.Frame(corpo, padding=(6, 4))
            corpo.add(sx, weight=1)
            ttk.Label(sx, text="Scegli l'oggetto", style="Titolo.TLabel").pack(anchor="w")
            self.lista = tk.Listbox(sx, height=len(M.OGGETTI) + len(M.IN_ARRIVO), exportselection=False,
                                    font="TkDefaultFont", activestyle="none", selectbackground="#1d4ed8",
                                    selectforeground="#ffffff", relief="flat", highlightthickness=1)
            for o in M.OGGETTI:
                self.lista.insert("end", o["nome"])
            for nome, nota in M.IN_ARRIVO:
                self.lista.insert("end", f"{nome}  ({nota})")
                self.lista.itemconfig("end", foreground="#9ca3af", selectforeground="#e5e7eb",
                                      selectbackground="#9ca3af")
            self.lista.pack(fill="x", pady=(4, 8))
            self.lista.bind("<<ListboxSelect>>", lambda e: self._oggetto_scelto())
            self.txt_descr = tk.Text(sx, height=8, wrap="word", font="TkDefaultFont", relief="flat",
                                     background="#f3f4f6", padx=10, pady=8, cursor="arrow")
            self.txt_descr.pack(fill="both", expand=True)
            comandi = ttk.Frame(sx)
            comandi.pack(fill="x", pady=(8, 0))
            self.bt_cerca = ttk.Button(comandi, text="1.  Cerca le epoche", style="Grande.TButton", command=self.cerca)
            self.bt_cerca.pack(fill="x", pady=3)
            self.bt_aggiungi = ttk.Button(comandi, text="➕  Aggiungi file tuoi…", command=self.aggiungi_file)
            self.bt_aggiungi.pack(fill="x", pady=3)
            self.bt_prepara = ttk.Button(comandi, text="2.  Prepara: scarica, allinea, misura, anima",
                                         style="Vai.TButton", command=self.prepara)
            self.bt_prepara.pack(fill="x", pady=(10, 3))
            self.bt_ferma = ttk.Button(comandi, text="■  Ferma", command=self.ferma_lavoro, state="disabled")
            self.bt_ferma.pack(fill="x", pady=3)
            self.var_nitidezza = tk.BooleanVar(value=bool(self.imp.get("nitidezza_uguale", True)))
            ttk.Checkbutton(comandi, text="Stessa nitidezza per tutte le epoche", variable=self.var_nitidezza
                            ).pack(anchor="w", pady=(8, 2))
            self.var_mp4 = tk.BooleanVar(value=bool(self.imp.get("mp4", True)))
            ttk.Checkbutton(comandi, text="Crea anche l'MP4 (serve ffmpeg)", variable=self.var_mp4).pack(anchor="w")

            # --- destra: schede
            self.nb = ttk.Notebook(corpo)
            corpo.add(self.nb, weight=3)
            # Epoche
            t1 = ttk.Frame(self.nb, padding=6)
            self.nb.add(t1, text="Epoche")
            colonne = ("usa", "anno", "nome", "banda", "origine", "stato", "nota")
            self.tab = ttk.Treeview(t1, columns=colonne, show="headings", selectmode="browse")
            intest = {"usa": "Usa", "anno": "Anno", "nome": "Telescopio / survey", "banda": "Banda",
                      "origine": "Da", "stato": "File", "nota": "Note"}
            larg = {"usa": 70, "anno": 110, "nome": 260, "banda": 170, "origine": 110, "stato": 130, "nota": 360}
            for c in colonne:
                self.tab.heading(c, text=intest[c])
                self.tab.column(c, width=int(larg[c] * self.scala / 1.5), anchor="w" if c in ("nome", "nota", "banda") else "center",
                                stretch=c == "nota")
            sb = ttk.Scrollbar(t1, orient="vertical", command=self.tab.yview)
            self.tab.configure(yscrollcommand=sb.set)
            ttk.Label(t1, text="Clic su «Usa» per includere o escludere un'epoca · doppio clic sull'anno per "
                               "correggerlo (es. 1955,85 oppure 1955-11-08)", foreground="#555", wraplength=900
                      ).pack(side="bottom", anchor="w", pady=(6, 0))
            sb.pack(side="right", fill="y")
            self.tab.pack(fill="both", expand=True)
            self.tab.bind("<Button-1>", self._clic_tabella)
            self.tab.bind("<Double-Button-1>", self._doppio_clic_tabella)
            self.tab.tag_configure("no", foreground="#9ca3af")
            self.tab.tag_configure("errore", foreground="#b91c1c")
            # Anteprima
            t2 = ttk.Frame(self.nb, padding=6)
            self.nb.add(t2, text="Anteprima")
            pulsanti = ttk.Frame(t2)
            pulsanti.pack(side="bottom", fill="x", pady=(6, 0))
            self.bt_gif = ttk.Button(pulsanti, text="▶ Apri la GIF", command=lambda: self._apri("gif"))
            self.bt_gif.pack(side="left")
            self.bt_mp4 = ttk.Button(pulsanti, text="▶ Apri l'MP4", command=lambda: self._apri("mp4"))
            self.bt_mp4.pack(side="left", padx=6)
            self.bt_pag = ttk.Button(pulsanti, text="🌐 Pagina con il cursore", style="Grande.TButton",
                                     command=lambda: self._apri("pagina"))
            self.bt_pag.pack(side="left", padx=6)
            self.var_sopra = tk.BooleanVar(value=True)
            self.ck_sopra = ttk.Checkbutton(pulsanti, text="Frecce / traccia", variable=self.var_sopra,
                                            command=self._mostra_anteprima)
            self.ck_sopra.pack(side="right")
            riga = ttk.Frame(t2)
            riga.pack(side="bottom", fill="x", pady=(6, 0))
            ttk.Label(riga, text="Epoca:").pack(side="left")
            self.var_tempo = tk.DoubleVar(value=0.0)
            self.sc_tempo = tk.Scale(riga, from_=0, to=1, resolution=0.02, orient="horizontal", variable=self.var_tempo,
                                     showvalue=False, width=int(18 * self.scala), sliderlength=int(30 * self.scala),
                                     command=lambda v: self._mostra_anteprima())
            self.sc_tempo.pack(side="left", fill="x", expand=True, padx=8)
            self.lab_tempo = ttk.Label(riga, text="", width=16)
            self.lab_tempo.pack(side="left")
            self.lab_img = tk.Label(t2, background="#0d0f14", foreground="#9ca3af", font=self.font_grande,
                                    text="Qui compare l'anteprima dopo «2. Prepara».")
            self.lab_img.pack(fill="both", expand=True)
            self.lab_img.bind("<Configure>", lambda e: self._anteprima_presto())
            # Misura
            t3 = ttk.Frame(self.nb, padding=6)
            self.nb.add(t3, text="Misura")
            pm = ttk.PanedWindow(t3, orient="vertical")
            pm.pack(fill="both", expand=True)
            self.lab_mis = tk.Label(pm, background="#ffffff")
            pm.add(self.lab_mis, weight=3)
            self.lab_mis.bind("<Configure>", lambda e: self._figura_presto())
            fr = ttk.Frame(pm)
            pm.add(fr, weight=2)
            self.txt_ris = tk.Text(fr, wrap="word", font=self.font_mono, padx=12, pady=10, height=10)
            sb2 = ttk.Scrollbar(fr, orient="vertical", command=self.txt_ris.yview)
            self.txt_ris.configure(yscrollcommand=sb2.set)
            sb2.pack(side="right", fill="y")
            self.txt_ris.pack(fill="both", expand=True)
            # Registro
            t4 = ttk.Frame(self.nb, padding=6)
            self.nb.add(t4, text="Registro")
            self.txt_log = tk.Text(t4, wrap="word", font=self.font_mono, padx=10, pady=8)
            sb3 = ttk.Scrollbar(t4, orient="vertical", command=self.txt_log.yview)
            self.txt_log.configure(yscrollcommand=sb3.set)
            sb3.pack(side="right", fill="y")
            self.txt_log.pack(fill="both", expand=True)

        def _cambia_scala(self):
            try:
                self.scala = float(self.var_scala.get().replace("%", "").strip()) / 100
            except ValueError:
                return
            self.imp["scala"] = self.scala
            scrivi_impostazioni(self.imp)
            self._applica_dimensioni()

        # ---------------------------------------------------------- oggetto
        def _oggetto_scelto(self):
            sel = self.lista.curselection()
            if not sel:
                return
            i = sel[0]
            self.txt_descr.configure(state="normal")
            self.txt_descr.delete("1.0", "end")
            if i >= len(M.OGGETTI):
                nome, nota = M.IN_ARRIVO[i - len(M.OGGETTI)]
                self.txt_descr.insert("1.0", f"{nome}\n\nNon ancora disponibile: arriverà in una {nota}.")
                self.txt_descr.configure(state="disabled")
                if not self.occupato:
                    for b in (self.bt_cerca, self.bt_aggiungi, self.bt_prepara):
                        b.configure(state="disabled")
                return
            if self.occupato:
                self.lista.selection_clear(0, "end")
                self.lista.selection_set(M.OGGETTI.index(next(o for o in M.OGGETTI if o["chiave"] == self.ogg["chiave"])))
                return
            self.ogg = dict(M.OGGETTI[i])
            self.imp["oggetto"] = i
            scrivi_impostazioni(self.imp)
            self.txt_descr.insert("1.0", self.ogg["descrizione"])
            self.txt_descr.configure(state="disabled")
            self.epoche = M.leggi_epoche(self.ogg, self.base)
            self._riempi_tabella()
            self._carica_risultati()
            self.bt_cerca.configure(state="normal" if self.ogg.get("fonti") or self.ogg.get("alias") else "disabled")
            self.bt_aggiungi.configure(state="normal")
            self.bt_prepara.configure(state="normal")
            if self.epoche:
                self.var_stato.set(f"{self.ogg['nome']}: {len(self.epoche)} epoche già trovate.")
            elif self.ogg["chiave"] == "file_tuoi":
                self.var_stato.set("Aggiungi almeno due FITS dello stesso oggetto con «Aggiungi file tuoi…».")
            else:
                self.var_stato.set(f"{self.ogg['nome']}: premi «1. Cerca le epoche».")

        def _riempi_tabella(self):
            self.tab.delete(*self.tab.get_children())
            for k, e in enumerate(self.epoche):
                ha_file = bool(e.get("file")) and Path(e["file"]).exists()
                stato = "ERRORE" if e.get("errore") else ("scaricato" if ha_file and e.get("origine") != "file tuo"
                                                          else ("tuo file" if ha_file else "da scaricare"))
                anno = M.testo_anno(e.get("anno"), 2) if e.get("anno") is not None else "scrivilo"
                if e.get("anno_approssimato"):
                    anno += " ?"
                nota = e.get("errore") or e.get("nota") or ""
                tag = "errore" if e.get("errore") else ("" if e.get("usa") else "no")
                self.tab.insert("", "end", iid=str(k), tags=(tag,),
                                values=("☑" if e.get("usa") else "☐", anno, e.get("etichetta", ""), e.get("banda", ""),
                                        "archivio" if e.get("origine") == "archivio" else "file tuo", stato, nota))

        def _clic_tabella(self, ev):
            if self.occupato:
                return
            if self.tab.identify("region", ev.x, ev.y) != "cell" or self.tab.identify_column(ev.x) != "#1":
                return
            riga = self.tab.identify_row(ev.y)
            if not riga:
                return
            e = self.epoche[int(riga)]
            e["usa"] = not e.get("usa")
            e["usa_manuale"] = True
            M.salva_epoche(self.ogg, self.epoche, self.base)
            self._riempi_tabella()
            return "break"

        def _doppio_clic_tabella(self, ev):
            if self.occupato or self.tab.identify_column(ev.x) != "#2":
                return
            riga = self.tab.identify_row(ev.y)
            if not riga:
                return
            e = self.epoche[int(riga)]
            att = M.testo_anno(e.get("anno"), 3) if e.get("anno") is not None else ""
            t = simpledialog.askstring("Anno dell'osservazione",
                                       f"{e.get('etichetta', '')}\n\nAnno (es. 1955,85) oppure data (es. 1955-11-08):",
                                       initialvalue=att, parent=self.root)
            if t is None:
                return
            a = M.leggi_data_testo(t.strip().replace(",", "."))
            if a is None or not (1850 < a < 2100):
                messagebox.showerror("Anno", f"Non capisco «{t}». Scrivi per esempio 1955,85 oppure 1955-11-08.")
                return
            e.update(anno=a, anno_manuale=True, anno_approssimato=False, usa=True, usa_manuale=True, data=M.data_da_anno(a).strftime("%Y-%m-%d"))
            e["nota"] = "anno scritto da te"
            self.epoche = M.ordina_epoche(self.epoche)
            M.salva_epoche(self.ogg, self.epoche, self.base)
            self._riempi_tabella()

        # ---------------------------------------------------------- lavori
        def _in_thread(self, funzione, *arg):
            def corpo():
                try:
                    funzione(*arg)
                except M.Fermato:
                    self.coda.put(("stato", "Fermato."))
                except Exception as e:
                    self.coda.put(("errore", f"{e}", traceback.format_exc()))
                finally:
                    self.coda.put(("libero", None))
            self.occupato = True
            self.ferma.clear()
            for b in (self.bt_cerca, self.bt_aggiungi, self.bt_prepara):
                b.configure(state="disabled")
            self.bt_ferma.configure(state="normal")
            threading.Thread(target=corpo, daemon=True).start()

        def _log(self, testo):
            self.coda.put(("log", str(testo)))

        def _progresso(self, frazione, testo=None):
            self.coda.put(("progresso", frazione))
            if testo:
                self.coda.put(("stato", testo))

        def cerca(self):
            if self.occupato or self.ogg is None:
                return
            self.nb.select(0)
            self.var_stato.set("Cerco le epoche negli archivi e tra i tuoi file…")
            self.barra.configure(mode="indeterminate")
            self.barra.start(15)

            def lavoro():
                ep = M.cerca_epoche(self.ogg, self.base, self._log, self.ferma)
                self.coda.put(("epoche", ep))
            self._in_thread(lavoro)

        def aggiungi_file(self):
            if self.occupato or self.ogg is None:
                return
            iniziale = str(M.cartella_astronomia())
            percorsi = []
            if shutil.which("zenity"):
                try:
                    r = subprocess.run(["zenity", "--file-selection", "--multiple", "--separator=\n",
                                        "--title=Scegli i FITS (anche più di uno)", f"--filename={iniziale}/",
                                        "--file-filter=FITS | *.fits *.fit *.fts *.fits.gz *.FITS *.FIT",
                                        "--file-filter=Tutti i file | *"],
                                       capture_output=True, text=True, env=M.ambiente_esterno(), timeout=900)
                    if r.returncode == 0:
                        percorsi = [p for p in r.stdout.strip().splitlines() if p]
                    elif r.returncode == 1:
                        return
                except Exception:
                    percorsi = []
            if not percorsi:
                percorsi = list(filedialog.askopenfilenames(
                    title="Scegli i FITS", initialdir=iniziale,
                    filetypes=[("FITS", "*.fits *.fit *.fts *.fits.gz"), ("Tutti i file", "*")]) or [])
            if not percorsi:
                return
            presenti = {e.get("file") for e in self.epoche}
            aggiunti, errori = 0, []
            for p in percorsi:
                if p in presenti:
                    continue
                try:
                    e = M.epoca_da_file(p)
                    i = e.pop("_info", {})
                    if self.ogg.get("ra") is not None and i.get("ra") is not None:
                        d = M.separazione_arcsec(i["ra"], i["dec"], *M.centro_campo(self.ogg))
                        if d > self.ogg["campo_arcmin"] * 60:
                            e["nota"] = f"ATTENZIONE: centro del file a {d / 60:.0f}′ dall'oggetto"
                    self.epoche.append(e)
                    aggiunti += 1
                except Exception as ex:
                    errori.append(f"{Path(p).name}: {ex}")
            self.epoche = M.ordina_epoche(self.epoche)
            M.salva_epoche(self.ogg, self.epoche, self.base)
            self._riempi_tabella()
            self.nb.select(0)
            self.var_stato.set(f"Aggiunti {aggiunti} file." + (f" Non letti: {len(errori)}." if errori else ""))
            if errori:
                messagebox.showwarning("File non letti", "\n".join(errori)[:1500])

        def prepara(self):
            if self.occupato or self.ogg is None:
                return
            usate = [e for e in self.epoche if e.get("usa") and e.get("anno") is not None]
            if len(usate) < 2:
                messagebox.showinfo("Prima e dopo", "Servono almeno due epoche spuntate e con l'anno.\n\n"
                                    "Premi «1. Cerca le epoche» oppure «Aggiungi file tuoi…».")
                return
            self.imp["nitidezza_uguale"] = bool(self.var_nitidezza.get())
            self.imp["mp4"] = bool(self.var_mp4.get())
            scrivi_impostazioni(self.imp)
            self.barra.configure(mode="determinate", value=0)
            self.nb.select(3)
            self._log(f"=== {self.ogg['nome']} – {time.strftime('%Y-%m-%d %H:%M')} ===")

            def lavoro():
                r = M.esegui(self.ogg, self.epoche, self.base, self._log, self.ferma, self._progresso,
                             bool(self.var_nitidezza.get()), bool(self.var_mp4.get()))
                self.coda.put(("fatto", r))
            self._in_thread(lavoro)

        def ferma_lavoro(self):
            if self.occupato:
                self.ferma.set()
                self.var_stato.set("Mi fermo appena possibile…")

        def _leggi_coda(self):
            try:
                while True:
                    tipo, *d = self.coda.get_nowait()
                    if tipo == "log":
                        self.txt_log.insert("end", d[0] + "\n")
                        self.txt_log.see("end")
                        if not d[0].startswith("   "):
                            self.var_stato.set(d[0][:170])
                    elif tipo == "stato":
                        self.var_stato.set(d[0][:170])
                    elif tipo == "progresso":
                        self.barra.configure(value=d[0])
                    elif tipo == "epoche":
                        self.epoche = d[0]
                        self._riempi_tabella()
                        n = sum(1 for e in self.epoche if e.get("usa"))
                        self.var_stato.set(f"{len(self.epoche)} epoche trovate ({n} spuntate). Controlla le date, "
                                           "poi «2. Prepara».")
                    elif tipo == "fatto":
                        r = d[0]
                        self._riempi_tabella()
                        self._carica_risultati()
                        self.nb.select(1)
                        mancano = [] if r["file"].get("mp4") or not self.var_mp4.get() else [" (MP4 non creato: vedi Registro)"]
                        self.var_stato.set(f"Fatto: {r['n_epoche']} epoche, {r['fotogrammi']} fotogrammi · "
                                           f"{r['cartella']}" + "".join(mancano))
                    elif tipo == "errore":
                        print(d[1], file=sys.stderr)
                        self.txt_log.insert("end", "ERRORE: " + d[0] + "\n")
                        self.var_stato.set(f"Errore: {d[0][:150]}")
                        self._riempi_tabella()
                        messagebox.showerror("Prima e dopo", d[0][:900])
                    elif tipo == "libero":
                        self.occupato = False
                        self.barra.stop()
                        self.barra.configure(mode="determinate")
                        for b in (self.bt_aggiungi, self.bt_prepara):
                            b.configure(state="normal")
                        self.bt_cerca.configure(state="normal" if self.ogg and (self.ogg.get("fonti") or self.ogg.get("alias"))
                                                else "disabled")
                        self.bt_ferma.configure(state="disabled")
            except queue.Empty:
                pass
            self.root.after(120, self._leggi_coda)

        # ---------------------------------------------------------- risultati
        def _carica_risultati(self):
            self.ris = M.leggi_risultati(self.ogg, self.base) if self.ogg else None
            self.foto, self.sopra = [], None
            if self.ris:
                for p in self.ris.get("immagini", []):
                    try:
                        self.foto.append(Image.open(p).convert("RGB"))
                    except OSError:
                        pass
                if self.ris.get("sopra"):
                    try:
                        self.sopra = Image.open(self.ris["sopra"]).convert("RGBA")
                    except OSError:
                        self.sopra = None
            n = len(self.foto)
            self.sc_tempo.configure(to=max(n - 1, 1))
            self.var_tempo.set(0.0)
            self.ck_sopra.configure(state="normal" if self.sopra is not None else "disabled")
            for b, k in ((self.bt_gif, "gif"), (self.bt_mp4, "mp4"), (self.bt_pag, "pagina")):
                b.configure(state="normal" if self.ris and self.ris.get(k) else "disabled")
            self._mostra_anteprima()
            self._mostra_figura()
            self.txt_ris.configure(state="normal")
            self.txt_ris.delete("1.0", "end")
            if self.ris and self.ris.get("testo"):
                try:
                    self.txt_ris.insert("1.0", Path(self.ris["testo"]).read_text(encoding="utf-8"))
                except OSError:
                    pass
            else:
                self.txt_ris.insert("1.0", "Nessun risultato ancora: «1. Cerca le epoche», poi «2. Prepara».")
            self.txt_ris.configure(state="disabled")

        def _anteprima_presto(self):
            if self._timer:
                self.root.after_cancel(self._timer)
            self._timer = self.root.after(80, self._mostra_anteprima)

        def _figura_presto(self):
            if getattr(self, "_timer_fig", None):
                self.root.after_cancel(self._timer_fig)
            self._timer_fig = self.root.after(120, self._mostra_figura)

        def _mostra_anteprima(self):
            self._timer = None
            if not self.foto:
                self.lab_img.configure(image="", text="Qui compare l'anteprima dopo «2. Prepara».")
                self.lab_tempo.configure(text="")
                return
            t = float(self.var_tempo.get())
            i = int(min(max(t, 0), len(self.foto) - 1))
            j = min(i + 1, len(self.foto) - 1)
            u = t - i
            im = self.foto[i] if u < 0.01 or i == j else Image.blend(self.foto[i], self.foto[j], u)
            if self.sopra is not None and self.var_sopra.get():
                im = Image.alpha_composite(im.convert("RGBA"), self.sopra).convert("RGB")
            w, h = max(self.lab_img.winfo_width(), 100), max(self.lab_img.winfo_height(), 100)
            lato = max(100, min(w, h) - 6)
            self._tk_img = ImageTk.PhotoImage(im.resize((lato, lato), Image.LANCZOS))
            self.lab_img.configure(image=self._tk_img, text="")
            ep = (self.ris or {}).get("epoche", [])
            if ep and j < len(ep):
                if 0.05 < u < 0.95:
                    testo = "≈ " + M.testo_anno(ep[i]["anno"] + u * (ep[j]["anno"] - ep[i]["anno"]), 0)
                else:
                    testo = M.testo_anno(ep[j if u >= 0.5 else i]["anno"], 1)
                self.lab_tempo.configure(text=testo)

        def _mostra_figura(self):
            self._timer_fig = None
            p = (self.ris or {}).get("figura")
            if not p:
                self.lab_mis.configure(image="", text="(nessuna misura per questo oggetto)", font=self.font_grande)
                return
            try:
                im = Image.open(p)
            except OSError:
                return
            w, h = max(self.lab_mis.winfo_width(), 100), max(self.lab_mis.winfo_height(), 100)
            f = min(w / im.width, h / im.height)
            self._tk_mis = ImageTk.PhotoImage(im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))),
                                                        Image.LANCZOS))
            self.lab_mis.configure(image=self._tk_mis, text="")

        def _apri(self, chiave):
            p = (self.ris or {}).get(chiave)
            if p and Path(p).exists():
                apri_esterno(p)

        def apri_cartella(self):
            c = M.cartella_oggetto(self.ogg, self.base) if self.ogg else M.cartella_risultati(self.base)
            c.mkdir(parents=True, exist_ok=True)
            apri_esterno(c)

    root = tk.Tk(className="PrimaEDopo")      # classe della finestra: «Primaedopo»
    try:
        root.iconphoto(True, tk.PhotoImage(file=str(M.risorsa(ICONA))))
    except Exception:
        pass
    root.title(f"Prima e dopo {VERSIONE}  —  {M.COPYRIGHT}")
    root.geometry("1500x950")
    root.minsize(1000, 650)
    if not autotest:
        try:
            root.attributes("-zoomed", True)
        except tk.TclError:
            pass
    app = App(root)
    return root, app


def avvia_finestra():
    root, _ = crea_finestra()
    root.mainloop()


# =========================================================================== autotest
def autotest():
    esiti = []

    def prova(nome, ok, dettaglio=""):
        esiti.append(bool(ok))
        print(f"[{'ok' if ok else 'ERRORE'}] {nome}  {dettaglio}", flush=True)

    import numpy as np
    print(f"Prima e dopo {VERSIONE} – autotest ({time.strftime('%Y-%m-%d %H:%M')})  {M.FIRMA}")
    print(f"Python {sys.version.split()[0]}, numpy {np.__version__}")
    for nome in ("scipy", "astropy", "PIL", "matplotlib"):
        try:
            mod = __import__(nome)
            prova(nome, True, getattr(mod, "__version__", ""))
        except Exception as e:
            prova(nome, False, f"{type(e).__name__}: {e}")
    try:
        from astropy.io import fits  # noqa: F401
        from astropy.wcs import WCS  # noqa: F401
        prova("astropy.io.fits e astropy.wcs", True)
    except Exception as e:
        prova("astropy.io.fits e astropy.wcs", False, str(e))
    try:
        import tkinter
        import PIL._tkinter_finder  # noqa: F401
        from PIL import ImageTk  # noqa: F401
        prova("tkinter e Pillow per Tk", True, tkinter.TkVersion)
    except Exception as e:
        prova("tkinter e Pillow per Tk", False, f"{type(e).__name__}: {e}")
    prova("icona", M.risorsa(ICONA).exists())
    ff = M.trova_ffmpeg()
    prova("ffmpeg per l'MP4 (facoltativo)", True, ff or "NON installato: niente MP4 (sudo apt install ffmpeg)")
    prova("lettura delle date", abs(M.leggi_data_testo("1955-11-08") - 1955.853) < 0.002
          and abs(M.leggi_data_testo("08/11/55") - 1955.853) < 0.002
          and abs(M.anno_da_mjd(51544.5) - 2000.0) < 0.01 and M.testo_mese(2024.978) == "dic 2024"
          and abs(M.leggi_data_testo("1951-11-07T09:60:00") - 1951.8505) < 0.001
          and abs(M.leggi_data_testo("1991/10/18") - 1991.7945) < 0.001)
    g = M.Griglia(83.633083, 22.0145, 1.0, 840)
    ra, dec = g.pix2world(np.array([10.0, 500.0]), np.array([700.0, 3.0]))
    x, y = g.world2pix(ra, dec)
    prova("griglia comune (andata e ritorno)", np.allclose(x, [10, 500], atol=1e-6) and np.allclose(y, [700, 3], atol=1e-6))
    import prova_sintetica as P
    with tempfile.TemporaryDirectory(prefix="autotest_pd_") as tmp:
        tmp = Path(tmp)
        try:
            t0 = time.time()
            files = P.crea_m1(tmp / "m1", saturazione=(1.0, 1.0))
            ep = [M.epoca_da_file(f) for f in files]
            r = M.esegui(M.oggetto("M1_ottico"), ep, tmp / "ris", log=lambda s: None, fa_mp4=bool(ff))
            m = r["misura"] or {}
            az = m.get("anno_zero")
            prova("M 1 simulata: anno dell'esplosione (vero 1130)", az is not None and abs(az - 1130) < 40,
                  f"{az:.0f} ± {m.get('err_anno_zero') or 0:.0f}, ingrandimento {m.get('ingrandimento_pc', 0):.2f} % "
                  f"(vero 7,01 %), {time.time() - t0:.0f} s" if az else "nessuna misura")
            prova("M 1 simulata: frecce sui filamenti", len(m.get("frecce", [])) >= 15, f"{len(m.get('frecce', []))} frecce")
            prova("M 1 simulata: centro dell'espansione", (m.get("centro_dal_riferimento_arcsec") or 99) < 5,
                  f"{m.get('centro_dal_riferimento_arcsec', 0):.1f}″ dal centro vero")
            fatti = r["file"]
            ok = all(Path(fatti[k]).stat().st_size > 5000 for k in ("gif", "pagina", "figura")) \
                and Path(fatti["testo"]).stat().st_size > 300
            prova("file: GIF, pagina con cursore, figura, testo", ok,
                  ", ".join(f"{k} {Path(v).stat().st_size // 1024} kB" for k, v in fatti.items() if k != "allineate"))
            if ff:
                prova("MP4", "mp4" in fatti and Path(fatti["mp4"]).stat().st_size > 10000)
            t0 = time.time()
            files = P.crea_barnard(tmp / "barnard")
            r = M.esegui(dict(M.oggetto("Barnard"), cerca_gaia=False), [M.epoca_da_file(f) for f in files],
                         tmp / "ris", log=lambda s: None,
                         fa_mp4=False)
            m = r["misura"] or {}
            mu = m.get("mu_mas", 0) / 1000
            prova("stella di Barnard simulata: moto proprio (Gaia 10,39″/anno)", abs(mu - 10.39) < 0.2,
                  f"{mu:.2f}″/anno, {m.get('v_kms', 0):.0f} km/s, {time.time() - t0:.0f} s")
        except Exception as e:
            prova("motore con dati simulati", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        # finestra vera per un istante (anteprima e figura comprese)
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            try:
                root, app = crea_finestra(base=tmp / "ris", autotest=True)
                root.update()
                app.lista.selection_clear(0, "end")
                app.lista.selection_set(0)
                app._oggetto_scelto()
                app.nb.select(1)
                root.update()
                app.var_tempo.set(0.5)
                app._mostra_anteprima()
                app.nb.select(2)
                root.update()
                ok = len(app.foto) >= 2 and app._tk_img is not None
                app.scala = 2.0
                app._applica_dimensioni()
                root.update()
                root.destroy()
                prova("finestra con anteprima e figura", ok, f"{len(app.foto)} epoche nell'anteprima")
            except Exception as e:
                prova("finestra con anteprima e figura", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        else:
            prova("finestra (saltata: nessuno schermo)", True)
    ok = all(esiti)
    print("AUTOTEST " + ("RIUSCITO" if ok else "FALLITO"))
    return 0 if ok else 1


def fai(chiave):
    try:
        ogg = M.oggetto(chiave)
    except KeyError:
        print("Oggetto sconosciuto. Chiavi: " + ", ".join(o["chiave"] for o in M.OGGETTI if o.get("fonti")))
        return 1
    ep = M.cerca_epoche(ogg, log=print)
    for e in ep:
        print(f"  {'☑' if e['usa'] else '☐'} {M.testo_anno(e['anno'], 2):>8}  {e['etichetta']:<22} {e.get('nota', '')}")
    r = M.esegui(ogg, ep, log=print, progresso=lambda f, t=None: None)
    print("\n".join(r["testo"]))
    return 0


def main():
    ap = argparse.ArgumentParser(description=f"Prima e dopo {VERSIONE} – {M.FIRMA}")
    ap.add_argument("--autotest", action="store_true")
    ap.add_argument("--diagnostica", action="store_true")
    ap.add_argument("--fai", metavar="OGGETTO")
    a = ap.parse_args()
    if a.autotest:
        sys.exit(autotest())
    if a.diagnostica:
        print(f"Prima e dopo {VERSIONE} – diagnostica della rete ({time.strftime('%Y-%m-%d %H:%M')})")
        sys.exit(0 if M.diagnostica() else 1)
    if a.fai:
        sys.exit(fai(a.fai))
    if getattr(sys, "frozen", False):
        try:
            log = open(Path.home() / ".prima_e_dopo.log", "a", encoding="utf-8", buffering=1)
            log.write(f"\n--- avvio {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            sys.stderr = log
        except OSError:
            pass
    avvia_finestra()


if __name__ == "__main__":
    main()
