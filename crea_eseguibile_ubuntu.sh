#!/usr/bin/env bash
# =============================================================================
# Prima e dopo 1.10 – crea l'eseguibile per Ubuntu e lo installa (menu + Scrivania)
# © 2026 Edoardo Battistel
#
# Uso:  cd ~/Claude/Astropy/programma_prima_e_dopo/versione_1.10
#       bash crea_eseguibile_ubuntu.sh
# Usa il venv ~/Claude/Astropy/venv_compila (PyInstaller), che vede numpy, scipy,
# astropy, matplotlib e Pillow di sistema.
# =============================================================================
set -e
cd "$(dirname "$(readlink -f "$0")")"
PY="$HOME/Claude/Astropy/venv_compila/bin/python"

for f in prima_e_dopo.py motore_pd.py prova_sintetica.py prima_e_dopo.png; do
    [ -f "$f" ] || { echo "ERRORE: manca $f in questa cartella ($(pwd))."; exit 1; }
done
[ -x "$PY" ] || { echo "ERRORE: non trovo $PY"; exit 1; }

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "NOTA: ffmpeg non è installato: senza, il programma crea GIF e pagina ma non l'MP4."
    echo "      Per installarlo:  sudo apt install ffmpeg"
fi

echo "=== 1/4  Controllo dei pacchetti (autotest dallo script) ==="
if ! "$PY" prima_e_dopo.py --autotest; then
    echo "L'autotest dello script è FALLITO: mandami il testo qui sopra."
    exit 1
fi

# metadati da copiare solo se il pacchetto c'è (con nomi diversi tra pip e Ubuntu)
META=""
for m in astropy numpy scipy pyerfa astropy-iers-data packaging pyyaml matplotlib pillow; do
    if "$PY" -c "import importlib.metadata as im, sys; im.version(sys.argv[1])" "$m" 2>/dev/null; then
        META="$META --copy-metadata $m"
    fi
done
EXTRA=""
"$PY" -c "import erfa" 2>/dev/null && EXTRA="$EXTRA --collect-all erfa"
"$PY" -c "import astropy_iers_data" 2>/dev/null && EXTRA="$EXTRA --collect-data astropy_iers_data"

echo "=== 2/4  Creazione dell'eseguibile (qualche minuto) ==="
"$PY" -m PyInstaller --noconfirm --clean --onefile --windowed \
    --name PrimaEDopo \
    --add-data "prima_e_dopo.png:." \
    --collect-all astropy $EXTRA $META \
    --hidden-import motore_pd \
    --hidden-import prova_sintetica \
    --hidden-import PIL._tkinter_finder \
    --hidden-import PIL.ImageTk \
    --hidden-import matplotlib.backends.backend_agg \
    --hidden-import scipy.signal \
    --hidden-import scipy.optimize \
    --hidden-import scipy.spatial \
    --exclude-module sklearn --exclude-module IPython --exclude-module pandas \
    prima_e_dopo.py

echo "=== 3/4  Verifica dell'eseguibile (autotest) ==="
if ! ./dist/PrimaEDopo --autotest > autotest.txt 2>&1; then
    cat autotest.txt
    echo
    echo "L'autotest dell'eseguibile è FALLITO: i dettagli sono in $(pwd)/autotest.txt"
    echo "L'eseguibile non è stato installato. Mandami autotest.txt per la correzione."
    rm -rf build PrimaEDopo.spec
    exit 1
fi
cat autotest.txt

echo "=== Prova degli archivi in rete (diagnostica, circa un minuto) ==="
./dist/PrimaEDopo --diagnostica > diagnostica.txt 2>&1 || true
grep -E "^\[(ok|ERRORE|--)\]" diagnostica.txt | cut -c1-200 || true
echo "(dettagli in $(pwd)/diagnostica.txt)"

echo "=== 4/4  Installazione nella home e icona nel menu ==="
DEST="$HOME/.local/bin"
ICONE="$HOME/.local/share/icons/hicolor/512x512/apps"
mkdir -p "$DEST" "$HOME/.local/share/applications" "$ICONE"
cp prima_e_dopo.png "$ICONE/prima-e-dopo.png"
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
cp dist/PrimaEDopo "$DEST/PrimaEDopo"
chmod +x "$DEST/PrimaEDopo"

# Tk dichiara la classe della finestra "Primaedopo" (solo la prima maiuscola): StartupWMClass
# va scritto così e il file .desktop ha lo stesso nome in minuscolo.
SCRIVANIA="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Scrivania")"
cat > "$HOME/.local/share/applications/primaedopo.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Prima e dopo
Comment=Lo stesso oggetto del cielo a anni di distanza: animazioni e misura del movimento
Exec=$DEST/PrimaEDopo
Icon=$ICONE/prima-e-dopo.png
StartupWMClass=Primaedopo
Terminal=false
Categories=Science;Astronomy;Education;
EOF
chmod +x "$HOME/.local/share/applications/primaedopo.desktop"
update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true
if [ -d "$SCRIVANIA" ]; then
    cp "$HOME/.local/share/applications/primaedopo.desktop" "$SCRIVANIA/"
    chmod +x "$SCRIVANIA/primaedopo.desktop"
    gio set "$SCRIVANIA/primaedopo.desktop" metadata::trusted true 2>/dev/null || true
fi

rm -rf build PrimaEDopo.spec
echo
echo "FATTO."
echo "  Eseguibile:  $DEST/PrimaEDopo   (copia anche in $(pwd)/dist/)"
echo "  Avvio:       'Prima e dopo' nel menu delle applicazioni o doppio clic sull'icona sulla Scrivania"
echo "               (la prima volta: tasto destro -> 'Consenti avvio')."
echo "  Il titolo della finestra deve dire 'Prima e dopo $(grep -m1 '^VERSIONE' motore_pd.py | cut -d'"' -f2)'."
echo "  Controllo dell'icona nella barra: xwininfo -root -tree | grep -i primaedopo"
