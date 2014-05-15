from datetime import timedelta
from flask import abort, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.orm import joinedload_all
from sqlalchemy.orm.exc import NoResultFound

from db import Session, Play

def log():
    plays = Session.query(Play).options(
        joinedload_all("song.category"),
        joinedload_all("song.artists"),
    ).all()
    return render_template(
        "log.html",
        section="log",
        log=plays,
    )

