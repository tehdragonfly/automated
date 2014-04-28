from datetime import timedelta
from flask import abort, redirect, render_template, request, url_for
from pydub import AudioSegment
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound
from werkzeug import secure_filename

from db import Session, Artist, Category, Song, string_to_timedelta

def playlist(category_id=None):
    songs = Session.query(Song).order_by(Song.name).options(
        joinedload(Song.artists),
        joinedload(Song.category),
    )
    current_category = None
    if category_id is not None:
        try:
            current_category = Session.query(Category).filter(Category.id==category_id).one()
            songs = songs.filter(Song.category==current_category)
        except NoResultFound:
            abort(404)
    all_categories = Session.query(Category).order_by(Category.name).all()
    return render_template(
        "playlist.html",
        section="playlist",
        all_categories=all_categories,
        current_category=current_category,
        songs=songs,
    )

def new_category():
    if "name" not in request.form or request.form["name"]=="":
        abort(400)
    category = Category(name=request.form["name"])
    Session.add(category)
    Session.flush()
    return redirect(url_for("playlist", category_id=category.id))

def song(song_id):
    try:
        song = Session.query(Song).filter(Song.id==song_id).options(
            joinedload(Song.category),
            joinedload(Song.artists),
        ).one()
    except NoResultFound:
        abort(404)
    all_categories = Session.query(Category).order_by(Category.name).all()
    return render_template(
        "song.html",
        section="playlist",
        all_categories=all_categories,
        song=song,
        artist_names=", ".join(_.name for _ in song.artists)
    )

def edit_song(song_id):

    try:
        song = Session.query(Song).filter(Song.id==song_id).options(
            joinedload(Song.category),
            joinedload(Song.artists),
        ).one()
    except NoResultFound:
        abort(404)

    name = request.form["title"].strip()
    if len(name)==0:
        return "Please enter a title.", 400
    song.name = name

    del song.artists[:]
    artists = [_.strip() for _ in request.form["artist"].split(",")]
    for artist_name in artists:
        if artist_name=="":
            continue
        try:
            # XXX NEEDS A UNIQUE CONSTRAINT ON THIS
            artist = Session.query(Artist).filter(func.lower(Artist.name)==artist_name.lower()).one()
        except NoResultFound:
            artist = Artist(name=artist_name)
            Session.add(artist)
        song.artists.append(artist)

    length = request.form["length"].strip()
    if len(length)==0:
        segment = AudioSegment.from_file("songs/"+song.filename)
        song.length = timedelta(0, segment.duration_seconds)
    else:
        try:
            song.length = string_to_timedelta(length)
        except ValueError:
            return "Please enter a length in the form MM:SS.", 400

    return redirect(url_for("song", song_id=song_id))

def new_song():

    name = request.form["title"].strip()
    if len(name)==0:
        return "Please enter a title.", 400

    song_file = request.files["file"]
    try:
        segment = AudioSegment.from_file(song_file)
    except:
        return "That doesn't appear to be a valid audio file. Accepted formats are WAV, MP3 and OGG.", 400

    try:
        category = Session.query(Category).filter(Category.id==request.form["category_id"]).one()
    except (ValueError, NoResultFound):
        return "Invalid category.", 400

    song = Song(
        name=request.form["title"],
        category=category,
        length=timedelta(0, segment.duration_seconds),
        filename="",
    )
    Session.add(song)
    Session.flush()

    artists = [_.strip() for _ in request.form["artist"].split(",")]
    for artist_name in artists:
        if artist_name=="":
            continue
        try:
            # XXX NEEDS A UNIQUE CONSTRAINT ON THIS
            artist = Session.query(Artist).filter(func.lower(Artist.name)==artist_name.lower()).one()
        except NoResultFound:
            artist = Artist(name=artist_name)
            Session.add(artist)
        song.artists.append(artist)

    song.filename=("%s_%s" % (song.id, secure_filename(song_file.filename)))[:100]
    song_file.seek(0)
    song_file.save("songs/"+song.filename)

    return redirect(request.headers["Referer"])

