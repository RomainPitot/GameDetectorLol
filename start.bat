@echo off
cd /d "%~dp0"
if not exist venv (
    echo Creation de l'environnement virtuel...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo Installation des dependances...
    pip install -q -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)
echo Demarrage de GameDetectorLol...
python notifier.py
echo.
echo Le script s'est arrete (ferme volontairement, erreur, ou deja lance ailleurs — voir ci-dessus).
echo Cette fenetre reste ouverte pour que tu puisses lire pourquoi ; ferme-la quand tu as fini.
