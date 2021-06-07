import aiohttp_jinja2
import asyncio
import base64
import jinja2
import json
import os
import logging

from aiohttp import web
from aiohttp_session import setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from aiohttp_security import setup as setup_security, check_permission, check_authorized, remember, forget, \
    authorized_userid
from aiohttp_security import SessionIdentityPolicy
from aiortc import RTCPeerConnection, RTCSessionDescription
from cryptography import fernet

from general_classes.logging_setting import ColorHandler
from web_server.authz import DictionaryAuthorizationPolicy, check_credentials
from web_server.users import user_map

# настройка логов
logger = logging.getLogger("webapp")
logger.setLevel(logging.INFO)
logger.addHandler(ColorHandler())


# класс для создания web-сервера
class WebServer:
    @staticmethod
    @aiohttp_jinja2.template("index.html")
    async def _index(request):
        directory = os.path.join(os.path.dirname(__file__), "../video")

        def get_size(file):
            size = os.path.getsize(os.path.join(directory, file))
            return f"{size / (2 ** 20):.2f} Мб"

        username = await authorized_userid(request)
        if not username:
            raise web.HTTPFound('/login.html')
        else:
            username = f"User: {username}"

        files = [{
            "filename": f,
            "url": f"/download/{f}",
            "size": get_size(f)
        } for f in os.listdir(directory)]
        return {"videos": files, "user": username}

    @staticmethod
    async def _logo(_):
        logo_path = os.path.join(os.path.dirname(__file__), "logo.svg")
        return web.FileResponse(logo_path)

    @staticmethod
    async def _javascript(_):
        content = open(os.path.join(os.path.dirname(__file__), "client.js"), "r").read()
        return web.Response(content_type="application/javascript", text=content)

    # обработка get запросов вида /download/name
    # name - имя файла из папки video для загрузки
    @staticmethod
    async def _download_file(request):
        await check_permission(request, 'download')
        filename = request.match_info['name']
        fullname = os.path.join(os.path.dirname(__file__), "../video", filename)
        if os.path.exists(fullname):
            return web.FileResponse(fullname)
        else:
            return web.Response(status=404)

    @staticmethod
    async def _login_form(_):
        content = open(os.path.join(os.path.dirname(__file__), "login.html"), "r").read()
        return web.Response(content_type="text/html", text=content)

    @staticmethod
    async def _login(request):
        response = web.HTTPFound('/')
        # получить значения полей формы
        form = await request.post()
        username = form.get('username')
        password = form.get('password')
        # проверка правильности данных
        verified = await check_credentials(
            request.app.user_map, username, password)
        # сохранение данных в сессии
        if verified:
            await remember(request, response, username)
            return response
        # если данные не верны, то возврат ошибки
        return web.HTTPUnauthorized(body='Неверный логин/пароль')

    @staticmethod
    async def _logout(request):
        await check_authorized(request)
        response = web.HTTPFound('/')
        await forget(request, response)
        return response

    def __init__(self, get_video_fun, ssl_context=None):
        self._ssl_context = ssl_context
        self._pcs = set()
        self._get_video_fun = get_video_fun
        self._server = None

    # обработка запроса offer и отправка answer
    async def _offer(self, request):
        await check_permission(request, 'realtime_video')
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

        pc = RTCPeerConnection()
        self._pcs.add(pc)

        logger.info(f"Created for {request.remote}")
        track = await self._get_video_fun()

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"Connection state: {pc.connectionState}")
            # закрытие подлючения
            if pc.connectionState == "failed":
                await pc.close()
                track.stop()
                self._pcs.discard(pc)

        await pc.setRemoteDescription(offer)
        if track:
            pc.addTrack(track)
        # отправить answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
            )
        )

    async def _on_shutdown(self, _):
        # закрыть все подключения
        task = [pc.close() for pc in self._pcs]
        await asyncio.gather(*task)
        self._pcs.clear()

    async def start_webserver(self):
        app = web.Application()
        app.on_shutdown.append(self._on_shutdown)
        # настройка авторизации
        app.user_map = user_map
        fernet_key = fernet.Fernet.generate_key()
        secret_key = base64.urlsafe_b64decode(fernet_key)

        storage = EncryptedCookieStorage(secret_key, cookie_name='API_SESSION')
        setup_session(app, storage)

        policy = SessionIdentityPolicy()
        setup_security(app, policy, DictionaryAuthorizationPolicy(user_map))

        # настройка маршрутов
        app.router.add_get("/", WebServer._index)
        app.router.add_get("/logo.svg", WebServer._logo)
        app.router.add_get("/client.js", WebServer._javascript)
        app.router.add_get("/login.html", WebServer._login_form)
        app.router.add_post("/login", WebServer._login)
        app.router.add_get("/logout", WebServer._logout)
        app.router.add_post("/offer", self._offer)
        app.router.add_get("/download/{name}", WebServer._download_file)
        aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))
        # запуск веб-сервера
        runner = web.AppRunner(app)
        await runner.setup()
        self._server = web.TCPSite(runner, host="0.0.0.0", port=8080, ssl_context=self._ssl_context)
        await self._server.start()

    async def stop_webserver(self):
        if self._server:
            await self._server.stop()
