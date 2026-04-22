from fastapi import FastAPI, Request, Form, Depends, Response, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, Integer, String, create_engine, DateTime, Float, ForeignKey, Table, or_
from datetime import datetime
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
import shutil
import os

DATABASE_URL = "sqlite:////tmp/users.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

song_collaborators = Table(
    'song_collaborators',
    Base.metadata,
    Column('song_id', Integer, ForeignKey('songs.id')),
    Column('user_id', Integer, ForeignKey('users.id'))
)

user_follows = Table(
    'user_follows', Base.metadata,
    Column('fan_id', Integer, ForeignKey('users.id')),
    Column('artist_id', Integer, ForeignKey('users.id'))
)

# Tabellen-Klassen
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    email = Column(String, unique=True)
    password = Column(String)
    role = Column(String, default="fan") # fan, artist
    
    # --- Profil-Personalisierung ---
    bio = Column(String, default="Noch keine Beschreibung vorhanden.")
    profile_pic = Column(String, nullable=True)
    banner_pic = Column(String, nullable=True)
    accent_color = Column(String, default="#243D32") # Der Artist bestimmt seine Farbe
    
    owned_songs = relationship("Song", back_populates="owner")
    # --- Socials ---
    spotify_link = Column(String, nullable=True)
    instagram_link = Column(String, nullable=True)
    whatsapp_link = Column(String, nullable=True)

    # Relationships
    # Gefolgte Künstler eines Fans
    following = relationship(
        "User", 
        secondary=user_follows,
        primaryjoin=(id == user_follows.c.fan_id),
        secondaryjoin=(id == user_follows.c.artist_id),
        backref="followers"
    )

class Song(Base):
    __tablename__ = "songs"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    artist = Column(String) # Anzeigename (Text)
    genre = Column(String)
    
    isrc = Column(String, unique=True, index=True, nullable=True)
    spotify_id = Column(String, nullable=True)
    spotify_url = Column(String)
    
    goal_streams = Column(Integer)
    current_streams = Column(Integer, default=0)
    
    last_sync = Column(DateTime, default=datetime.utcnow)
    cover_path = Column(String)
    reward_path = Column(String)
    
    # Der Haupt-Besitzer
    user_id = Column(Integer, ForeignKey('users.id'))
    owner = relationship("User", back_populates="owned_songs")
    
    # --- NEU: Die Kooperations-Partner (Features) ---
    collaborators = relationship("User", secondary=song_collaborators, backref="featured_on")

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    recipient_id = Column(Integer, ForeignKey('users.id'))
    sender_id = Column(Integer, ForeignKey('users.id'))
    song_id = Column(Integer, ForeignKey('songs.id'))
    message = Column(String)
    type = Column(String) # z.B. "collab_request"
    is_read = Column(Integer, default=0) # 0=ungelesen, 1=gelesen
    created_at = Column(DateTime, default=datetime.utcnow)

    # Verknüpfungen für einfachen Zugriff im Template
    song = relationship("Song")
    sender = relationship("User", foreign_keys=[sender_id])

Base.metadata.create_all(bind=engine)

# 2. FastAPI Setup (WICHTIG: app ZUERST definieren)
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# JETZT kann gemountet werden, da "app" existiert
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates Setup
templates = Jinja2Templates(directory="templates")

# Hilfsfunktionen
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_current_user(request: Request, db: Session):
    user_id = request.cookies.get("user_id")
    if user_id:
        return db.query(User).filter(User.id == int(user_id)).first()
    return None

import smtplib
from email.mime.text import MIMEText

def send_verification_email(email: str, token: str):
    verification_url = f"http://127.0.0.1:8000/verify/{token}"
    
    msg = MIMEText(f"Willkommen! Bitte bestätige deine E-Mail hier: {verification_url}")
    msg['Subject'] = "Bestätige deinen Source-Account"
    msg['From'] = "noreply@source-app.de"
    msg['To'] = email

    # Beispiel mit einem fiktiven SMTP (Nutze Mailtrap.io für lokales Testen!)
    try:
        with smtplib.SMTP("smtp.mailtrap.io", 2525) as server:
            server.login("DEIN_USER", "DEIN_PASSWORT")
            server.sendmail(msg['From'], [msg['To']], msg.as_string())
    except Exception as e:
        print(f"Fehler beim Mail-Versand: {e}")

