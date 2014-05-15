from datetime import datetime, timedelta
from flask import abort, redirect, render_template, request, url_for
from redis import StrictRedis
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from automated.db import Session, Song

redis = StrictRedis()

def automation():
    play_queue = []
    for item_id, timestamp in redis.zrange("play_queue", 0, -1, withscores=True):
        item = redis.hgetall("item:"+item_id)
        item["length"] = timedelta(0, float(item["length"]))
        song = Session.query(Song).filter(
            Song.id==int(item["song_id"])
        ).options(
            joinedload(Song.artists),
            joinedload(Song.category),
        ).one()
        play_queue.append((datetime.fromtimestamp(timestamp), item, song))
    return render_template(
        "automation.html",
        section="automation",
        play_queue=play_queue,
    )

