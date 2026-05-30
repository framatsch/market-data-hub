# MCP Integration Proposal — FastAPI + MCP über einen Dienst

## Zielbild

MCP (Model Context Protocol) läuft **nicht als separater Prozess**, sondern als
zusätzlicher Router innerhalb der bestehenden FastAPI-App. Alles teilt sich
denselben Uvicorn-Prozess, dieselbe DB-Session, dieselben Services. Der einzige
Unterschied: MCP-Endpunkte liegen unter dem Pfad `/mcp/*`.

```
http://localhost:8000/
├── /health              ← bestehendes FastAPI-Health-Endpoint
├── /api/v1/...          ← bestehendes REST-API
└── /mcp/                ← MCP-Transport (neu, Feature-Flag-geschützt)
    ├── /mcp/sse         ← Server-Sent Events Stream (MCP Notifications)
    └── /mcp/messages    ← JSON-RPC POST (MCP Tool Calls)
```

---

## Warum ein Dienst?

| Aspekt | Separater MCP-Prozess | Integrierter Router |
|--------|----------------------|---------------------|
| DB-Sessions | eigene Connection-Pool | geteilt, kein Overhead |
| Services/Repos | Code-Duplikation | direkt importiert |
| Deployments | 2 Container | 1 Container |
| Konfiguration | doppelte Env-Vars | ein `settings`-Objekt |
| Logs/Traces | aufgeteilt | unified |

---

## Umsetzung

### 1. Feature-Flag in Settings

```python
# app/core/config.py
class Settings(BaseSettings):
    MCP_ENABLED: bool = False
```

### 2. Router einbinden (main.py)

```python
# app/main.py  — nur der relevante Teil, kein Auth-Code
from app.api.mcp import router as mcp_router
from app.api.v1.router import router as v1_router

def create_app() -> FastAPI:
    app = FastAPI(...)
    app.include_router(v1_router)          # /api/v1/...

    if settings.MCP_ENABLED:
        app.include_router(mcp_router)     # /mcp/...

    return app
```

### 3. MCP Router — Struktur

```python
# app/api/mcp.py
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import asyncio, json

router = APIRouter(prefix="/mcp", tags=["mcp"])

# Global session → queue mapping für SSE-Routing
_ACTIVE_STREAMS: dict[str, asyncio.Queue[str]] = {}
```

### 4. SSE-Transport  `/mcp/sse`

```python
@router.get("/sse")
async def mcp_sse(request: Request) -> StreamingResponse:
    """
    Öffnet einen persistenten SSE-Stream für den MCP-Client.
    Der Server sendet:
      - sofort das 'endpoint'-Event mit der POST-URL
      - danach Keepalives alle 15 s
      - Tool-Results werden via _ACTIVE_STREAMS[session_id] geroutet
    """
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue[str] = asyncio.Queue()
    _ACTIVE_STREAMS[session_id] = queue

    async def event_stream() -> AsyncGenerator[str, None]:
        # Schritt 1: Client erhält seine POST-URL
        yield f"event: endpoint\ndata: /mcp/messages?session_id={session_id}\n\n"

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"   # hält TCP-Verbindung offen
        finally:
            _ACTIVE_STREAMS.pop(session_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

### 5. JSON-RPC POST  `/mcp/messages`

```python
@router.post("/messages")
async def mcp_messages(
    request: Request,
    session_id: str = Query(...),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """
    Empfängt einen MCP JSON-RPC Call, verarbeitet ihn synchron
    und schickt das Ergebnis in die SSE-Queue des Clients.
    """
    payload = await request.json()
    method  = payload.get("method")
    rpc_id  = payload.get("id")
    params  = payload.get("params", {})

    # Tool-Dispatch
    result = await _dispatch(method, params, db)

    # Antwort in SSE-Stream schieben
    queue = _ACTIVE_STREAMS.get(session_id)
    if queue:
        msg = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result})
        await queue.put(f"event: message\ndata: {msg}\n\n")

    return Response(status_code=202)


async def _dispatch(
    method: str,
    params: dict,
    db: AsyncSession,
) -> dict:
    """Mappt MCP-Tool-Namen auf interne Service-Calls."""
    if method == "tools/list":
        return {"tools": TOOL_REGISTRY}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            raise ValueError(f"Unknown tool: {name}")
        return await handler(args, db)

    raise ValueError(f"Unknown method: {method}")
```

### 6. Tool-Registrierung — Beispiel

```python
# Jedes Tool ist eine async-Funktion: (args, db) -> dict
TOOL_REGISTRY = [
    {
        "name": "search_trades",
        "description": "Search trades by symbol, date range, P&L",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol":    {"type": "string"},
                "date_from": {"type": "string", "format": "date"},
                "date_to":   {"type": "string", "format": "date"},
            },
        },
    },
]

async def _tool_search_trades(args: dict, db: AsyncSession) -> dict:
    # Direkt auf TradeRepository — kein HTTP-Roundtrip
    from app.repositories.trade_repository import TradeRepository
    repo   = TradeRepository(db)
    trades = await repo.search(**args)
    return {"content": [{"type": "text", "text": json.dumps([t.model_dump() for t in trades])}]}

TOOL_HANDLERS: dict[str, Any] = {
    "search_trades": _tool_search_trades,
}
```

---

## Datenfluss (Sequenzdiagramm)

```
Agent / MCP Client          FastAPI (Uvicorn)              DB
       │                          │                          │
       │── GET /mcp/sse ─────────>│                          │
       │<─ event: endpoint ───────│  (session_id vergeben)   │
       │                          │                          │
       │── POST /mcp/messages ───>│                          │
       │   {method: tools/call}   │── TradeRepository ──────>│
       │                          │<─ Ergebnis ──────────────│
       │<─ event: message ────────│  (via SSE-Queue)          │
       │   {result: ...}          │                          │
```

---

## Deployment-Änderungen

Keine. Dasselbe Docker-Image, derselbe Port. Nur `MCP_ENABLED=true` setzen.

```yaml
# docker-compose.yml  — kein neuer Service nötig
services:
  backend:
    environment:
      MCP_ENABLED: "true"
```

---

## Was noch fehlt (außerhalb dieses Proposals)

- Authentifizierung (PAT-basiert, bereits implementiert via `get_current_user_from_pat`)
- Tool-Erweiterungen (Playbooks, Annotationen, Metriken)
- Rate-Limiting für `/mcp/*`
- SSE-Reconnect-Handling (Last-Event-ID)
