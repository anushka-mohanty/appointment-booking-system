from flask import Flask, render_template, request, redirect, url_for, session, flash
from db import get_db

app = Flask(__name__)
app.secret_key = 'medbook_secret_123'  # needed for session & flash to work


# ─────────────────────────────────────────────
# HOME PAGE — lists all professionals
# ─────────────────────────────────────────────
@app.route('/')
def index():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Professionals")
    professionals = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('index.html', professionals=professionals)


# ─────────────────────────────────────────────
# LOGIN — simple login by UserID (no password for now)
# ─────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form['user_id']
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Users WHERE UserID = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user:
            session['user_id'] = user['UserID']
            session['user_name'] = user['Name']
            session['user_role'] = user['Role']
            flash(f"Welcome, {user['Name']}!")
            return redirect(url_for('index'))
        else:
            flash("User not found. Please check your User ID.")
            return redirect(url_for('login'))

    return render_template('login.html')


# ─────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('index'))


# ─────────────────────────────────────────────
# BOOK APPOINTMENT — shows slots for a professional
# ─────────────────────────────────────────────
@app.route('/book/<int:prof_id>', methods=['GET', 'POST'])
def book(prof_id):
    # Must be logged in to book
    if 'user_id' not in session:
        flash("Please log in to book an appointment.")
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':
        slot_id = request.form['slot_id']
        user_id = session['user_id']

        try:
            # Call the stored procedure BookAppointment
            cursor.callproc('BookAppointment', [user_id, slot_id])
            db.commit()
            flash("Appointment booked successfully!")
            return redirect(url_for('my_bookings'))

        except Exception as e:
            db.rollback()
            # The trigger or procedure will raise an error if slot is taken
            flash(f"Booking failed: {str(e)}")
            return redirect(url_for('book', prof_id=prof_id))

        finally:
            cursor.close()
            db.close()

    # GET request — fetch available slots for this professional
    cursor.execute("""
        SELECT s.SlotID, s.Date, s.StartTime, s.EndTime,
               p.Name AS DoctorName, p.Specialization, p.ServiceFee
        FROM Availability_Slots s
        JOIN Professionals p ON s.ProfID = p.ProfID
        WHERE s.ProfID = %s AND s.IsAvailable = TRUE
        ORDER BY s.Date, s.StartTime
    """, (prof_id,))
    slots = cursor.fetchall()

    cursor.execute("SELECT * FROM Professionals WHERE ProfID = %s", (prof_id,))
    professional = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template('book.html', slots=slots, professional=professional)


