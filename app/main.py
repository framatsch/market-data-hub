from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.utils.errors import AppError, ErrorResponse, ErrorDetail
from app.utils.logging import logger
from app.api import routes_meta, routes_prices, routes_companies, routes_options, routes_ws

app = FastAPI(
    title=settings.APP_NAME,
    description="Market and Company Data Aggregation Service",
    version="0.1.0",
)

# Exception Handlers
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    status_code = 500
    if exc.code == "DATA_NOT_FOUND":
        status_code = 404
    elif exc.code == "INVALID_PROVIDER":
        status_code = 400
    elif exc.code in ("PROVIDER_NOT_AVAILABLE", "PROVIDER_TIMEOUT"):
        status_code = 503
        
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=exc.code, 
                message=exc.message, 
                details=exc.details
            )
        ).model_dump()
    )

# Routers
app.include_router(routes_meta.router)
app.include_router(routes_prices.router)
app.include_router(routes_companies.router)
app.include_router(routes_options.router)
app.include_router(routes_ws.router)

@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
