import sqlite3

def init_db():
    conn = sqlite3.connect("movies.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            title TEXT,
            type TEXT,
            season INTEGER,
            episode INTEGER,
            quality TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_file(file_id, title, type_, season=None, episode=None, quality=None):
    conn = sqlite3.connect("movies.db")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO files (file_id, title, type, season, episode, quality)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (file_id, title, type_, season, episode, quality))
    conn.commit()
    conn.close()

def search_files(query):
    from fuzzywuzzy import process
    conn = sqlite3.connect("movies.db")
    cur = conn.cursor()
    cur.execute("SELECT title, file_id, type, season FROM files")
    all_files = cur.fetchall()
    conn.close()

    titles = [f[0] for f in all_files]
    matches = process.extract(query, titles, limit=5)
    results = []
    for match in matches:
        for row in all_files:
            if row[0] == match[0]:
                results.append(row)
                break
    return results
