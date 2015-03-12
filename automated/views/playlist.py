from datetime import timedelta
from flask import abort, redirect, render_template, request, url_for
from pydub import AudioSegment
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound
from werkzeug import secure_filename

from automated.db import Session, Artist, Category, Song, string_to_timedelta

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
        return "Please enter a name for the new category.", 400
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
            artist = Session.query(Artist).filter(func.lower(Artist.name)==artist_name.lower()).one()
        except NoResultFound:
            artist = Artist(name=artist_name)
            Session.add(artist)
        song.artists.append(artist)

    start = request.form["start"].strip()
    if len(start)==0:
        song.start = timedelta(0)
    else:
        try:
            start = string_to_timedelta(start)
            if start > timedelta(0, 3):
                return "Start point can't be later than 3 seconds.", 400
            song.start = start
        except ValueError:
            return "Please enter an end point in the form MM:SS.", 400

    end = request.form["end"].strip()
    if len(end)==0:
        segment = AudioSegment.from_file("songs/"+song.filename)
        song.end = timedelta(0, segment.duration_seconds)
    else:
        try:
            song.end = string_to_timedelta(end)
        except ValueError:
            return "Please enter an end point in the form MM:SS.", 400

    min_end = request.form["min_end"].strip()
    if len(end)==0:
        song.min_end = song.end
    else:
        try:
            song.min_end = string_to_timedelta(min_end)
        except ValueError:
            return "Please enter a minimum end point in the form MM:SS.", 400

    max_end = request.form["max_end"].strip()
    if len(end)==0:
        song.max_end = song.end
    else:
        try:
            song.max_end = string_to_timedelta(max_end)
        except ValueError:
            return "Please enter a maximum end point in the form MM:SS.", 400

    try:
        category_id = int(request.form["category_id"])
    except ValueError:
        category_id = None

    if category_id is not None and category_id!=song.category_id:
        try:
            category = Session.query(Category).filter(Category.id==category_id).one()
            song.category = category
        except NoResultFound:
            pass

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

    # Default to not having a start point for now because that's fine for most songs.
    length = request.form["length"].strip()
    if len(length)==0:
        length = timedelta(0, segment.duration_seconds)
    else:
        try:
            length = string_to_timedelta(length)
        except ValueError:
            return "Please enter a length in the form MM:SS.", 400

    song = Song(
        name=request.form["title"],
        category=category,
        end=length,
        min_end=length,
        max_end=length,
        filename="",
    )
    Session.add(song)
    Session.flush()

    artists = [_.strip() for _ in request.form["artist"].split(",")]
    for artist_name in artists:
        if artist_name=="":
            continue
        try:
            artist = Session.query(Artist).filter(func.lower(Artist.name)==artist_name.lower()).one()
        except NoResultFound:
            artist = Artist(name=artist_name)
            Session.add(artist)
        song.artists.append(artist)

    song.filename=("%s_%s" % (song.id, secure_filename(song_file.filename)))[:100]
    song_file.seek(0)
    song_file.save("songs/"+song.filename)

    return redirect(request.headers["Referer"])

