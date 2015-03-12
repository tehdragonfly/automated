from datetime import timedelta

from automated.helpers.schedule import (
    get_clockwheel,
    pick_song,
    populate_cw_items,
)

TEN_MINUTES = timedelta(0, 600)


def plan_attempt(target_length, error_margin, next_time, cw, cw_items):

    min_target_length = target_length - error_margin
    max_target_length = target_length + error_margin

    attempt_length = timedelta(0)
    attempt_min_length = timedelta(0)
    attempt_max_length = timedelta(0)

    # Clone this so we don't alter the original.
    cw_items = list(cw_items)

    songs = []

    continues = 0

    while attempt_length < target_length:

        # Cancel if we run out of songs.
        if continues == 10:
            break

        remaining_time = target_length - attempt_length

        attempt_songs = set(_[0].id for _ in songs)
        attempt_artists = set()
        for song, length in songs:
            for artist in song.artists:
                attempt_artists.add(artist.id)

        if cw is None or len(cw_items) == 0:

            # If there isn't a clockwheel, just pick any song.
            song = pick_song(
                next_time,
                songs=attempt_songs, artists=attempt_artists,
                length=remaining_time if remaining_time <= TEN_MINUTES else None,
            )

        else:

            # Otherwise pick songs from the clockwheel.
            item, category = cw_items.pop(0)
            song = pick_song(
                next_time, category.id,
                songs=attempt_songs, artists=attempt_artists,
                length=remaining_time if remaining_time <= TEN_MINUTES else None,
            )

        if song is None:
            continues += 1
            continue

        continues = 0

        songs.append([song, song.length])

        attempt_length += song.length
        attempt_min_length += song.min_length
        attempt_max_length += song.max_length

        next_time += song.length

        # Check if we need a new clockwheel
        # or if the item list needs repopulating.
        new_cw = get_clockwheel(next_time)
        if new_cw != cw or len(cw_items) == 0:
            cw = get_clockwheel(next_time)
            cw_items = populate_cw_items(cw)

    can_shorten = attempt_min_length <= max_target_length
    can_lengthen = attempt_max_length - songs[-1][0].max_length >= min_target_length

    return {
        "songs": songs,
        "cw": cw,
        "cw_items": cw_items,
        # Full lengths
        "length": attempt_length,
        "min_length": attempt_min_length,
        "max_length": attempt_max_length,
        "distance": attempt_length-target_length,
        # Lengths minus last song
        "mls_length": attempt_length-songs[-1][0].length,
        "mls_min_length": attempt_min_length-songs[-1][0].min_length,
        "mls_max_length": attempt_max_length-songs[-1][0].max_length,
        "mls_distance": target_length-(attempt_length-songs[-1][0].length),
        # Validity
        "can_shorten": can_shorten,
        "can_lengthen": can_lengthen,
    }


def shorten(songs, distance, error_margin):
    while distance > error_margin:
        for song in songs:
            # Shorten each item by whichever is smallest:
            # - distance remaining
            # - song shortenability
            # - one second
            shorten_by = min(
                distance,
                song[1] - song[0].min_length,
                timedelta(0, 1),
            )
            song[1] -= shorten_by
            distance -= shorten_by
    return songs


def lengthen(songs, distance, error_margin):
    while distance > error_margin:
        for song in songs:
            # Lengthen each item by whichever is smallest:
            # - distance remaining
            # - song lengthenability
            # - one second
            lengthen_by = min(
                distance,
                song[0].max_length - song[1],
                timedelta(0, 1),
            )
            song[1] += lengthen_by
            distance -= lengthen_by
    return songs
