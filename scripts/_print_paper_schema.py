import sqlite3, os

# Get the path to the SQLite database
DB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coindcx.db'))

# Establish the connection to the database
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Check the table schema and the existing records
cur.execute("PRAGMA table_info('paper_trades')")
for r in cur.fetchall():
    print(r)

# Execute the update query to set user_id to 1
try:
    # Update the 'user_id' column to 1 for all records
    cur.execute("UPDATE paper_trades SET user_id = 1")

    # Commit the changes to the database
    conn.commit()
    print("user_id updated to 1 for all records in 'paper_trades' table.")

    # Optionally, verify the update by fetching the records again
    cur.execute("SELECT * FROM paper_trades")
    rows = cur.fetchall()
    if rows:
        print("Updated records from 'paper_trades' table:")
        for r in rows:
            print(r)
    else:
        print("No records found in 'paper_trades' table.")

except sqlite3.OperationalError as e:
    print(f"Database error: {e}")

finally:
    # Close the database connection
    conn.close()
