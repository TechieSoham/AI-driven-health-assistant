from fastapi import FastAPI, Request, Form, File, UploadFile, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from starlette.middleware.sessions import SessionMiddleware
from mysql.connector import connect
from requests_oauthlib import OAuth1Session
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional
import io
import os
import socket

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Set the secret key from environment variables
app.add_middleware(SessionMiddleware, secret_key=os.getenv('SECRET_KEY'))

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up templates
templates = Jinja2Templates(directory="templates")

# Twitter OAuth credentials
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
TWITTER_CALLBACK_URL = 'http://localhost:5000/callback'  # Keep the original port for Twitter callback

# MySQL database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'port': 3306,
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}

# Helper function to connect to MySQL
def get_db_connection():
    return connect(**DB_CONFIG)

# Helper function to get session data
async def get_session(request: Request):
    return request.session

# Home route
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

# Doctor login route
@app.get("/doctor/login", response_class=HTMLResponse)
async def doctor_login(request: Request):
    return templates.TemplateResponse("doctor_login.html", {"request": request})

# Patient login route
@app.get("/patient/login", response_class=HTMLResponse)
async def patient_login(request: Request):
    return templates.TemplateResponse("patient_login.html", {"request": request})

# Start Twitter OAuth flow
@app.get("/login/{role}")
async def login(role: str, request: Request, session=Depends(get_session)):
    twitter = OAuth1Session(TWITTER_API_KEY, client_secret=TWITTER_API_SECRET, callback_uri=TWITTER_CALLBACK_URL)
    request_token_url = 'https://api.twitter.com/oauth/request_token'
    fetch_response = twitter.fetch_request_token(request_token_url)
    session['oauth_token'] = fetch_response.get('oauth_token')
    session['oauth_token_secret'] = fetch_response.get('oauth_token_secret')
    session['role'] = role
    auth_url = f"https://api.twitter.com/oauth/authorize?oauth_token={fetch_response.get('oauth_token')}"
    return RedirectResponse(auth_url)

# Callback route after Twitter authorization
@app.get("/callback")
async def callback(request: Request, session=Depends(get_session)):
    oauth_token = session.pop('oauth_token', None)
    oauth_token_secret = session.pop('oauth_token_secret', None)
    role = session.pop('role', None)
    
    if not oauth_token or not oauth_token_secret or not role:
        return RedirectResponse(url="/", status_code=303)

    # Set up Twitter OAuth session
    twitter = OAuth1Session(
        TWITTER_API_KEY,
        client_secret=TWITTER_API_SECRET,
        resource_owner_key=oauth_token,
        resource_owner_secret=oauth_token_secret,
        verifier=request.query_params.get('oauth_verifier')
    )
    
    try:
        # Get access token
        access_token_url = 'https://api.twitter.com/oauth/access_token'
        access_token_response = twitter.fetch_access_token(access_token_url)
        
        # Extract Twitter user data
        user_id = access_token_response.get('user_id')
        screen_name = access_token_response.get('screen_name')
        
        # Save user to database
        save_user_to_db(user_id, screen_name, role)
        
        # Set session data
        session['user_id'] = user_id
        session['role'] = role
        
        # Redirect based on role
        if role == 'doctor':
            return RedirectResponse(url="/doctor/dashboard", status_code=303)
        else:
            return RedirectResponse(url="/patient/dashboard", status_code=303)
            
    except Exception as e:
        return RedirectResponse(url="/", status_code=303)

