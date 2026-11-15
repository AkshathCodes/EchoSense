"""Local-only range readout static server. Exactly three public assets, no recordings."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import argparse
ROOT=Path(__file__).resolve().parents[1]
ASSETS={"/":("range-preview/index.html","text/html"),"/src/range.js":("src/range.js","text/javascript"),"/src/feed.js":("src/feed.js","text/javascript")}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        asset=ASSETS.get(self.path.split("?")[0])
        if not asset: self.send_error(404); return
        path,mime=asset
        data=(ROOT/path).read_bytes()
        self.send_response(200); self.send_header("Content-Type",mime+"; charset=utf-8")
        self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--port",type=int,default=4180); args=parser.parse_args()
    server=ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    print(f"ECHO range readout http://127.0.0.1:{server.server_port}/",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
