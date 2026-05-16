import os 
from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
import requests
from datetime import datetime, date
import hashlib

app = Flask(__name__)
app.secret_key = 'cinebook_secret_2024'

TMDB_API_KEY = '22ae35429832b54753cac0a4a4cdb861'
TMDB_BASE = 'https://api.themoviedb.org/3'
TMDB_IMG = 'https://image.tmdb.org/t/p/w500'

LANGUAGES = ['Hindi', 'English', 'Telugu', 'Tamil', 'Kannada', 'Malayalam', 'Bengali', 'Marathi']
FORMATS = ['2D', '3D']

def get_db():
    return mysql.connector.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', 'Mashritha@03'),
        database=os.environ.get('DB_NAME', 'movie_booking')
    )

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def sync_tmdb_movies():
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        response = requests.get(f'{TMDB_BASE}/movie/now_playing', params={
            'api_key': TMDB_API_KEY,
            'region': 'IN',
            'language': 'en-IN',
            'page': 1
        })
        data = response.json()
        for m in data.get('results', [])[:20]:
            cursor.execute('SELECT movie_id FROM movies WHERE title = %s', (m['title'],))
            existing = cursor.fetchone()
            if not existing:
                lang = 'Hindi' if m.get('original_language') == 'hi' else \
                       'Telugu' if m.get('original_language') == 'te' else \
                       'Tamil' if m.get('original_language') == 'ta' else \
                       'Kannada' if m.get('original_language') == 'kn' else \
                       'Malayalam' if m.get('original_language') == 'ml' else 'English'
                poster = TMDB_IMG + m['poster_path'] if m.get('poster_path') else None
                cursor.execute('''INSERT INTO movies (title, genre, language, duration, rating, release_date, format, poster_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                    (m['title'], 'Drama', lang, 140, round(m.get('vote_average', 7.0), 1),
                     m.get('release_date', str(date.today())), '2D', poster))
                movie_id = cursor.lastrowid

                # ✅ Auto-create shows for next 7 days for new movies
                from datetime import timedelta
                days = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
                times = ['10:00:00', '14:00:00', '18:00:00', '21:00:00']
                for i in range(7):
                    show_date = date.today() + timedelta(days=i)
                    day_name = days[show_date.weekday()]
                    for theatre_id in [1, 2]:
                        for show_time in times:
                            cursor.execute('''INSERT INTO shows 
                                (movie_id, theatre_id, show_date, show_time, price, available_seats, show_day)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                                (movie_id, theatre_id, show_date, show_time, 220, 50, day_name))
                            show_id = cursor.lastrowid
                            # Auto-create seats A1-E10
                            for row in ['A','B','C','D','E']:
                                for num in range(1, 11):
                                    cursor.execute('''INSERT INTO seats (show_id, seat_number, seat_status)
                                        VALUES (%s, %s, 'Available')''',
                                        (show_id, f'{row}{num}'))
        db.commit()
        cursor.close()
        db.close()
        print('✅ TMDB sync done')
    except Exception as e:
        import traceback
        print(f'❌ TMDB sync error: {e}')
        traceback.print_exc()

