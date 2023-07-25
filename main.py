import asyncio
import hashlib
import json
import sys
import traceback
from uuid import uuid4

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from application.api.commands import get_pixel_data, ping
from application.api.config import ServerConfig
from application.api.connection_manager import ConnectionManager
from application.canvas.canvas import Canvas
from application.target_configuration.target_configuration import TargetConfiguration

app = FastAPI()

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

connection_manager = ConnectionManager()

config = ServerConfig()
canvas: Canvas
target_config: TargetConfiguration


async def update_canvas(monalisa: Canvas):
    while True:
        try:
            await monalisa.update_board()
            await asyncio.sleep(10)
        except:
            print('There was an error updating the canvas.')
            traceback.print_exception(*sys.exc_info())


@app.on_event('startup')
async def startup():
    global canvas, target_config
    target_config = TargetConfiguration(config)
    canvas = Canvas(target_config)
    print('Scheduling canvas update')
    asyncio.create_task(update_canvas(canvas))


@app.websocket('/')
async def live_endpoint(websocket: WebSocket):
    uuid = str(uuid4())
    await connection_manager.connect(uuid, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            print("Received Request: "+str(data), flush=True)
            if op := data.get("operation"):
                response = None

                if op == 'request-pixel':
                    pixel = await canvas.pop_mismatched_pixel()
                    if pixel:
                        response = { "operation":"place-pixel", "data":await get_pixel_data(pixel) }
                    else:
                        response = {}

                elif op == 'handshake':
                    metadata = data.get('data', {})

                    client_version = metadata.get('version', 0)
                    client_platform = metadata.get('platform', '')
                    versions = (await target_config.get_config()).get("versions")
                    target_version = versions.get(client_platform, -1)
                    advertised_count = max(0, metadata.get('useraccounts', 1))

                    response = { "operation":"notify-update", "version":str(target_version) }
                    connection_manager.set_advertised_accounts(uuid, advertised_count)

                elif op == 'ping':
                    response = ping()

                print("Response: "+str(response), flush=True)
                if response is not None:
                    await websocket.send_json(response)
    except:
        pass
    finally:
        connection_manager.disconnect(uuid, websocket)


@app.get('/users/count')
async def get_users_count():
    return JSONResponse(content={
        'connections': connection_manager.connection_count(),
        'advertised_accounts': connection_manager.advertised_account_count()
    })


@app.get('/pixel/amount')
async def get_pixels_count():
    return JSONResponse(content={
        'mismatched': await canvas.get_wrong_pixel_amount(),
        'all': len(await canvas.target_configuration.get_pixels(True))
    })


@app.get('/pixel/get_images')
async def get_users_count():
    return JSONResponse(content=await canvas.get_images_as_json())


@app.get('/test')
async def get_users_count():
    return JSONResponse(content=
        canvas.mismatched_pixels
    )


def password_check(password):
    return hashlib.sha3_512(
        password.encode()).hexdigest() == config.admin_password
