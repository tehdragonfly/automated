import os
import subprocess
import time

from datetime import datetime, timedelta
from pydub.utils import get_player_name
from redis import StrictRedis
from uuid import uuid4

from automated.db import Session, Play

redis = StrictRedis()

base_path = "songs/"

PLAYER = get_player_name()
FNULL = open(os.devnull, 'w')

def play_song(queue_time, item_id, item):

    # Calculate how early we're meant to start the item and wait until then.
    play_time = queue_time - float(item["start"])
    time.sleep(play_time - time.time())

    redis.hset("item:"+item_id, "status", "playing")
    Session.add(Play(time=datetime.now(), song_id=int(item["song_id"]), length=timedelta(0, float(item["length"]))))
    Session.commit()
    subprocess.call([PLAYER, "-nodisp", "-autoexit", base_path+item["filename"]], stdout=FNULL, stderr=FNULL)
    redis.hset("item:"+item_id, "status", "played")


def queue_song(queue_time, song):
    queue_item_id = str(uuid4())
    item_info = {
        "status": "queued",
        "song_id": song.id,
        "start": song.start.total_seconds(),
        "length": song.length.total_seconds(),
        "filename": song.filename,
    }
    if song.album is not None:
        item_info["album"] = song.album
    redis.hmset("item:"+queue_item_id, item_info)
    redis.sadd("item:"+queue_item_id+":artists", *(_.id for _ in song.artists))
    redis.zadd("play_queue", time.mktime(queue_time.timetuple()), queue_item_id)

