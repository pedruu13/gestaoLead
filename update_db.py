import sqlite3

def update():
    conn = sqlite3.connect('leads.db')
    c = conn.cursor()
    columns_to_add = [
        ('copy_texto', 'TEXT'),
        ('analise_ia', 'TEXT'),
        ('estrategia_ia', 'TEXT')
    ]
    for col_name, col_type in columns_to_add:
        try:
            c.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

if __name__ == '__main__':
    update()
