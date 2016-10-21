import os, time

from datetime import datetime, timedelta
from redis import StrictRedis
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from automated.db import (
    session_scope,
    Artist,
    Category,
    Event,
    Sequence,
    SequenceItem,
    Song,
    Stream,
)


redis = StrictRedis(decode_responses=True)


def get_stream():
    with session_scope() as db:
        return db.query(Stream).filter(Stream.url_name == os.environ["STREAM"]).one()


def get_default_sequence():
    with session_scope() as db:
        return db.query(Sequence).join(Stream).filter(Stream.url_name == os.environ["STREAM"]).first()


def find_event(last_event, range_start):
    with session_scope() as db:
        event_query = db.query(Event).filter(Event.stream_id == (
            db.query(Stream.url_name).filter(Stream.url_name == os.environ["STREAM"])
        ))
        if last_event:
            event_query = event_query.filter(Event.start_time > last_event.start_time)
        else:
            event_query = event_query.filter(Event.start_time > range_start)
        range_end = range_start + timedelta(0, 3600)
        event_query = event_query.filter(Event.start_time <= range_end)
        event_query = event_query.order_by(Event.start_time)

        event = event_query.first()

        # Force SQLAlchemy to fetch associated items before we destroy the session.
        # doing this because i have no idea how to get joinedload() to fetch them
        # TODO figure that out
        if event:
            event.sequence
            for item in event.items:
                item.start_time
                if hasattr(item, "song"):
                    item.song.artists
                if hasattr(item, "start"):
                    item.start

        return event


def populate_sequence_items(sequence):
    with session_scope() as db:
        return db.query(SequenceItem, Category).join(Category).filter(
            SequenceItem.sequence == sequence
        ).order_by(SequenceItem.number).all() if sequence is not None else []


def pick_song(queue_time, category_id=None, songs=None, artists=None, length=None):
    with session_scope() as db:

        song_query = db.query(Song).order_by(func.random())

        if category_id is not None:
            song_query = song_query.filter(Song.category_id == category_id)

        queue_timestamp = time.mktime(queue_time.timetuple())

        # Song limit
        song_timestamp = queue_timestamp - float(redis.get("song_limit"))
        if songs is None:
            songs = set()
        for item_id in redis.zrangebyscore("play_queue", song_timestamp, queue_timestamp):
            song_id = redis.hget("item:" + item_id, "song_id")
            if song_id is not None:
                songs.add(song_id)
        if len(songs) != 0:
            song_query = song_query.filter(~Song.id.in_(songs))

        # Artist limit
        artist_timestamp = queue_timestamp - float(redis.get("artist_limit"))
        if artists is None:
            artists = set()
        for item_id in redis.zrangebyscore("play_queue", artist_timestamp, queue_timestamp):
            artists = artists | redis.smembers("item:" + item_id + ":artists")
        if len(artists) != 0:
            song_query = song_query.filter(~Song.artists.any(Artist.id.in_(artists)))

        song_query = song_query.options(joinedload(Song.artists))

        if length is not None:
            length_song = song_query.filter(and_(
                Song.min_end-Song.start <= length,
                Song.max_end-Song.start >= length,
            )).first()
            if length_song is not None:
                return length_song

        return song_query.first()

