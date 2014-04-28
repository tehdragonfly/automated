from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import backref, relationship, scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Table,
    Column,
    ForeignKey,
    Integer,
    Interval,
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
    length = Column(Interval, nullable=False)
    filename = Column(Unicode(100), nullable=False)

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


song_artists = Table('song_artists', Base.metadata,
    Column('song_id', Integer, ForeignKey('songs.id'), primary_key=True),
    Column('artist_id', Integer, ForeignKey('artists.id'), primary_key=True)
)

Song.category = relationship(Category, backref="songs")
Song.artists = relationship("Artist", secondary=song_artists, backref="songs", order_by=Artist.name.asc())

Clockwheel.items = relationship(ClockwheelItem, backref="clockwheel", order_by=ClockwheelItem.number.asc())
ClockwheelItem.category = relationship(Category)

ClockwheelHour.clockwheel = relationship(Clockwheel)

def string_to_timedelta(input_string):
    split = input_string.split(":")
    # hh:mm:ss
    if len(split)==3:
        return timedelta(0, float(split[0])*3600 + float(split[1])*60 + float(split[2]))
    # mm:ss
    elif len(split)==2:
        return timedelta(0, float(split[0])*60 + float(split[1]))
    # seconds only
    elif len(split)==1:
        return timedelta(0, float(split[0]))
    # ???
    else:
        raise ValueError

