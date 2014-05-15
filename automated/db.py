from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import backref, relationship, scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Table,
    Column,
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

engine = create_engine("postgres://meow:meow@localhost/foreverchannel", convert_unicode=True, pool_recycle=3600, echo=True)
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
    album = Column(Unicode(50), nullable=True)
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


class Clockwheel(Base):
    __tablename__ = "clockwheels"
    id = Column(Integer, primary_key=True)
    name = Column(Unicode(50), nullable=False)

    def __repr__(self):
        return "<Clockwheel #%s: %s>" % (self.id, self.name)


class ClockwheelItem(Base):
    __tablename__ = "clockwheel_items"
    clockwheel_id = Column(Integer, ForeignKey("clockwheels.id"), primary_key=True)
    number = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)

    def __repr__(self):
        return "<Clockwheel #%s item #%s: category #%s>" % (self.clockwheel_id, self.number, self.category_id)


class ClockwheelHour(Base):
    __tablename__ = "clockwheel_hours"
    day = Column(Integer, primary_key=True)
    hour = Column(Integer, primary_key=True)
    clockwheel_id = Column(Integer, ForeignKey("clockwheels.id"), nullable=False)

    def __repr__(self):
        return "<Day #%s hour #%s: clockwheel #%s>" % (self.day, self.hour, self.clockwheel_id)


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


class Play(Base):
    __tablename__ = "plays"
    id = Column(Integer, primary_key=True)
    # XXX NEEDS AN INDEX ON THIS
    time = Column(DateTime, nullable=False)
    length = Column(Interval, nullable=False)
    type = Column(Enum("song", "event", "stop", name="play_type"), nullable=False, default="song")
    song_id = Column(Integer, ForeignKey("songs.id"), nullable=False)


song_artists = Table("song_artists", Base.metadata,
    Column("song_id", Integer, ForeignKey("songs.id"), primary_key=True),
    Column("artist_id", Integer, ForeignKey("artists.id"), primary_key=True)
)

Song.category = relationship(Category, backref="songs")
Song.artists = relationship("Artist", secondary=song_artists, backref="songs", order_by=Artist.name.asc())

Clockwheel.items = relationship(ClockwheelItem, backref="clockwheel", order_by=ClockwheelItem.number.asc())
ClockwheelItem.category = relationship(Category)

ClockwheelHour.clockwheel = relationship(Clockwheel)

Play.song = relationship(Song)

def string_to_timedelta(input_string):
    split = input_string.split(":")
    # hh:mm:ss
    if len(split)==3:
        td = timedelta(0, float(split[0])*3600 + float(split[1])*60 + float(split[2]))
    # mm:ss
    elif len(split)==2:
        td = timedelta(0, float(split[0])*60 + float(split[1]))
    # seconds only
    elif len(split)==1:
        td = timedelta(0, float(split[0]))
    # ???
    else:
        raise ValueError
    # Lengths can't be negative.
    if td<timedelta(0):
        raise ValueError
    return td
