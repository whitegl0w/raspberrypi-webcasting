import asyncio
import json
import platform
import socket

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaPlayer, MediaRelay
from argparse import ArgumentParser


async def get_tracks():
    video_options = {"video_size": "640x480", "framerate": "30"}

    if platform.system() == "Windows":
        video_track = MediaPlayer(
                        "video=HP TrueVision HD Camera",
                        format="dshow",
                        options=video_options
                    ).video
    else:
        video_track = MediaPlayer("/dev/video0", format="v4l2", options=video_options).video

    return video_track


async def open_socket(args):
    conn = socket.socket()
    conn.connect((args.host, args.port))
    conn.setblocking(False)

    await create_rtc_connection(conn)
    conn.close()


async def create_rtc_connection(conn):
    relay = MediaRelay()
    config = RTCConfiguration([RTCIceServer('stun:stun.l.google.com:19302')])
    pc = RTCPeerConnection(config)
    video = await get_tracks()
    pc.addTrack(relay.subscribe(video))
    loop = asyncio.get_event_loop()

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState == "failed":
            await pc.close()
        print(f"Connection state: {pc.connectionState}")

    async def send_offer():
        if pc.iceGatheringState == 'complete':
            message = json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
            await loop.sock_sendall(conn, message.encode('utf-8'))
            params = json.loads((await loop.sock_recv(conn, 8192)).decode('utf-8'))
            if "sdp" in params.keys():
                answer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
                await pc.setRemoteDescription(answer)
        else:
            pc.once("icegatheringstatechange", send_offer)

    await send_offer()


def main():
    parser = ArgumentParser()
    parser.add_argument("host", help='Server IP address')
    parser.add_argument("port", type=int, help='Server port')
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    loop.create_task(open_socket(args))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.stop()


if __name__ == '__main__':
    main()