# 3. Routen
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    all_database_songs = db.query(Song).all()
    
    genres = ["HipHop", "Rap", "Schlager", "Pop", "Rock", "Techno", "Indie"]
    explore_data = {}

    notifications = []
    if user:
            notifications = db.query(Notification).filter(
                Notification.recipient_id == user.id, 
                Notification.is_read == 0
            ).all()

    all_database_songs = db.query(Song).all()

    for g in genres:
        songs = db.query(Song).filter(Song.genre.ilike(f"%{g.strip()}%")).limit(8).all()
        if songs:
            explore_data[g] = songs

    if not explore_data and all_database_songs:
        explore_data["Entdecken"] = all_database_songs

    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "user": user, 
            "explore_data": explore_data,
            "notifications": notifications  # <--- DAS HIER MUSS REIN
        }
    )

@app.get("/about")
async def about_page(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="about.html"
    )

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/auth")
async def handle_auth(
    email: str = Form(...), 
    password: str = Form(...), 
    username: str = Form(None), 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email, User.password == password).first()
    
    if username:  # Registrierung
        new_user = User(username=username, email=email, password=password, role="fan")
        db.add(new_user)
        db.commit()
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(key="user_id", value=str(new_user.id), httponly=True)
        return response

    if user:  # Login
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(key="user_id", value=str(user.id), httponly=True)
        return response
    
    return RedirectResponse(url="/login", status_code=303)

@app.get("/dashboard")
async def show_dashboard(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # NEU: Zeige Songs an, die dem User gehören ODER wo er als Collaborator eingetragen ist
    user_songs = db.query(Song).filter(
        or_(Song.user_id == user.id, Song.collaborators.any(id=user.id))
    ).all()
    
    active_goals = len(user_songs)
    
    return templates.TemplateResponse(
        request=request, name="dashboard.html", 
        context={"user": user, "songs": user_songs, "active_goals": active_goals}
    )

@app.get("/song/{song_id}")
async def song_detail(song_id: int, request: Request, db: Session = Depends(get_db)):
    song = db.query(Song).filter(Song.id == song_id).first()
    if not song:
        return "Song nicht gefunden", 404

    # Den aktuell eingeloggten User holen
    user = await get_current_user(request, db)

    # Wichtig: Die Variablen für das Template berechnen
    progress = (song.current_streams / song.goal_streams * 100) if song.goal_streams > 0 else 0
    is_unlocked = song.current_streams >= song.goal_streams

    return templates.TemplateResponse(
        request=request,
        name="song_detail.html",
        context={
            "song": song,
            "user": user, # Das hier ermöglicht die Prüfung im HTML
            "progress": progress,
            "is_unlocked": is_unlocked
        }
    )

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="user_id")
    return response

# --- Künstler Routen ---

