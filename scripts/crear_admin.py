"""CLI per crear el primer usuari administrador.

Ús:
    python scripts/crear_admin.py
    python scripts/crear_admin.py --username admin --nom "Administrador"

Si no es passen arguments, el script demana els valors interactivament.
La contrasenya sempre es demana per stdin (no per CLI argument, per no
quedar visible al historial).
"""
import argparse
import getpass
import os
import sys

# Permet executar des de l'arrel del repo
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Carrega el .env igual que ho fa app.py
_env = os.path.join(_ROOT, ".env")
if os.path.exists(_env):
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

import auth


def main():
    p = argparse.ArgumentParser(description="Crea un usuari (per defecte rol=admin).")
    p.add_argument("--username", help="Email de l'usuari (p.ex. nom@agrienergia.com).")
    p.add_argument("--nom", help="Nom complet de l'usuari.")
    p.add_argument("--rol", default="admin", choices=list(auth.ROLS))
    args = p.parse_args()

    username = args.username or input("Email: ").strip().lower()
    nom = args.nom or input("Nom complet: ").strip()
    rol = args.rol

    # Contrasenya: demanada per getpass, mai per CLI
    pw1 = getpass.getpass("Contrasenya: ")
    pw2 = getpass.getpass("Repeteix-la: ")
    if pw1 != pw2:
        print("ERROR: les contrasenyes no coincideixen.", file=sys.stderr)
        sys.exit(1)
    if len(pw1) < 8:
        print("ERROR: la contrasenya ha de tenir com a mínim 8 caràcters.", file=sys.stderr)
        sys.exit(1)

    try:
        user = auth.crear_usuari(username, pw1, nom, rol)
    except Exception as e:
        print(f"ERROR creant l'usuari: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"OK — usuari creat: id={user['id']} username={user['username']} rol={user['rol']}")


if __name__ == "__main__":
    main()
