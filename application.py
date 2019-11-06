import os
import requests
from flask import Flask, session, request, render_template, redirect, url_for, jsonify
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import login_required

app = Flask(__name__)

# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
engine = create_engine(os.getenv("DATABASE_URL"), echo=True)
db = scoped_session(sessionmaker(bind=engine))

# Set up API
API_KEY = "5gLUrFuiEtUtGBkFF0ihuw"


@app.route("/")
def index():
    return render_template("search.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    else:
        username = request.form.get('username')
        email = request.form.get('email')

        if not username:
            return render_template("register.html", message="Must enter username")
        if not email:
            return render_template("register.html", message="Must enter email")
        if not request.form.get('password'):
            return render_template("register.html", message="Must enter password")
        if request.form.get('password') != request.form.get('confirmation'):
            return render_template("register.html", message="Password and Confirmation don't match")

        if db.execute("SELECT * FROM users WHERE username=:username", {'username': username}).fetchone():
            return render_template("register.html", message="Username already taken")
        else:
            db.execute("INSERT INTO users(user_id, username, email, hash) VALUES (default, :username, :email, :hash)",
                       {'username': username, 'email': email, 'hash': generate_password_hash(request.form.get('password'))})
            db.commit()
            query = db.execute("SELECT user_id FROM users WHERE username=:username", {'username': username}).fetchone()
            session['user_id'] = query['user_id']

        return redirect("/")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    else:
        username = request.form.get('username')
        if not username:
            return render_template("login.html", message="Must provide username")
        # Ensure password was submitted
        elif not request.form.get("password"):
            return render_template("login.html", message="Must provide password")

        row = db.execute("SELECT * FROM users WHERE username = :username",
                         {'username': username}).fetchone()

        if not row:
            return render_template("login.html", message="Invalid username and/or password")
        else:
            if not check_password_hash(row['hash'], request.form.get('password')):
                return render_template("login.html", message="Invalid username and/or password")
            session['user_id'] = row['user_id']

        return redirect("/")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    return render_template("login.html", message="You have logged out!")


@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    if request.method == "GET":
        return render_template("search.html")
    else:
        search = request.form.get('search').capitalize()
        search = "%" + search + "%"
        results = db.execute("SELECT * FROM books WHERE title LIKE :search OR isbn LIKE :search OR author LIKE :search",
                             {"search": search}).fetchall()
        message = ""
        if results is None:
            message = "No Books Found."
        else:
            count = str(len(results))
            message = "Your search returned " + count + " result(s)."
        return render_template("/search.html", results=results, message=message)


@app.route("/search/<string:isbn>", methods=["GET", "POST"])
@login_required
def book(isbn):
    if request.method == "GET":
        book = db.execute("SELECT * FROM books WHERE isbn=:isbn",
                          {"isbn": isbn}).fetchone()

        if book is None:
            return render_template("error.html", message="No such book.")

        average = db.execute("SELECT ROUND(AVG(rating), 2) as avg FROM reviews WHERE isbn=:isbn",
                             {"isbn": isbn}).fetchone()

        if average['avg'] is None:
            average = 0.00
        else:
            average = average['avg']

        reviews = db.execute("SELECT username, reviews.user_id, review_text, rating, created_at FROM reviews JOIN users ON users.user_id=reviews.user_id WHERE isbn=:isbn ORDER BY created_at DESC",
                             {"isbn": isbn}).fetchall()

        reviewed = False
        for review in reviews:
            if review['user_id'] == session['user_id']:
                reviewed = True

        goodreads = requests.get("https://www.goodreads.com/book/review_counts.json", params={"key": API_KEY, "isbns": isbn})
        if goodreads:
            goodreads = goodreads.json()
            goodreads = goodreads['books'][0]

        return render_template("/book.html", book=book, reviews=reviews, reviewed=reviewed, average=average, goodreads=goodreads)
    else:
        review_text = request.form.get('review')
        rating = request.form.get('rating')

        if not review_text:
            return render_template("/error.html", message="Must provide text for review.")
        if not rating:
            return render_template("/error.html", message="Must provide a rating.")

        db.execute("INSERT INTO reviews(isbn, user_id, review_text, created_at, rating) VALUES (:isbn, :user_id, :review_text, default, :rating)",
                   {'isbn': isbn, 'user_id': session['user_id'], 'review_text': review_text, 'rating': rating})
        db.commit()

        return redirect(url_for('book', isbn=isbn))


@app.route("/api/<string:isbn>", methods=["GET", "POST"])
@login_required
def api(isbn):
    if request.method == "GET":
        result = db.execute("SELECT title, author, year, books.isbn FROM reviews JOIN books ON reviews.isbn=books.isbn WHERE books.isbn=:isbn",
                            {"isbn": isbn}).fetchone()
        average = db.execute("SELECT ROUND(AVG(rating), 2) as avg FROM reviews JOIN books ON reviews.isbn=books.isbn WHERE books.isbn=:isbn",
                             {"isbn": isbn}).fetchone()
        review_count = db.execute("SELECT COUNT(reviews.isbn) as count FROM reviews JOIN books ON reviews.isbn=books.isbn WHERE books.isbn=:isbn",
                                  {"isbn": isbn}).fetchone()
        if result is None:
            return jsonify({"error": "No such ISBN"}), 404

        goodreads = jsonify({
                "title": result["title"],
                "author": result["author"],
                "year": result["year"],
                "isbn": result["isbn"],
                "review_count": int(review_count["count"]),
                "average_score": float(average["avg"])
        })
        return goodreads
