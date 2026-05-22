## ADDED Requirements

### Requirement: MCP SSE endpoint
The system SHALL expose a Server-Sent Events stream at `GET /mcp/sse` when `MCP_ENABLED=true`.

#### Scenario: Client opens SSE stream
- **WHEN** a client sends `GET /mcp/sse`
- **THEN** the server responds with `Content-Type: text/event-stream` and immediately emits an `endpoint` event containing the session-specific POST URL `/mcp/messages?session_id=<uuid>`

#### Scenario: Keepalive while idle
- **WHEN** no messages are queued for 15 seconds
- **THEN** the server emits a keepalive comment (`: keepalive`) to prevent TCP timeout

#### Scenario: Session cleanup on disconnect
- **WHEN** the client disconnects or the stream generator exits
- **THEN** the session entry is removed from the active stream registry

### Requirement: MCP JSON-RPC message endpoint
The system SHALL expose a JSON-RPC POST endpoint at `POST /mcp/messages?session_id=<uuid>` when `MCP_ENABLED=true`.

#### Scenario: Valid tool call dispatched
- **WHEN** a POST body `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"<tool>","arguments":{...}}}` is received with a valid `session_id`
- **THEN** the server dispatches to the matching handler, pushes the result to the SSE queue, and returns HTTP 202

#### Scenario: tools/list request
- **WHEN** method is `tools/list`
- **THEN** the server returns the full `TOOL_REGISTRY` in the SSE stream

#### Scenario: Unknown session_id
- **WHEN** the `session_id` query param does not match any active stream
- **THEN** the server SHALL still process the call but the response will not be delivered (no SSE stream to route to)

### Requirement: Feature flag controls router mount
The system SHALL only mount the `/mcp` router when `MCP_ENABLED=true` in settings.

#### Scenario: Flag disabled
- **WHEN** `MCP_ENABLED=false` (default)
- **THEN** all `/mcp/*` paths return HTTP 404

#### Scenario: Flag enabled
- **WHEN** `MCP_ENABLED=true`
- **THEN** `/mcp/sse` and `/mcp/messages` are reachable
