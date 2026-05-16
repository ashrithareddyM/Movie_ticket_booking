USE movie_booking;

-- All users
SELECT * FROM users;

-- All movies
SELECT * FROM movies;

-- All bookings with details
SELECT u.name, m.title, t.theatre_name, s.show_date, 
       s.show_time, se.seat_number, b.status, p.amount
FROM bookings b
JOIN users u ON b.user_id = u.user_id
JOIN shows s ON b.show_id = s.show_id
JOIN movies m ON s.movie_id = m.movie_id
JOIN theatres t ON s.theatre_id = t.theatre_id
JOIN seats se ON b.seat_id = se.seat_id
LEFT JOIN payments p ON p.booking_id = b.booking_id;

-- All payments
SELECT * FROM payments;