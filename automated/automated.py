import os
import subprocess
import time

from datetime import datetime, timedelta
from pydub.utils import get_player_name
from redis import StrictRedis
from sqlalchemy import and_, func
from sqlalchemy.orm.exc import NoResultFound
from threading import Thread
from uuid import uuid4

from db import Session, Artist, Category, Clockwheel, ClockwheelHour, ClockwheelItem, Play, Song

redis = StrictRedis()

# Set default values for repetition limits if they don't exist already.
if redis.get("song_limit") is None:
    redis.set("song_limit", 3600)
if redis.get("artist_limit") is None:
    redis.set("artist_limit", 3600)
if redis.get("album_limit") is None:
    redis.set("album_limit", 3600)

base_path = "songs/"

PLAYER = get_player_name()
FNULL = open(os.devnull, 'w')

def play_song(queue_time, item_id, item):

    print "PREPARING", item

    print "QUEUE TIME", queue_time

    # Calculate how early we're meant to start the item and wait until then.

    play_time = queue_time - float(item["start"])

    print "PLAY TIME", queue_time
    print "WAITING", play_time - time.time()

    time.sleep(play_time - time.time())


    redis.hset("item:"+item_id, "status", "playing")
    Session.add(Play(time=datetime.now(), song_id=int(item["song_id"]), length=timedelta(0, float(item["length"]))))
    Session.commit()
    subprocess.call([PLAYER, "-nodisp", "-autoexit", base_path+item["filename"]], stdout=FNULL, stderr=FNULL)
    redis.hset("item:"+item_id, "status", "played")

def play_queue():
    while running:
        t = time.time()
        # Cue things up 5 seconds ahead.
        play_items = redis.zrangebyscore("play_queue", t+4, t+5, withscores=True)
        for item_id, queue_time in play_items:
            item = redis.hgetall("item:"+item_id)
            if len(item)==0:
                redis.zrem("play_queue", item_id, item)
                continue
            if item["status"] != "queued":
                continue
            Thread(target=play_song, args=(queue_time, item_id, item)).start()
            redis.hset("item:"+item_id, "status", "preparing")
        time.sleep(0.01)

def get_clockwheel(target_time):
    if target_time is None:
        target_time = datetime.now()
    try:
        return Session.query(Clockwheel).join(ClockwheelHour).filter(and_(
            ClockwheelHour.day==target_time.weekday(),
            ClockwheelHour.hour==target_time.hour,
        )).one()
    except NoResultFound:
        return None

def pick_song(queue_time, category_id=None):

    song_query = Session.query(Song).order_by(func.random())

    if category_id is not None:
        song_query = song_query.filter(Song.category_id==category_id)

    queue_timestamp = time.mktime(queue_time.timetuple())

    # Song limit
    song_timestamp = queue_timestamp - float(redis.get("song_limit"))
    songs = set()
    for item_id in redis.zrangebyscore("play_queue", song_timestamp, queue_timestamp):
        songs.add(redis.hget("item:"+item_id, "song_id"))
    if len(songs)!=0:
        song_query = song_query.filter(~Song.id.in_(songs))

    # Artist limit
    artist_timestamp = queue_timestamp - float(redis.get("artist_limit"))
    artists = set()
    for item_id in redis.zrangebyscore("play_queue", artist_timestamp, queue_timestamp):
        artists = artists | redis.smembers("item:"+item_id+":artists")
    if len(artists)!=0:
        song_query = song_query.filter(~Song.artists.any(Artist.id.in_(artists)))

    # Album limit
    album_timestamp = queue_timestamp - float(redis.get("album_limit"))
    albums = set()
    for item_id in redis.zrangebyscore("play_queue", album_timestamp, queue_timestamp):
        album = redis.hget("item:"+item_id, "album")
        if album is not None:
            albums.add(album)
    if len(albums)!=0:
        song_query = song_query.filter(~Song.album.in_(albums))

    return song_query.first()

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

def scheduler():
    next_time = datetime.fromtimestamp(round(time.time()+5))
    current_cw = get_clockwheel(next_time)
    while True:

        # Trim playlist items older than half an hour.
        # XXX MAKE THIS THE LONGEST REPETITION GAP
        old_items = redis.zrangebyscore("play_queue", 0, time.time()-1800)
        for item_id in old_items:
            redis.zrem("play_queue", item_id)
            redis.delete("item:"+item_id)
            redis.delete("item:"+item_id+":artists")

        print "STARTING LOOP. CURRENT CLOCKWHEEL IS", current_cw

        # Pick songs randomly if we don't have a clockwheel right now.
        if current_cw is None:
            print "CLOCKWHEEL IS NONE, PICKING ANY SONG."
            song = pick_song(next_time)
            if song is None:
                print "NOTHING HERE, SKIPPING."
                continue
            print "SELECTED", song
            queue_song(next_time, song)
            # Pause if we've reached more than 30 minutes into the future.
            while next_time-datetime.now() > timedelta(0, 1800):
                print "SLEEPING"
                time.sleep(300)
            current_cw = get_clockwheel(next_time)

        # Otherwise pick songs from the clockwheel.
        for item, category in Session.query(ClockwheelItem, Category).join(Category).filter(
            ClockwheelItem.clockwheel==current_cw
        ).order_by(ClockwheelItem.number):
            print "ITEM", item
            print "CATEGORY", category
            song = pick_song(next_time, category.id)
            if song is None:
                print "NOTHING HERE, SKIPPING."
                continue
            print "SELECTED", song
            queue_song(next_time, song)
            next_time += song.length
            # Pause if we've reached more than 30 minutes into the future.
            while next_time-datetime.now() > timedelta(0, 1800):
                print "SLEEPING"
                time.sleep(300)
            # Get new clockwheel, skipping the rest of this one if it's changed.
            new_cw = get_clockwheel(next_time)
            if new_cw!=current_cw:
                print "CLOCKWHEEL CHANGED, BREAKING."
                current_cw = new_cw
                break

# Make sure any existing future items are cleared.
future_items = redis.zrangebyscore("play_queue", time.time(), "inf")
for item_id in future_items:
    redis.zrem("play_queue", item_id)
    redis.delete("item:"+item_id)

running = True

Thread(target=play_queue).start()

try:
    scheduler()
except:
    running = False
    raise

