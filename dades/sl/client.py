"""Capa de lectura sobre el client del Service Layer de l'app germana.

Reutilitzem `SLClient` de `preparacioComandesVendaSAP` (arriba per
`PREPARACIO_PATH`, el mateix `sys.path` que ja porta `motor.py`) en lloc de
copiar-lo: el seu codi de sessio es la part dificil i ja va costar un incident
de produccio (login per peticio -> 502 amb 8 peticions concurrents). Copiar-lo
crearia dues copies divergents d'exactament aquell codi.

Aqui nomes hi afegim el que li falta, que es tota la part de LECTURA: el
client germa no te cap metode public de consulta, `_request` no accepta
parametres i retorna el `Response` cru.

Dues decisions d'implementacio que val la pena entendre:

1. El query string el montem nosaltres i el passem dins del `path`. `_request`
   fa `f"{self.url}/{path.lstrip('/')}"`, aixi que hi cap sencer, i aixi
   heretem de franc el reintent de 401 amb relogin, el de 5xx amb backoff i
   el lock del client.

2. La capcalera `Prefer: odata.maxpagesize` no es pot passar per `_request`
   (nomes posa `Prefer` als metodes que muten), aixi que l'estampem a la
   sessio en fer login. Sense ella el Service Layer retorna 20 files i, si no
   es mira `odata.nextLink`, el codi les dona per bones EN SILENCI. Es l'error
   mes facil de cometre aqui i el mes dificil de detectar.
"""
from __future__ import annotations

import logging
import os
import threading
from urllib.parse import quote, urlencode

import requests

from sap_service_layer import SLClient, SLError  # ve de PREPARACIO_PATH

log = logging.getLogger("agrupacio")

# Caracters que han de quedar literals al query string. Sobretot el dolar dels
# operadors OData i la cometa simple dels literals de text. `quote` codifica
# l'espai com a %20 (no com a +, que el Service Layer no sempre accepta dins
# de $filter) i aquesta diferencia no dona error: dona un resultat DIFERENT.
_SEGURS = "$,()'/= :"


class SLLectura(SLClient):
    """`SLClient` amb consultes OData de lectura."""

    def __init__(self, *args, page_size: int = 1000, max_files: int = 20000, **kwargs):
        super().__init__(*args, **kwargs)
        self.page_size = page_size
        self.max_files = max_files

    def login(self) -> None:
        super().login()
        if self._session is not None:
            self._session.headers["Prefer"] = f"odata.maxpagesize={self.page_size}"

    # --- Nivell baix ----------------------------------------------------
    def _get(self, path: str) -> dict:
        """GET que retorna el JSON ja parsejat i embolcalla els errors de xarxa.

        El client germa no embolcalla `requests.RequestException` fora del
        login: un ReadTimeout sortiria cru i l'endpoint el convertiria en 500
        en lloc de 503. Amb una app de llistats, que fa moltes mes lectures
        que escriptures, aixo passaria sovint.
        """
        try:
            resp = self._request("GET", path)
        except requests.RequestException as e:
            raise SLError(f"Fallada de xarxa al Service Layer: {e}") from e
        try:
            return resp.json()
        except ValueError as e:
            raise SLError(
                f"El Service Layer ha respost una cosa que no es JSON ({path[:120]})",
                status_code=resp.status_code,
            ) from e

    @staticmethod
    def _qs(select=None, filtre=None, ordre=None, top=None, skip=None,
            compta=False, aplica=None) -> str:
        params: list[tuple[str, str]] = []
        if aplica:
            params.append(("$apply", aplica))
        if select:
            params.append(("$select", select if isinstance(select, str) else ",".join(select)))
        if filtre:
            params.append(("$filter", filtre))
        if ordre:
            params.append(("$orderby", ordre))
        if top is not None:
            params.append(("$top", str(int(top))))
        if skip:
            params.append(("$skip", str(int(skip))))
        if compta:
            # OData v3: $inlinecount, no $count
            params.append(("$inlinecount", "allpages"))
        return urlencode(params, quote_via=quote, safe=_SEGURS)

    # --- Nivell util ----------------------------------------------------
    def pagina(self, entitat: str, **kw) -> tuple[list[dict], int | None]:
        """Una sola pagina. Retorna (files, total); total nomes si compta=True."""
        qs = self._qs(**kw)
        j = self._get(f"{entitat}?{qs}" if qs else entitat)
        total = j.get("odata.count")
        return j.get("value") or [], (int(total) if total is not None else None)

    def tot(self, entitat: str, **kw) -> list[dict]:
        """Totes les files, seguint `odata.nextLink` fins al final.

        Si se supera `max_files` llanca excepcio en lloc de truncar: un volcat
        incomplet que sembla complet es pitjor que un error.
        """
        qs = self._qs(**kw)
        path = f"{entitat}?{qs}" if qs else entitat
        files: list[dict] = []
        pagines = 0
        while path:
            j = self._get(path)
            files.extend(j.get("value") or [])
            pagines += 1
            if len(files) > self.max_files:
                raise SLError(
                    f"La consulta a {entitat} supera el maxim de {self.max_files} files "
                    f"({len(files)} en {pagines} pagines). Redueix el rang."
                )
            path = j.get("odata.nextLink")
        return files

    def agrega(self, entitat: str, aplica: str) -> list[dict]:
        """`$apply` amb `groupby`/`aggregate`.

        Es pagina igual que qualsevol col·leccio: un `groupby` per
        transportista pot tornar centenars de grups i nomes en veuries 20.
        """
        return self.tot(entitat, aplica=aplica)

    def compta(self, entitat: str, filtre: str | None = None) -> int:
        _, total = self.pagina(entitat, select="DocEntry", top=1, filtre=filtre, compta=True)
        return int(total or 0)

    def viu(self) -> bool:
        """Sonda barata per a /health (~7 ms). Escalfa tambe la sessio: amb el
        monitoring passant cada 30 s, no es troba mai freda i s'estalvia el
        login de ~2 s a la primera peticio d'usuari."""
        self.pagina("SEI_ORDENCARGA", select="DocEntry", top=1)
        return True


# --- Singleton per proces ----------------------------------------------
# La sessio del Service Layer es un recurs del PROCES, no de la peticio. Un
# `with SLClient(...)` per peticio fa login cada vegada (~2 s) i satura el SL:
# es exactament l'incident del 29-09 a l'app germana.
_client: SLLectura | None = None
_client_lock = threading.Lock()


def _bool_env(nom: str, per_defecte: bool) -> bool:
    v = os.environ.get(nom)
    if v is None:
        return per_defecte
    return v.strip().lower() not in ("false", "0", "no")


def client() -> SLLectura:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                url = os.environ.get("SAP_SL_URL")
                if not url:
                    raise SLError("SAP_SL_URL no esta configurat")
                _client = SLLectura(
                    url,
                    os.environ["SAP_SL_COMPANY"],
                    os.environ["SAP_SL_USER"],
                    os.environ["SAP_SL_PASSWORD"],
                    verify=_bool_env("SAP_SL_VERIFY_SSL", True),
                    timeout=int(os.environ.get("SAP_SL_TIMEOUT", "15")),
                    page_size=int(os.environ.get("SAP_SL_PAGE_SIZE", "1000")),
                    max_files=int(os.environ.get("SAP_SL_MAX_FILES", "20000")),
                )
                # No fem login aqui: si SAP esta caigut, el worker ha de poder
                # arrencar i servir el backend SQL igualment.
    return _client