# Save user data to MySQL
def save_user_to_db(user_id, screen_name, role):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, screen_name, role)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE screen_name = %s, role = %s
    ''', (user_id, screen_name, role, screen_name, role))
    conn.commit()
    cursor.close()
    conn.close()

# Doctor dashboard route
@app.get("/doctor/dashboard", response_class=HTMLResponse)
async def doctor_dashboard(request: Request, session=Depends(get_session)):
    if 'user_id' not in session or session['role'] != 'doctor':
        return RedirectResponse(url="/", status_code=303)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch doctor's name
    cursor.execute('SELECT screen_name FROM users WHERE user_id = %s', (session['user_id'],))
    doctor = cursor.fetchone()

    # Fetch appointments with patient profile picture for the doctor
    cursor.execute('''
        SELECT a.appointment_id, a.patient_id, a.appointment_date, u.profile_picture
        FROM appointments a
        LEFT JOIN users u ON a.patient_id = u.user_id
        WHERE a.doctor_id = %s
    ''', (session['user_id'],))
    
    appointments = cursor.fetchall()
    cursor.close()
    conn.close()

    return templates.TemplateResponse(
        "doctor_dashboard.html", 
        {"request": request, "doctor_name": doctor, "appointments": appointments}
    )

@app.get("/view_medical_records/{patient_id}/{appointment_id}", response_class=HTMLResponse)
async def view_medical_records(
    request: Request, 
    patient_id: int, 
    appointment_id: int, 
    session=Depends(get_session)
):
    if 'user_id' not in session or session['role'] != 'doctor':
        return RedirectResponse(url="/", status_code=303)
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get consent value from the appointment
    cursor.execute("SELECT isconsent FROM appointments WHERE appointment_id = %s", (appointment_id,))
    result = cursor.fetchone()

    if result and result['isconsent']:
        # Patient gave consent → fetch all records
        cursor.execute("SELECT * FROM medical_records WHERE patient_id = %s", (patient_id,))
    else:
        # No consent → fetch only general type records
        cursor.execute("SELECT * FROM medical_records WHERE patient_id = %s AND consent = 'general'", (patient_id,))

    medical_records = cursor.fetchall()

    cursor.close()
    conn.close()

    return templates.TemplateResponse(
        "view_medical_records.html", 
        {"request": request, "medical_records": medical_records}
    )

# Patient dashboard route
@app.get("/patient/dashboard", response_class=HTMLResponse)
async def patient_dashboard(request: Request, session=Depends(get_session)):
    if 'user_id' not in session or session['role'] != 'patient':
        return RedirectResponse(url="/", status_code=303)
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM users WHERE role = "doctor"')
    doctors = cursor.fetchall()
    cursor.execute('SELECT * FROM medical_records WHERE patient_id = %s', (session['user_id'],))
    medical_records = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return templates.TemplateResponse(
        "patient_dashboard.html", 
        {"request": request, "doctors": doctors, "medical_records": medical_records}
    )

@app.post("/toggle_consent/{record_id}")
async def toggle_consent(record_id: int, request: Request, session=Depends(get_session)):
    if 'user_id' not in session or session['role'] != 'patient':
        return RedirectResponse(url="/", status_code=303)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get current consent value
    cursor.execute('SELECT consent FROM medical_records WHERE record_id = %s AND patient_id = %s',
                   (record_id, session['user_id']))
    record = cursor.fetchone()

    if not record:
        return RedirectResponse(url="/patient/dashboard", status_code=303)

    new_consent = 'general' if record['consent'] == 'sensitive' else 'sensitive'

    # Update the consent
    cursor.execute('UPDATE medical_records SET consent = %s WHERE record_id = %s',
                   (new_consent, record_id))
    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(url="/patient/dashboard", status_code=303)

# Book appointment route
@app.post("/book_appointment")
async def book_appointment(
    request: Request,
    doctor_id: str = Form(...),
    appointment_date: str = Form(...),
    isconsent: Optional[str] = Form(default='false'),
    session=Depends(get_session)
):
    if 'user_id' not in session or session['role'] != 'patient':
        return RedirectResponse(url="/", status_code=303)

    isconsent_bool = isconsent.lower() == 'true'  # Convert to boolean

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO appointments (patient_id, doctor_id, appointment_date, isconsent)
        VALUES (%s, %s, %s, %s)
    ''', (session['user_id'], doctor_id, appointment_date, isconsent_bool))

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(url="/patient/dashboard", status_code=303)

