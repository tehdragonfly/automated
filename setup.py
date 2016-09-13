import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'README.md')) as f:
    README = f.read()

CHANGES = ""

setup(
    name="automated",
    packages=find_packages(),
    zip_safe=False,
    install_requires=[
        "aioredis",
        "flask",
        "gunicorn",
        "psycopg2",
        "pydub",
        "python-vlc",
        "redis",
        "sqlalchemy",
    ],
    entry_points="""\
    """,
)

