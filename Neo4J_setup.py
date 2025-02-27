import requests
import json
import os
import json
import time
from datetime import datetime, timedelta
from neo4j import GraphDatabase
from dotenv import load_dotenv
import logging
from typing import Dict, List, Optional


#looging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


#Env
load_dotenv()
access_token = os.getenv('TMDB_ACCESS_TOKEN')
neo4j_uri = os.getenv('NEO4J_URI')
neo4j_user = os.getenv('NEO4J_USER')
neo4j_password = os.getenv('NEO4J_PASSWORD')

class MovieDatabase:
    def __init__(self):
        self.base_url ='https://api.themoviedb.org/3'
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'accept': 'application/json'
        }

        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    def close(self):
        ''' 
        Close The Neo4j driver connection
        '''
        self.driver.close()

    def fetch_popular_movies(self, num_pages:int=10):
        """
        Fetch popular movies from TMDB API
        """

        all_movies = []
        for page in range(1, num_pages + 1):
            try:
                url = f'{self.base_url}/movie/popular?language=en-US&page={page}'
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                all_movies.extend(data['results'])
                logger.info(f'Fetched page {page} of popular movies')
                #rate limit
                time.sleep(0.25)
            except Exception as e:
                logger.error(f'Error fetching page {page}: {str(e)}')
        return all_movies
        
    def fetch_movie_details(self, movie_id):
        '''
        
        Fetch detailes information for a specific movie
        
        '''

        try:
            url = f'{self.base_url}/movie/{movie_id}?append_to_response=credits,keywords'
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching details for movie {movie_id}: {str(e)}")
            return None
        
    def create_movie_node(self, tx, movie_data):
        """
        Create or update a movie node in Neo4j
        """
        query = """
        MERGE (m:Movie {tmdb_id: $tmdb_id})
        SET 
            m.title = $title,
            m.overview = $overview,
            m.release_date = $release_date,
            m.vote_average = $vote_average,
            m.vote_count = $vote_count,
            m.popularity = $popularity,
            m.poster_path = $poster_path,
            m.last_updated = $last_updated
        """
        tx.run(query, {
            'tmdb_id': movie_data['id'],
            'title': movie_data['title'],
            'overview': movie_data['overview'],
            'release_date': movie_data['release_date'],
            'vote_average': movie_data['vote_average'],
            'vote_count': movie_data['vote_count'],
            'popularity': movie_data['popularity'],
            'poster_path': movie_data.get('poster_path', ''),
            'last_updated': datetime.now().isoformat()
        })
    
    def create_person_node(self, tx, person_data: Dict, role: str):
        """
        Create or update a person node (actor/director) in Neo4j
        """
        query = """
        MERGE (p:Person {tmdb_id: $tmdb_id})
        SET 
            p.name = $name,
            p.profile_path = $profile_path,
            p.last_updated = $last_updated
        """
        tx.run(query, {
            'tmdb_id': person_data['id'],
            'name': person_data['name'],
            'profile_path': person_data.get('profile_path', ''),
            'last_updated': datetime.now().isoformat()
        })

        # Create relationship based on role
        if role == 'ACTED_IN':
            query = """
            MATCH (p:Person {tmdb_id: $person_id})
            MATCH (m:Movie {tmdb_id: $movie_id})
            MERGE (p)-[r:ACTED_IN]->(m)
            SET r.character = $character
            """
            tx.run(query, {
                'person_id': person_data['id'],
                'movie_id': person_data['movie_id'],
                'character': person_data.get('character', '')
            })
        elif role == 'DIRECTED':
            query = """
            MATCH (p:Person {tmdb_id: $person_id})
            MATCH (m:Movie {tmdb_id: $movie_id})
            MERGE (p)-[r:DIRECTED]->(m)
            """
            tx.run(query, {
                'person_id': person_data['id'],
                'movie_id': person_data['movie_id']
            })

    def update_database(self):
        """
        Main function to update the Neo4j database with movie data
        """
        try:
            # Fetch popular movies
            movies = self.fetch_popular_movies(num_pages=10)  # Fetches 200 movies (20 per page)
            
            with self.driver.session() as session:
                for movie in movies:
                    # Fetch detailed information for each movie
                    details = self.fetch_movie_details(movie['id'])
                    if not details:
                        continue

                    # Create movie node
                    session.execute_write(self.create_movie_node, details)

                    # Process cast
                    if 'credits' in details:
                        for actor in details['credits']['cast'][:10]:  # Top 10 actors
                            actor['movie_id'] = details['id']
                            session.execute_write(self.create_person_node, actor, 'ACTED_IN')

                        # Process directors
                        for crew in details['credits']['crew']:
                            if crew['job'] == 'Director':
                                crew['movie_id'] = details['id']
                                session.execute_write(self.create_person_node, crew, 'DIRECTED')

                    logger.info(f"Processed movie: {details['title']}")
                    time.sleep(0.25)  # Rate limiting

        except Exception as e:
            logger.error(f"Error updating database: {str(e)}")

def main():
    # Create indexes for better performance
    # def create_indexes(tx):
    #     tx.run("CREATE INDEX movie_tmdb_id IF NOT EXISTS FOR (m:Movie) ON (m.tmdb_id)")
    #     tx.run("CREATE INDEX person_tmdb_id IF NOT EXISTS FOR (p:Person) ON (p.tmdb_id)")

    movie_db = MovieDatabase()
    
    try:
        # Create indexes
        with movie_db.driver.session() as session:
            session.execute_write(create_indexes)

        # Update database
        movie_db.update_database()
        
    finally:
        movie_db.close()

if __name__ == "__main__":
    main()