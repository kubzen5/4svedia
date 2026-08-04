# 4svedia


My project is called like that because it's all about course.
Solution will be in Python 3.12.

## S02E01

Fetch and classify the current cargo list:

```powershell
$env:AGENTHUB_API_URL = "https://hub.ag3nts.org/"
$env:AGENTHUB_API_KEY = "your_api_key_here"
uv run s02e01.py
```

The script tries four compact classification prompts, always treats
reactor-related cargo as neutral (`NEU`), and resets the task before each
prompt variant. Credentials are loaded from `.env` when present.

## S01E05

Activate railway route `X-01` using the API's self-documented workflow:

```powershell
uv run s01e05.py
```

The script starts with `help`, follows an explicit machine-readable workflow,
retries simulated overload responses, respects rate-limit reset headers, and
stops when it receives a `{FLG:...}` flag. It uses `AGENTHUB_API_URL` and
`AGENTHUB_API_KEY` documented in `.env-example`.

## S01E04

Build and submit the SPK transport declaration for the `sendit` task:

```powershell
uv run s01e04.py
```

The script uses `AGENTHUB_API_URL` and `AGENTHUB_API_KEY` documented in
`.env-example`, prints the exact declaration sent to the Hub, and then prints
the JSON verification response.

## S01E03

Start the session-aware logistics proxy:

```powershell
uv run s01e03.py
```

It listens on `http://127.0.0.1:3000/assistant` by default and accepts:

```json
{"sessionID": "operator-1", "msg": "Sprawdź paczkę PKG12345678"}
```

Health check: `GET /health`. Configure credentials and optional `PROXY_HOST` /
`PROXY_PORT` in `.env` (see `.env-example`). For access from outside the local
machine, expose port 3000 through the tunnel configured by your course setup.

### Publiczny tunel ngrok i weryfikacja (Windows)

1. Załóż bezpłatne konto na `https://dashboard.ngrok.com/signup`, a następnie
   skopiuj authtoken z `https://dashboard.ngrok.com/get-started/your-authtoken`.
2. Zainstaluj ngrok z Microsoft Store lub poleceniem wyświetlonym na
   `https://ngrok.com/download/windows`. Sprawdź instalację przez `ngrok help`.
3. Jednorazowo połącz agenta z kontem:

   ```powershell
   ngrok config add-authtoken "TU_WKLEJ_AUTHTOKEN"
   ```

4. W pierwszym terminalu uruchom proxy:

   ```powershell
   cd F:\PythonProjects\4svedia
   uv run s01e03.py
   ```

5. W drugim terminalu wystaw port 3000:

   ```powershell
   ngrok http 3000
   ```

6. Nie zamykając obu terminali, w trzecim sprawdź i zgłoś endpoint:

   ```powershell
   cd F:\PythonProjects\4svedia
   uv run s01e03_verify.py
   ```

Skrypt automatycznie odczytuje adres HTTPS z API agenta ngrok na porcie 4040,
sprawdza publiczne `/health`, dodaje `/assistant` i wysyła URL jako zadanie
`proxy` do Agent Hub wraz z losowym `sessionID`. Odpowiedź weryfikatora, w tym ewentualna flaga, pojawi się
w terminalu. Opcjonalnie można wpisać pełny URL endpointu do
`PROXY_PUBLIC_URL` w `.env`, aby pominąć automatyczne wykrywanie.

Jeśli przeglądarka pokaże `ERR_NGROK_6024`, jest to jednorazowa strona ochronna
darmowego ngrok. Można kliknąć przycisk przejścia albo testować API z nagłówkiem:

```powershell
Invoke-RestMethod "$publicUrl/health" `
  -Headers @{ "ngrok-skip-browser-warning" = "s01e03" }
```

Skrypt `s01e03_verify.py` dodaje ten nagłówek automatycznie.
