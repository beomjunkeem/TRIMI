"""Render index.html?record in headless Chrome and encode the frames to a 4K MP4.

Usage: python3 tools/record_video.py [--fps 60] [--seconds 30] [--out rotation_4k.mp4]
"""
import argparse
import functools
import http.server
import os
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

parser = argparse.ArgumentParser()
parser.add_argument("--fps", type=int, default=60)
parser.add_argument("--seconds", type=float, default=30.0)  # 360deg / 12deg/s
parser.add_argument("--speed", type=float, default=12.0)  # deg per second, same as the page
parser.add_argument("--width", type=int, default=3840)
parser.add_argument("--height", type=int, default=2160)
parser.add_argument("--out", default=os.path.join(ROOT, "rotation_4k.mp4"))
parser.add_argument("--first-frame", help="also save frame 0 as a PNG here")
parser.add_argument("--src", help="model to load instead of data/model.glb (path relative to the page)")
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()

ffmpeg = subprocess.Popen(
    [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(args.fps), "-c:v", "png", "-i", "-",
        "-vf", "format=yuv420p",
        "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-profile:v", "high", "-level", "5.2",
        "-movflags", "+faststart", args.out,
    ],
    stdin=subprocess.PIPE,
)
done = threading.Event()
state = {"frames": 0, "error": None}


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.startswith("/frame"):
            ffmpeg.stdin.write(body)
            if state["frames"] == 0 and args.first_frame:
                with open(args.first_frame, "wb") as f:
                    f.write(body)
            state["frames"] += 1
            if state["frames"] % 60 == 0:
                print(f"  {state['frames']} frames", flush=True)
        elif self.path.startswith("/done"):
            done.set()
        elif self.path.startswith("/error"):
            state["error"] = body.decode(errors="replace")
            done.set()
        self.send_response(204)
        self.end_headers()


server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(Handler, directory=ROOT))
threading.Thread(target=server.serve_forever, daemon=True).start()

# Viewport is the output size at 2x device pixels, so model-viewer renders natively at 4K.
scale = 2
url = (
    f"http://127.0.0.1:{args.port}/index.html?record&fps={args.fps}"
    f"&seconds={args.seconds}&speed={args.speed}&w={args.width // scale}&h={args.height // scale}"
    + (f"&src={args.src}" if args.src else "")
)
profile = tempfile.mkdtemp(prefix="chrome-record-")
chrome = subprocess.Popen(
    [
        CHROME, "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
        # Extra height: headless Chrome's viewport is a bit shorter than the window.
        f"--window-size={args.width // scale},{args.height // scale + 200}",
        f"--force-device-scale-factor={scale}", "--hide-scrollbars",
        "--use-angle=metal", "--enable-gpu-rasterization", "--ignore-gpu-blocklist",
        "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        url,
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

print(f"Recording {url}", flush=True)
done.wait()
chrome.terminate()
server.shutdown()
ffmpeg.stdin.close()
ffmpeg.wait()

if state["error"]:
    sys.exit(f"Recording failed in page:\n{state['error']}")
print(f"Wrote {state['frames']} frames -> {args.out}")