@app.get("/artist-verification", response_class=HTMLResponse)
async def show_verification_page(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse(
    request=request, 
    name="artist-verification.html", 
    context={"user": user}
    )   

@app.post("/verify-request")
async def handle_verification(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    if user:
        user.role = "pending_artist"
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/create-song-goal")
async def create_song_page(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user or user.role != "artist":
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request, 
        name="create_song.html", 
        context={"user": user}
)

@app.post("/submit-song")
async def handle_song_submit(
    request: Request,
    title: str = Form(...),
    artist: str = Form(...),
    genre: str = Form(...),
    isrc: str = Form(None),
    spotify_url: str = Form(...),
    goal_streams: int = Form(...),
    cover: UploadFile = File(...),
    reward_content: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user or user.role != "artist":
        return RedirectResponse(url="/dashboard", status_code=303)

    os.makedirs("static/uploads", exist_ok=True)
    cover_path = f"static/uploads/{cover.filename}"
    reward_path = f"static/uploads/{reward_content.filename}"
    
    with open(cover_path, "wb") as buffer:
        shutil.copyfileobj(cover.file, buffer)
    with open(reward_path, "wb") as buffer:
        shutil.copyfileobj(reward_content.file, buffer)

    new_song = Song(
        title=title, artist=artist, genre=genre, 
        isrc=isrc, spotify_url=spotify_url, 
        goal_streams=goal_streams, cover_path=cover_path, 
        reward_path=reward_path, user_id=user.id
    )
    db.add(new_song)
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/invite-collaborator/{song_id}")
async def invite_artist(song_id: int, artist_name: str = Form(...), db: Session = Depends(get_db), request: Request = None):
    user = await get_current_user(request, db) # Der Absender
    invited_user = db.query(User).filter(User.username == artist_name, User.role == "artist").first()
    song = db.query(Song).filter(Song.id == song_id).first()

    if invited_user and song:
        # Benachrichtigung erstellen
        new_notif = Notification(
            recipient_id=invited_user.id,
            sender_id=user.id,
            song_id=song_id,
            message=f"{user.username} möchte dich als Partner für '{song.title}' einladen.",
            type="collab_request"
        )
        db.add(new_notif)
        db.commit()
    return RedirectResponse(url=f"/edit-song/{song_id}", status_code=303)

@app.get("/artist/{username}")
async def artist_profile(username: str, request: Request, db: Session = Depends(get_db)):
    artist = db.query(User).filter(User.username == username, User.role == "artist").first()
    if not artist:
        return "Künstler nicht gefunden", 404
    
    user = await get_current_user(request, db)
    # Alle Songs dieses Künstlers (Inhaber oder Collaborator)
    songs = db.query(Song).filter(or_(Song.user_id == artist.id, Song.collaborators.any(id=artist.id))).all()
    
    # Prüfen ob der eingeloggte User diesen Artist bereits liked
    is_following = user in artist.followers if user else False

    return templates.TemplateResponse(
    request=request, 
    name="artist_profile.html", 
    context={
        "artist": artist, 
        "user": user, 
        "songs": songs, 
        "is_following": is_following
    }
)

# Artist Liken/Folgen
@app.post("/like-artist/{artist_id}")
async def like_artist(artist_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user: return RedirectResponse(url="/login", status_code=303)
    
    artist = db.query(User).filter(User.id == artist_id).first()
    if artist and user not in artist.followers:
        artist.followers.append(user)
        db.commit()
    return RedirectResponse(url=f"/artist/{artist.username}", status_code=303)

# Suche erweitern (Songs UND Artists)
@app.get("/api/search")
async def search(q: str, db: Session = Depends(get_db)):
    songs = db.query(Song).filter(Song.title.ilike(f"%{q}%")).limit(5).all()
    artists = db.query(User).filter(User.username.ilike(f"%{q}%"), User.role == "artist").limit(5).all()
    
    results = []
    for s in songs:
        results.append({"type": "song", "id": s.id, "title": s.title, "artist": s.artist, "cover": s.cover_path})
    for a in artists:
        results.append({"type": "artist", "id": a.id, "title": a.username, "artist": "Künstler", "cover": a.profile_pic or "static/default_avatar.png"})
    return results

@app.get("/settings")
async def settings_page(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user: return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
    request=request, 
    name="settings.html", 
    context={"user": user}
)

@app.post("/update-settings")
async def update_settings(
    request: Request,
    bio: str = Form(None),
    spotify: str = Form(None),
    whatsapp: str = Form(None),
    instagram: str = Form(None),
    accent_color: str = Form("#243D32"),
    profile_pic: UploadFile = File(None),
    banner_pic: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user: return RedirectResponse(url="/login", status_code=303)

    # Texte & Farben speichern
    user.bio = bio
    user.spotify_link = spotify
    user.whatsapp_link = whatsapp
    user.instagram_link = instagram
    user.accent_color = accent_color

    # Bilder verarbeiten
    os.makedirs("static/uploads/profiles", exist_ok=True)
    
    if profile_pic and profile_pic.filename:
        path = f"static/uploads/profiles/p_{user.id}_{profile_pic.filename}"
        with open(path, "wb") as buffer:
            shutil.copyfileobj(profile_pic.file, buffer)
        user.profile_pic = path

    if banner_pic and banner_pic.filename:
        path = f"static/uploads/profiles/b_{user.id}_{banner_pic.filename}"
        with open(path, "wb") as buffer:
            shutil.copyfileobj(banner_pic.file, buffer)
        user.banner_pic = path

    db.commit()
    return RedirectResponse(url=f"/artist/{user.username}", status_code=303)

#fake
@app.get("/make-me-artist")
async def make_me_artist(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    if user:
        user.role = "artist" # Hier setzen wir dich manuell auf Artist
        db.commit()
        return f"Erfolg! {user.username} ist jetzt ein verifizierter Künstler. Geh zurück zum /dashboard"
    return "Fehler: Du bist nicht eingeloggt."

@app.get("/api/search")
async def search_songs(q: str, db: Session = Depends(get_db)):
    # Suche in Titel oder Künstler (case-insensitive)
    songs = db.query(Song).filter(
        (Song.title.ilike(f"%{q}%")) | (Song.artist.ilike(f"%{q}%"))
    ).limit(5).all()
    
    # Wir geben nur die nötigsten Daten als Liste von Dicts zurück
    return [
        {
            "id": s.id, 
            "title": s.title, 
            "artist": s.artist, 
            "cover_path": s.cover_path
        } for s in songs
    ]

# --- EDIT SONG GET (Formular anzeigen) ---
@app.get("/edit-song/{song_id}")
async def edit_song_form(song_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    song = db.query(Song).filter(Song.id == song_id, Song.user_id == user.id).first()
    if not song:
        return "Song nicht gefunden oder keine Berechtigung", 404
        
    return templates.TemplateResponse(
    request=request, 
    name="edit_song.html", 
    context={
        "song": song,
        "user": user
    }
    )

@app.post("/edit-song/{song_id}")
async def update_song(
    song_id: int,
    request: Request,
    title: str = Form(...),
    artist: str = Form(...),
    genre: str = Form(...),
    isrc: str = Form(None), # NEU
    goal_streams: int = Form(...),
    spotify_url: str = Form(...),
    db: Session = Depends(get_db)
):
    user = await get_current_user(request, db)
    song = db.query(Song).filter(Song.id == song_id, Song.user_id == user.id).first()
    
    if song:
        song.title = title
        song.artist = artist
        song.genre = genre
        song.isrc = isrc # NEU
        song.goal_streams = goal_streams
        song.spotify_url = spotify_url
        db.commit()
    
    return RedirectResponse(url=f"/song/{song_id}", status_code=303)

@app.post("/invite-collaborator/{song_id}")
async def invite_artist(
    song_id: int, 
    artist_name: str = Form(...), 
    db: Session = Depends(get_db),
    request: Request = None
):
    # 1. Den eingeladenen Nutzer suchen
    invited_user = db.query(User).filter(User.username == artist_name).first()
    
    # 2. Check: Existiert er und ist er wirklich ein Künstler?
    if not invited_user or invited_user.role != "artist":
        # Hier könntest du eine Fehlermeldung ans Frontend senden
        return RedirectResponse(url=f"/edit-song/{song_id}?error=not_an_artist", status_code=303)

    # 3. Zum Song hinzufügen
    song = db.query(Song).filter(Song.id == song_id).first()
    if invited_user not in song.collaborators:
        song.collaborators.append(invited_user)
        db.commit()
    
    return RedirectResponse(url=f"/edit-song/{song_id}", status_code=303)

@app.post("/accept-collab/{notif_id}")
async def accept_collab(notif_id: int, db: Session = Depends(get_db)):
    notif = db.query(Notification).filter(Notification.id == notif_id).first()
    if notif:
        song = db.query(Song).filter(Song.id == notif.song_id).first()
        user = db.query(User).filter(User.id == notif.recipient_id).first()
        
        if song and user and user not in song.collaborators:
            song.collaborators.append(user)
            db.delete(notif) # Anfrage erledigt
            db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)

# Dieser Endpunkt ist nur für dich zum Testen da!
@app.get("/make-me-artist")
async def make_me_artist(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user(request, db)
    if user:
        user.role = "artist" # Hier ändern wir deine Rolle in der Datenbank
        db.commit()
        return f"Erfolg! {user.username} ist jetzt ein verifizierter Künstler. Geh zurück zum /dashboard"
    return "Fehler: Du bist nicht eingeloggt."

if __name__ == "__main__":
    import uvicorn
    import os
    # Render gibt uns den Port über die Umgebungsvariable 'PORT'
    port = int(os.environ.get("PORT", 8000))
    # Wir binden an 0.0.0.0, um Anfragen aus dem Internet zu erlauben
    uvicorn.run(app, host="0.0.0.0", port=port)
