"""No-op — l'app.py ja fa el bootstrap directament.

app.py llegeix .env i insereix `PREPARACIO_PATH` (=P:\\preparacioComandesVendaSAP)
a sys.path abans d'importar `motor`. El motor de preparacioComandesVendaSAP
te el seu propi `_bootstrap` que afegeix el Kais canonic (per resoldre
`models`/`regles`/`mailer`) i aplica els overrides SAP.

Aquest fitxer existeix per si en el futur cal fer bootstrap especific de
la variant SAP de l'app d'agrupacio; de moment es inert.
"""
