#Importing libraries that we need

from sqlalchemy import create_engine, Table, Column, Integer, String, ForeignKey, MetaData
import pandas as pd

#Connecting to sql server

engine = create_engine("mysql+mysqlconnector://root:your_password@localhost/cinema_db")

metadata = MetaData()

#Creating tables

actors = Table("actors", metadata,
    Column("actor_id", Integer, primary_key=True),
    Column("name", String(100))
)

movies = Table("movies", metadata,
    Column("movie_id", Integer, primary_key=True),
    Column("title", String(200)),
    Column("genre_id", Integer, ForeignKey("genres.genre_id"))
)

genres = Table("genres", metadata,
    Column("genre_id", Integer, primary_key=True),
    Column("genre_name", String(50))
)

actor_movie = Table("actor_movie", metadata,
    Column("actor_id", Integer, ForeignKey("actors.actor_id")),
    Column("movie_id", Integer, ForeignKey("movies.movie_id"))
)

#Using Inner join for connecting the tables


query = (
    actors.join(actor_movie, actors.c.actor_id == actor_movie.c.actor_id)
          .join(movies, actor_movie.c.movie_id == movies.c.movie_id)
          .join(genres, movies.c.genre_id == genres.c.genre_id)
)

stmt = (
    actors.select()
    .with_only_columns([
        actors.c.name.label("actor_name"),
        movies.c.title.label("movie_title"),
        genres.c.genre_name.label("genre")
    ])
    .select_from(query)
)

#Getting the final table using inner join that has actor and their movies and genre of movie

with engine.connect() as conn:
    result = conn.execute(stmt)
    df = pd.DataFrame(result.fetchall(), columns=result.keys())

#Saving to csv file

df.to_csv("actors_movies_genres.csv", index=False, encoding="utf-8-sig")

#print("دیتاست با SQLAlchemy ساخته شد و در actors_movies_genres.csv ذخیره شد")