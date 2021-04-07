import asyncio
import json
import socket

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaRecorder, MediaRelay
from argparse import ArgumentParser

recorder: MediaRecorder


async def open_socket(args):
    sock = socket.socket()
    sock.bind(('', args.port))
    sock.setblocking(False)
    sock.listen(1)
    loop = asyncio.get_event_loop()
    conn, _ = await loop.sock_accept(sock)

    await create_rtc_connection(conn)


async def create_rtc_connection(conn):
    global recorder
    relay = MediaRelay()
    config = RTCConfiguration([RTCIceServer('stun:stun.l.google.com:19302')])
    pc = RTCPeerConnection(config)
    recorder = MediaRecorder('out.mp4')

    loop = asyncio.get_event_loop()

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState == "failed":
            await pc.close()
        if pc.connectionState == "connected":
            await recorder.start()
        print(f"Connection state: {pc.connectionState}")

    @pc.on("track")
    async def on_track(track):
        if track.kind == "audio":
            recorder.addTrack(track)
        elif track.kind == "video":
            recorder.addTrack(relay.subscribe(track))
        print(f"Track {track.kind} added")

        @track.on("ended")
        async def on_ended():
            await recorder.stop()
            print("Recorder closed")

    data = (await loop.sock_recv(conn, 8192)).decode('utf-8')
    params = json.loads(data)

    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    await pc.setRemoteDescription(offer)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    answer = json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
    await loop.sock_sendall(conn, answer.encode('utf-8'))


def main():
    global recorder
    parser = ArgumentParser()
    parser.add_argument("--port", type=int, help='Server port (default: 443)')
    args = parser.parse_args()

    if not args.port:
        args.port = 443

    loop = asyncio.get_event_loop()
    loop.create_task(open_socket(args))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if recorder is MediaRecorder:
            loop.run_until_complete(recorder.stop())
        loop.stop()


if __name__ == '__main__':
    main()
