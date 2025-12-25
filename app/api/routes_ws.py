import asyncio
import json
import logging
from typing import List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

class SubscriptionMessage(BaseModel):
    type: str # "subscribe"
    symbols: List[str]
    provider: str = "ibkr"

@router.websocket("/prices")
async def websocket_prices(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            try:
                # Basic parsing
                message_dict = json.loads(data)
                
                # In a real app, we'd handle subscription state here
                if message_dict.get("type") == "subscribe":
                    symbols = message_dict.get("symbols", [])
                    provider = message_dict.get("provider", "ibkr")
                    
                    logger.info(f"Subscribing to {symbols} from {provider}")
                    
                    # Echo simulated stream for 10 updates
                    for i in range(10):
                        response = {
                            "type": "trade",
                            "symbol": symbols[0] if symbols else "UNKNOWN",
                            "price": 150.0 + i,
                            "provider": provider,
                            "ts": str(asyncio.get_event_loop().time())
                        }
                        await websocket.send_json(response)
                        await asyncio.sleep(1)
                        
            except json.JSONDecodeError:
                await websocket.send_text("Invalid JSON")
                
    except WebSocketDisconnect:
        logger.info("Client disconnected")
