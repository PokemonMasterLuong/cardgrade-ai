import sqlite3
conn = sqlite3.connect('users.db')
conn.execute("UPDATE users SET verified = 1 WHERE email = 'alexluongpokemonmaster@gmail.com'")
conn.commit()
print('Done')