# ─────────────────────────────────────────────
# MY BOOKINGS — logged-in user's bookings
# ─────────────────────────────────────────────
@app.route('/my-bookings')
def my_bookings():
    if 'user_id' not in session:
        flash("Please log in to view your bookings.")
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT b.BookingID, b.Status, b.PaymentStatus,
               s.Date, s.StartTime, s.EndTime,
               p.Name AS DoctorName, p.Specialization, p.ServiceFee,
               r.Rating, r.Comment
        FROM Bookings b
        JOIN Availability_Slots s ON b.SlotID = s.SlotID
        JOIN Professionals p ON s.ProfID = p.ProfID
        LEFT JOIN Reviews r ON r.BookingID = b.BookingID
        WHERE b.UserID = %s
        ORDER BY s.Date DESC
    """, (session['user_id'],))
    bookings = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('my_bookings.html', bookings=bookings)


# ─────────────────────────────────────────────
# CANCEL BOOKING — calls CancelBooking procedure
# ─────────────────────────────────────────────
@app.route('/cancel/<int:booking_id>')
def cancel(booking_id):
    if 'user_id' not in session:
        flash("Please log in.")
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.callproc('CancelBooking', [booking_id])
        db.commit()
        flash("Booking cancelled successfully.")
    except Exception as e:
        db.rollback()
        flash(f"Cancellation failed: {str(e)}")
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('my_bookings'))


# ─────────────────────────────────────────────
# SUBMIT REVIEW — for a completed booking
# ─────────────────────────────────────────────
@app.route('/review/<int:booking_id>', methods=['GET', 'POST'])
def review(booking_id):
    if 'user_id' not in session:
        flash("Please log in.")
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':
        rating = request.form['rating']
        comment = request.form['comment']

        cursor.execute("""
            INSERT INTO Reviews (BookingID, Rating, Comment, ReviewDate)
            VALUES (%s, %s, %s, CURDATE())
        """, (booking_id, rating, comment))
        db.commit()
        cursor.close()
        db.close()
        flash("Review submitted. Thank you!")
        return redirect(url_for('my_bookings'))

    # GET — show the review form, pre-load booking info
    cursor.execute("""
        SELECT b.BookingID, p.Name AS DoctorName, s.Date
        FROM Bookings b
        JOIN Availability_Slots s ON b.SlotID = s.SlotID
        JOIN Professionals p ON s.ProfID = p.ProfID
        WHERE b.BookingID = %s
    """, (booking_id,))
    booking = cursor.fetchone()
    cursor.close()
    db.close()

    return render_template('review.html', booking=booking)


# ─────────────────────────────────────────────
# ADMIN DASHBOARD — full overview + advanced queries
# ─────────────────────────────────────────────
@app.route('/admin')
def admin():
    if session.get('user_role') != 'Admin':
        flash("Access denied. Admins only.")
        return redirect(url_for('index'))

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # All bookings with full details
    cursor.execute("""
        SELECT b.BookingID, u.Name AS UserName, p.Name AS DoctorName,
               p.Specialization, s.Date, s.StartTime,
               b.Status, b.PaymentStatus
        FROM Bookings b
        JOIN Users u ON b.UserID = u.UserID
        JOIN Availability_Slots s ON b.SlotID = s.SlotID
        JOIN Professionals p ON s.ProfID = p.ProfID
        ORDER BY s.Date DESC
    """)
    all_bookings = cursor.fetchall()

    # Nested query — professionals with NO bookings this week
    cursor.execute("""
        SELECT Name FROM Professionals
        WHERE ProfID NOT IN (
            SELECT DISTINCT p.ProfID
            FROM Bookings b
            JOIN Availability_Slots s ON b.SlotID = s.SlotID
            JOIN Professionals p ON s.ProfID = p.ProfID
            WHERE s.Date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY)
        )
    """)
    idle_professionals = cursor.fetchall()

    # Correlated query — professionals earning above average in their specialization
    cursor.execute("""
        SELECT p1.Name, p1.Specialization,
            (SELECT COALESCE(SUM(p2.ServiceFee), 0)
             FROM Bookings b
             JOIN Availability_Slots s ON b.SlotID = s.SlotID
             JOIN Professionals p2 ON s.ProfID = p2.ProfID
             WHERE p2.ProfID = p1.ProfID) AS TotalRevenue
        FROM Professionals p1
        WHERE (
            SELECT COALESCE(SUM(p2.ServiceFee), 0)
            FROM Bookings b
            JOIN Availability_Slots s ON b.SlotID = s.SlotID
            JOIN Professionals p2 ON s.ProfID = p2.ProfID
            WHERE p2.ProfID = p1.ProfID
        ) > (
            SELECT AVG(p3.ServiceFee)
            FROM Professionals p3
            WHERE p3.Specialization = p1.Specialization
        )
    """)
    top_earners = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template('admin.html',
                           all_bookings=all_bookings,
                           idle_professionals=idle_professionals,
                           top_earners=top_earners)


# ─────────────────────────────────────────────
# GENERATE SLOTS — admin triggers slot generation
# ─────────────────────────────────────────────
@app.route('/admin/generate-slots', methods=['POST'])
def generate_slots():
    if session.get('user_role') != 'Admin':
        flash("Access denied.")
        return redirect(url_for('index'))

    prof_id = request.form['prof_id']
    slot_date = request.form['slot_date']

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.callproc('GenerateDailySlots', [prof_id, slot_date])
        db.commit()
        flash(f"Slots generated for Professional ID {prof_id} on {slot_date}.")
    except Exception as e:
        db.rollback()
        flash(f"Error generating slots: {str(e)}")
    finally:
        cursor.close()
        db.close()

    return redirect(url_for('admin'))


# ─────────────────────────────────────────────
# RUN THE APP
# ─────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True)