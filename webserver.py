import asyncio
import json
import os
import logging

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from logging_setting import ColorHandler


logger = logging.getLogger("webapp")
logger.setLevel(logging.INFO)
logger.addHandler(ColorHandler())


class WebServer:
    @staticmethod
    async def index(_):
        content = open(os.path.join(os.path.dirname(__file__), "index.html"), "r").read()
        return web.Response(content_type="text/html", text=content)

    @staticmethod
    async def javascript(_):
        content = open(os.path.join(os.path.dirname(__file__), "client.js"), "r").read()
        return web.Response(content_type="application/javascript", text=content)

    def __init__(self, get_video_fun, ssl_context=None):
        self.ssl_context = ssl_context
        self.pcs = set()
        self.get_video_fun = get_video_fun

    async def offer(self, request):
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

        pc = RTCPeerConnection()
        self.pcs.add(pc)

        logger.info(f"Created for {request.remote}")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"Connection state: {pc.connectionState}")
            if pc.connectionState == "failed":
                await pc.close()
                self.pcs.discard(pc)

        # handle offer
        await pc.setRemoteDescription(offer)
        pc.addTrack(await self.get_video_fun())
        # send answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
            )
        )

    async def on_shutdown(self, _):
        # close peer connections
        task = [pc.close() for pc in self.pcs]
        await asyncio.gather(*task)
        self.pcs.clear()

    async def start_webserver(self):
        app = web.Application()
        app.on_shutdown.append(self.on_shutdown)
        app.router.add_get("/", WebServer.index)
        app.router.add_get("/client.js", WebServer.javascript)
        app.router.add_post("/offer", self.offer)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=8080, ssl_context=self.ssl_context)
        await site.start()