# ─── AUTH ───────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = hash_password(request.form['password'])
        phone = request.form['phone']
        try:
            db = get_db()
            cursor = db.cursor()
            cursor.execute('INSERT INTO users (name, email, password, phone) VALUES (%s,%s,%s,%s)',
                           (name, email, password, phone))
            db.commit()
            cursor.close()
            db.close()
            flash('Account created! Please login.', 'success')
            return redirect(url_for('login'))
        except mysql.connector.IntegrityError:
            flash('Email already registered.', 'danger')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = hash_password(request.form['password'])
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute('SELECT * FROM users WHERE email=%s AND password=%s', (email, password))
        user = cursor.fetchone()
        cursor.close()
        db.close()
        if user:
            session['user_id'] = user['user_id']
            session['user_name'] = user['name']
            return redirect(url_for('index'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── HOME / MOVIE LISTING ────────────────────────────────

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    sync_tmdb_movies()
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute('SELECT * FROM cities')
    cities = cursor.fetchall()
    lang = request.args.get('language', '')
    fmt = request.args.get('format', '')
    city_id = request.args.get('city_id', '')

    # ✅ FIXED: Show ALL movies from DB (no JOIN with shows needed)
    query = 'SELECT * FROM movies WHERE 1=1'
    params = []
    if lang:
        query += ' AND language = %s'
        params.append(lang)
    if fmt:
        query += ' AND format = %s'
        params.append(fmt)
    query += ' ORDER BY release_date DESC'

    cursor.execute(query, params)
    movies = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('index.html', movies=movies, cities=cities,
                           languages=LANGUAGES, formats=FORMATS,
                           selected_lang=lang, selected_fmt=fmt, selected_city=city_id)

# ─── SHOWS ──────────────────────────────────────────────

@app.route('/shows/<int:movie_id>')
def shows(movie_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute('SELECT * FROM movies WHERE movie_id = %s', (movie_id,))
    movie = cursor.fetchone()
    city_id = request.args.get('city_id', '')
    show_date = request.args.get('show_date', str(date.today()))
    cursor.execute('SELECT * FROM cities')
    cities = cursor.fetchall()
    query = '''SELECT s.*, t.theatre_name, t.location, c.city_name
               FROM shows s
               JOIN theatres t ON s.theatre_id = t.theatre_id
               JOIN cities c ON t.location = c.city_name
               WHERE s.movie_id = %s AND s.show_date = %s'''
    params = [movie_id, show_date]
    if city_id:
        query += ' AND c.city_id = %s'
        params.append(city_id)
    cursor.execute(query, params)
    show_list = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('shows.html', movie=movie, shows=show_list,
                           cities=cities, selected_city=city_id, show_date=show_date)

# ─── SEATS ──────────────────────────────────────────────

@app.route('/seats/<int:show_id>')
def seats(show_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute('''SELECT s.*, m.title, m.language, m.format,
                      t.theatre_name, t.location
                      FROM shows s
                      JOIN movies m ON s.movie_id = m.movie_id
                      JOIN theatres t ON s.theatre_id = t.theatre_id
                      WHERE s.show_id = %s''', (show_id,))
    show = cursor.fetchone()
    cursor.execute('SELECT * FROM seats WHERE show_id = %s ORDER BY seat_number', (show_id,))
    seat_list = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('seats.html', show=show, seats=seat_list)

# ─── PAYMENT ────────────────────────────────────────────

@app.route('/payment', methods=['GET', 'POST'])
def payment():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        show_id = request.form['show_id']
        seat_ids = request.form.getlist('seat_ids')
        if not seat_ids:
            flash('Please select at least one seat.', 'danger')
            return redirect(url_for('seats', show_id=show_id))
        session['pending_show_id'] = show_id
        session['pending_seat_ids'] = seat_ids
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute('''SELECT s.price, m.title, t.theatre_name, s.show_date, s.show_time
                          FROM shows s JOIN movies m ON s.movie_id=m.movie_id
                          JOIN theatres t ON s.theatre_id=t.theatre_id
                          WHERE s.show_id=%s''', (show_id,))
        show = cursor.fetchone()
        seats_info = []
        for sid in seat_ids:
            cursor.execute('SELECT seat_number FROM seats WHERE seat_id=%s', (sid,))
            seats_info.append(cursor.fetchone())
        cursor.close()
        db.close()
        total = float(show['price']) * len(seat_ids)
        return render_template('payment.html', show=show, seats=seats_info,
                               total=total, seat_ids=seat_ids, show_id=show_id)
    return redirect(url_for('index'))

@app.route('/confirm_payment', methods=['POST'])
def confirm_payment():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    show_id = request.form['show_id']
    seat_ids = request.form.getlist('seat_ids')
    payment_method = request.form['payment_method']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute('SELECT price FROM shows WHERE show_id=%s', (show_id,))
    show = cursor.fetchone()
    price = float(show['price'])
    total = price * len(seat_ids)
    booking_ids = []
    for sid in seat_ids:
        cursor.execute('''INSERT INTO bookings (user_id, show_id, seat_id, status, total_amount)
                          VALUES (%s,%s,%s,'confirmed',%s)''',
                       (session['user_id'], show_id, sid, price))
        booking_id = cursor.lastrowid
        booking_ids.append(booking_id)
        cursor.execute("UPDATE seats SET seat_status='Booked' WHERE seat_id=%s", (sid,))
    cursor.execute('''INSERT INTO payments (booking_id, amount, payment_method, payment_status)
                      VALUES (%s,%s,%s,'success')''', (booking_ids[0], total, payment_method))
    db.commit()
    cursor.close()
    db.close()
    flash('Booking confirmed!', 'success')
    return redirect(url_for('confirmation', booking_id=booking_ids[0]))

@app.route('/confirmation/<int:booking_id>')
def confirmation(booking_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute('''SELECT b.*, m.title, m.language, m.format,
                      t.theatre_name, s.show_date, s.show_time, s.price,
                      se.seat_number, p.payment_method, p.amount
                      FROM bookings b
                      JOIN shows s ON b.show_id=s.show_id
                      JOIN movies m ON s.movie_id=m.movie_id
                      JOIN theatres t ON s.theatre_id=t.theatre_id
                      JOIN seats se ON b.seat_id=se.seat_id
                      JOIN payments p ON p.booking_id=b.booking_id
                      WHERE b.booking_id=%s''', (booking_id,))
    booking = cursor.fetchone()
    cursor.close()
    db.close()
    return render_template('confirmation.html', booking=booking)

# ─── HISTORY ────────────────────────────────────────────

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute('''SELECT b.*, m.title, m.poster_url, m.language, m.format,
                      t.theatre_name, s.show_date, s.show_time,
                      se.seat_number, p.amount, p.payment_method
                      FROM bookings b
                      JOIN shows s ON b.show_id=s.show_id
                      JOIN movies m ON s.movie_id=m.movie_id
                      JOIN theatres t ON s.theatre_id=t.theatre_id
                      JOIN seats se ON b.seat_id=se.seat_id
                      LEFT JOIN payments p ON p.booking_id=b.booking_id
                      WHERE b.user_id=%s
                      ORDER BY b.booking_date DESC''', (session['user_id'],))
    bookings = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('history.html', bookings=bookings)
@app.route('/test-tmdb')
def test_tmdb():
    import requests
    r = requests.get('https://api.themoviedb.org/3/movie/now_playing', params={
        'api_key': '22ae35429832b54753cac0a4a4cdb861',
        'region': 'IN',
        'language': 'en-IN'
    })
    return str(r.json())
@app.route('/force-sync')
def force_sync():
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        response = requests.get(f'{TMDB_BASE}/movie/now_playing', params={
            'api_key': TMDB_API_KEY,
            'region': 'IN',
            'language': 'en-IN',
            'page': 1
        })
        data = response.json()
        count = 0
        errors = []
        for m in data.get('results', [])[:20]:
            try:
                cursor.execute('SELECT movie_id FROM movies WHERE title = %s', (m['title'],))
                if not cursor.fetchone():
                    lang = 'Hindi' if m.get('original_language') == 'hi' else \
                           'Telugu' if m.get('original_language') == 'te' else \
                           'Tamil' if m.get('original_language') == 'ta' else \
                           'Kannada' if m.get('original_language') == 'kn' else \
                           'Malayalam' if m.get('original_language') == 'ml' else 'English'
                    poster = TMDB_IMG + m['poster_path'] if m.get('poster_path') else None
                    cursor.execute('''INSERT INTO movies 
                        (title, genre, language, duration, rating, release_date, format, poster_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                        (m['title'], 'Drama', lang, 140,
                         round(m.get('vote_average', 7.0), 1),
                         m.get('release_date', str(date.today())),
                         '2D', poster))
                    count += 1
            except Exception as e:
                errors.append(f"{m['title']}: {str(e)}")
        db.commit()
        cursor.close()
        db.close()
        return f'✅ Done! {count} movies added. Errors: {errors}'
    except Exception as e:
        return f'❌ Failed: {str(e)}'
if __name__ == '__main__':
    app.run(debug=True)