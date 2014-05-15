from datetime import date, datetime, timedelta
from flask import abort, redirect, render_template, request, url_for
from sqlalchemy import and_
from sqlalchemy.orm import joinedload_all
from sqlalchemy.orm.exc import NoResultFound

from db import Session, Play

def log():
    if "date" in request.values and request.values["date"]!="":
        try:
            day, month, year = request.values["date"].split("/")
            year = int(year)
            # strftime doesn't like years before 1900
            if year<1900:
                raise ValueError
            current_date = date(int(year), int(month), int(day))
        except ValueError:
            return "Please enter a date in the form dd/mm/yyyy.", 400
    else:
        current_date = date.today()
    # In theory we could just use the date_trunc function but I'm pretty
    # sure that's only supported by Postgres.
    min_datetime = datetime(
        current_date.year,
        current_date.month,
        current_date.day
    )
    max_datetime = min_datetime + timedelta(1)
    plays = Session.query(Play).filter(and_(
        Play.time>=min_datetime,
        Play.time<max_datetime,
    )).options(
        joinedload_all("song.category"),
        joinedload_all("song.artists"),
    ).all()
    return render_template(
        "log.html",
        section="log",
        current_date=current_date,
        log=plays,
    )

