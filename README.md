<p align="center"><img src="assets/icon-256.png" width="128" alt="Logo Android Debloat : un téléphone dont une application est retirée"></p>

# Android Debloat

Retire (ou restaure) les applications préinstallées d'un téléphone Android, depuis un ordinateur Linux ou Windows, via `adb`. Sans root, sans rien installer sur le téléphone, réversible.

> **À lire avant d'utiliser.** Cet outil est fourni tel quel, sans garantie (licence MIT). Retirer le mauvais paquet peut empêcher le téléphone de démarrer correctement ; une réinitialisation d'usine règle alors le problème **mais efface les données**. Fais une sauvegarde avant, et commence par la **simulation**.

## Ce que fait l'outil
- Liste les paquets du téléphone et te laisse cocher ceux à retirer.
- Retire « pour l'utilisateur 0 » (`pm uninstall --user 0`) : l'application disparaît et ne tourne plus, mais l'APK reste sur la partition système. Tu gagnes de la **RAM**, de la batterie et de la confidentialité, **peu d'espace de stockage**.
- Restaure en un clic (`install-existing`) ou par réinitialisation d'usine.
- **Protège** les paquets critiques : tout `com.android.*`, Play Services, modem, Knox, et, pour **ton** téléphone, le lanceur, le composeur, l'appli SMS, le clavier et l'assistant actuellement utilisés. Ces paquets sont refusés (cadenas 🔒).
- Écrit un journal de chaque suppression dans `~/.android-debloat/`.
- Ne se connecte à aucun serveur, n'envoie aucune donnée.

## Prérequis
- Python 3.9+ avec tkinter (Windows : inclus ; Linux : `sudo apt install python3-tk`).
- `adb` (platform-tools de Google) dans le PATH, ou un dossier `platform-tools/` à côté du programme.
- Sur le téléphone : activer les options de développement (7 touches sur « Numéro de build »), puis **Débogage USB**, et accepter la clé RSA.
- Windows : le pilote USB du constructeur.
- **Pas besoin de déverrouiller le bootloader.**

## Utilisation
Interface graphique :

    python3 debloat.py

Ligne de commande (simulation par défaut ; `--apply` pour exécuter) :

    python3 debloat.py presets
    python3 debloat.py list --removed
    python3 debloat.py remove --preset "Bixby"
    python3 debloat.py remove --preset "Bixby" --apply
    python3 debloat.py restore com.facebook.system --apply

## Préréglages
Ils sont dans `presets.json` : une liste de paquets, les marques concernées (`brands`) et l'appareil sur lequel elle a été **testée** (`tested`). Un préréglage n'est proposé que pour sa marque. **Un préréglage n'est une garantie que pour l'appareil indiqué.** Sur un autre modèle, vérifie chaque paquet.

Pour contribuer : ajoute une entrée avec `tested` honnête (modèle et version d'Android), et uniquement des paquets que tu as réellement retirés sans problème.

## Limites connues
- Les paquets protégés sont volontairement nombreux. C'est prudent, pas parfait.
- La liste « Retirées » montre tout ce qui n'est pas installé pour l'utilisateur 0, y compris des paquets déjà absents avant l'outil (paquets de langue, par exemple).
- Testé uniquement sur un Samsung Galaxy S20 FE 5G (SM-G781U1, Android 13) sous Linux. Windows et les autres marques : non testés.
- Les mises à jour du système peuvent réinstaller certains paquets.

## Créer un exécutable
    pip install pyinstaller
    pyinstaller --onefile --windowed --icon assets/icon.ico --add-data "presets.json:." --add-data "assets:assets" debloat.py     # Linux
    pyinstaller --onefile --windowed --icon assets/icon.ico --add-data "presets.json;." --add-data "assets;assets" debloat.py     # Windows

Le logo est dans `assets/` (`icon.svg` est la source, les PNG et l'`.ico` en sont tirés).
(à lancer sur chaque système ; non testé)