@app.get("/add_medical_record_form/{patient_id}", response_class=HTMLResponse)
async def add_medical_record_form(patient_id: int, request: Request, session=Depends(get_session)):
    if 'user_id' not in session or session['role'] != 'doctor':
        return RedirectResponse(url="/", status_code=303)
        
    return templates.TemplateResponse(
        "add_medical_record.html", 
        {"request": request, "patient_id": patient_id}
    )

# Add medical record route (for doctors)
@app.post("/add_medical_record")
async def add_medical_record(
    request: Request,
    patient_id: str = Form(...),
    diagnosis: str = Form(...),
    prescription: str = Form(...),
    notes: str = Form(...),
    medical_image: UploadFile = File(None),
    x_ray_image: UploadFile = File(None),
    lab_report: UploadFile = File(None),
    session=Depends(get_session)
):
    if 'user_id' not in session or session['role'] != 'doctor':
        return RedirectResponse(url="/", status_code=303)

    # Ensure connection
    conn = get_db_connection()
    cursor = conn.cursor()

    # Read files only if uploaded
    medical_image_data = await medical_image.read() if medical_image else None
    x_ray_image_data = await x_ray_image.read() if x_ray_image else None
    lab_report_data = await lab_report.read() if lab_report else None

    # Insert into database
    cursor.execute('''
        INSERT INTO medical_records (patient_id, doctor_id, diagnosis, prescription, notes, image_data, x_ray_image, lab_report)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ''', (patient_id, session['user_id'], diagnosis, prescription, notes, medical_image_data, x_ray_image_data, lab_report_data))

    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(url="/doctor/dashboard", status_code=303)

@app.get("/medical_image/{image_type}/{record_id}")
async def get_medical_image(image_type: str, record_id: int):
    if image_type not in ['image_data', 'x_ray_image', 'lab_report', 'profile_picture']:
        raise HTTPException(status_code=400, detail="Invalid file type")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Using safer SQL query formatting
    query = f"SELECT {image_type} FROM medical_records WHERE record_id = %s"
    cursor.execute(query, (record_id,))
    
    image_data = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if image_data and image_data[0]:
        return Response(content=image_data[0], media_type='image/jpeg')
    raise HTTPException(status_code=404, detail="No file available")

@app.get("/profile_picture/{patient_id}")
async def get_profile_picture(patient_id: int):
    # Connect to the database
    conn = get_db_connection()
    cursor = conn.cursor()

    # Query to fetch the profile picture for the given patient_id
    cursor.execute('''
        SELECT profile_picture 
        FROM users 
        WHERE user_id = %s
    ''', (patient_id,))
    
    profile_picture = cursor.fetchone()

    cursor.close()
    conn.close()

    if profile_picture and profile_picture[0]:
        return Response(content=profile_picture[0], media_type='image/jpeg')
    raise HTTPException(status_code=404, detail="No image available")

@app.get("/download_medical_image/{record_id}")
async def download_medical_image(record_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT image_data FROM medical_records WHERE record_id = %s", (record_id,))
    image_data = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if image_data and image_data[0]:
        return StreamingResponse(
            io.BytesIO(image_data[0]),
            media_type='image/jpeg',
            headers={"Content-Disposition": f"attachment; filename=medical_record_{record_id}.jpg"}
        )
    raise HTTPException(status_code=404, detail="No image available")

# Logout route
@app.get("/logout")
async def logout(request: Request, session=Depends(get_session)):
    session.pop('user_id', None)
    session.pop('role', None)
    return RedirectResponse(url="/", status_code=303)

# Run the application
if __name__ == '__main__':
    import uvicorn
    
    # Get the local IP address of the machine
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    print("\n🚀 FastAPI app running!")
    print(f"👉 Local:    http://127.0.0.1:5000")
    print(f"👉 Network:  http://{local_ip}:5000\n")
    
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)