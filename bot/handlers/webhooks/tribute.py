from aiohttp import web
from bot.services.tribute_service import TributeService


async def tribute_webhook_route(request: web.Request):
    tribute_service: TributeService = request.app['tribute_service']
    raw_body = await request.read()
    signature_header = request.headers.get('trbt-signature')
    return await tribute_service.handle_webhook(raw_body, signature_header)
