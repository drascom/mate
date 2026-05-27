"""Mate Core entry point.

Çağrı: mate-core dizininden `python main.py`. core/, pi/, voice_bridge/
paketleri sys.path[0] (=mate-core) üzerinden import edilir.
"""
import uvicorn

from core import config
from core.app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level="warning",
        access_log=False,
    )
