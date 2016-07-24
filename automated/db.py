from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import backref, relationship, scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.schema import Index
from sqlalchemy import (
    Table,
    Column,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Interval,
    Time,
    Unicode,
)

import datetime
import time

engine = create_engine(
    "postgres://meow:meow@localhost/foreverchannel",
    convert_unicode=True,
    pool_recycle=3600,
)
Session = scoped_session(sessionmaker(bind=engine, autoflush=False))

Base = declarative_base(bind=engine)
Base.query = Session.query_property()


def init_db():
    Base.metadata.create_all(bind=engine)


class Song(Base):
    __tablename__ = "songs"
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    name = Column(Unicode(50), nullable=False)
    start = Column(Interval, nullable=False, default=timedelta(0))
    end = Column(Interval, nullable=False)
    min_end = Column(Interval, nullable=False)
    max_end = Column(Interval, nullable=False)
    filename = Column(Unicode(100), nullable=False)

    @property
    def length(self):
        return self.end - self.start

    @property
    def min_length(self):
        return self.min_end - self.start

    @property
    def max_length(self):
        return self.max_end - self.start

    def __repr__(self):
        return "<Song #%s: %s>" % (self.id, self.name)


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(Unicode(50), nullable=False)

    def __repr__(self):
        return "<Category #%s: %s>" % (self.id, self.name)


class Artist(Base):
    __tablename__ = "artists"
    id = Column(Integer, primary_key=True)
    name = Column(Unicode(50), nullable=False)

    def __repr__(self):
        return "<Artist #%s: %s>" % (self.id, self.name)


class Sequence(Base):
    __tablename__ = "sequences"
    id = Column(Integer, primary_key=True)
    name = Column(Unicode(50), nullable=False)

    def __repr__(self):
        return "<Sequence #%s: %s>" % (self.id, self.name)


class SequenceItem(Base):
    __tablename__ = "sequence_items"
    sequence_id = Column(Integer, ForeignKey("sequences.id"), primary_key=True)
    number = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)

    def __repr__(self):
        return (
            "<Sequence #%s item #%s: category #%s>"
            % (self.sequence_id, self.number, self.category_id)
        )


class WeeklyEvent(Base):
    __tablename__ = "weekly_events"
    id = Column(Integer, primary_key=True)
    day = Column(Integer, nullable=False)
    time = Column(Time, nullable=False)
    error_margin = Column(Interval, nullable=False)
    name = Column(Unicode(50), nullable=False)
    type = Column(Enum(u"audio", u"stop", name="event_type"))
    length = Column(Interval, nullable=True)
    filename = Column(Unicode(100), nullable=True)

    def __repr__(self):
        return (
            "<WeeklyEvent #%s: %s %s, %s, %s>"
            % (self.id, self.day, self.time, self.type, self.name)
        )


class Event(Base):
    __tablename__ = "events"
    __mapper_args__ = {"polymorphic_on": "type"}
    id = Column(Integer, primary_key=True)
    # TODO stream_id
    start_time = Column(DateTime, nullable=False, unique=True)
    error_margin = Column(Interval, nullable=False)
    type = Column(Enum(u"stop", u"play", name="event_type"), nullable=False)
    name = Column(Unicode(50), nullable=False)
    played = Column(Boolean, nullable=False, default=False)

    def __repr__(self):
        return (
            "<%s #%s: %s, %s, %s>"
            % (self.__class__.__name__, self.id, self.start_time, self.type, self.name)
        )


class StopEvent(Event):
    __mapper_args__ = {"polymorphic_identity": "stop"}


class PlayEvent(Event):
    __mapper_args__ = {"polymorphic_identity": "play"}
    # TODO episode_id
    sequence_id = Column(Integer, ForeignKey("sequences.id"))
    end_time = Column(DateTime)


class EventItem(Base):
    __tablename__ = "event_items"
    __mapper_args__ = {"polymorphic_on": "type"}
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    order = Column(Integer, nullable=False)
    start_time = Column(DateTime, nullable=True)
    error_margin = Column(Interval, nullable=True)
    type = Column(Enum(u"song", u"recording", name="event_item_type"), nullable=False)
    name = Column(Unicode(50), nullable=False)

    def __repr__(self):
        return "<%s #%s: %s>" % (self.__class__.__name__, self.id, self.name)


class SongEventItem(EventItem):
    __mapper_args__ = {"polymorphic_identity": "song"}
    song_id = Column(Integer, ForeignKey("songs.id"))

    def __repr__(self):
        return "<%s #%s: %s>" % (self.__class__.__name__, self.id, self.song)

    @property
    def length(self):
        return self.song.length


class RecordingEventItem(EventItem):
    __mapper_args__ = {"polymorphic_identity": "recording"}
    length = Column(Interval)


class Play(Base):
    __tablename__ = "plays"
    id = Column(Integer, primary_key=True)
    time = Column(DateTime, nullable=False)
    length = Column(Interval, nullable=False)
    type = Column(Enum("song", "event", "stop", name="play_type"), nullable=False, default="song")
    song_id = Column(Integer, ForeignKey("songs.id"), nullable=False)


song_artists = Table(
    "song_artists", Base.metadata,
    Column("song_id", Integer, ForeignKey("songs.id"), primary_key=True),
    Column("artist_id", Integer, ForeignKey("artists.id"), primary_key=True)
)


Song.category = relationship(Category, backref="songs")
Song.artists = relationship("Artist", secondary=song_artists, backref="songs", order_by=Artist.name.asc())

Sequence.items = relationship(SequenceItem, backref="sequence", order_by=SequenceItem.number.asc())
SequenceItem.category = relationship(Category)

Event.items = relationship(EventItem, backref="items", order_by=EventItem.order)
PlayEvent.sequence = relationship(Sequence)

SongEventItem.song = relationship(Song)

Play.song = relationship(Song)


Index("play_time", Play.time)


def string_to_timedelta(input_string):
    split = input_string.split(":")
    # hh:mm:ss
    if len(split) == 3:
        td = timedelta(0, float(split[0])*3600 + float(split[1])*60 + float(split[2]))
    # mm:ss
    elif len(split) == 2:
        td = timedelta(0, float(split[0])*60 + float(split[1]))
    # seconds only
    elif len(split) == 1:
        td = timedelta(0, float(split[0]))
    # ???
    else:
        raise ValueError
    # Lengths can't be negative.
    if td < timedelta(0):
        raise ValueError
    return td
