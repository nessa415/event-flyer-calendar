import os
import uuid
import re
import cv2
import pytesseract
import dateutil.parser
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-for-testing')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///event_flyer.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize database
db = SQLAlchemy(app)

# Google Calendar API settings
SCOPES = ['https://www.googleapis.com/auth/calendar']
CLIENT_CONFIG = {
    'web': {
        'client_id': os.environ.get('GOOGLE_CLIENT_ID', ''),
        'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET', ''),
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'redirect_uris': []  # Will be set dynamically
    }
}

# Define Event model
class Event(db.Model):
    """Model for storing event information extracted from flyers."""
    
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(255), nullable=False)
    raw_text = db.Column(db.Text, nullable=True)
    
    event_name = db.Column(db.String(255), nullable=True)
    event_location = db.Column(db.String(255), nullable=True)
    event_date = db.Column(db.Date, nullable=True)
    event_time = db.Column(db.String(100), nullable=True)
    event_description = db.Column(db.Text, nullable=True)
    event_hosts = db.Column(db.String(255), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    google_event_id = db.Column(db.String(255), nullable=True)
    
    def to_dict(self):
        """Convert event to dictionary."""
        return {
            'id': self.id,
            'image_path': self.image_path,
            'event_name': self.event_name,
            'event_location': self.event_location,
            'event_date': self.event_date.strftime('%Y-%m-%d') if self.event_date else None,
            'event_time': self.event_time,
            'event_description': self.event_description,
            'event_hosts': self.event_hosts,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'google_event_id': self.google_event_id
        }

# OCR Processor class
class OCRProcessor:
    """Class for processing images with OCR and extracting event information."""
    
    def __init__(self, image_path):
        """Initialize with the path to the image."""
        self.image_path = image_path
        self.raw_text = None
        self.extracted_info = {
            'event_name': None,
            'event_location': None,
            'event_date': None,
            'event_time': None,
            'event_description': None,
            'event_hosts': None
        }
    
    def preprocess_image(self):
        """Preprocess the image to improve OCR results."""
        # Read the image
        image = cv2.imread(self.image_path)
        
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply threshold to get image with only black and white pixels
        _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        
        # Save the preprocessed image temporarily
        temp_path = f"{os.path.splitext(self.image_path)[0]}_processed.png"
        cv2.imwrite(temp_path, binary)
        
        return temp_path
    
    def extract_text(self):
        """Extract text from the image using OCR."""
        # Preprocess the image
        processed_image_path = self.preprocess_image()
        
        # Extract text using pytesseract
        self.raw_text = pytesseract.image_to_string(processed_image_path)
        
        # Clean up temporary file
        if os.path.exists(processed_image_path):
            os.remove(processed_image_path)
        
        return self.raw_text
    
    def extract_event_info(self):
        """Extract event information from the OCR text."""
        if not self.raw_text:
            self.extract_text()
        
        # Extract event name (usually prominent text at the beginning)
        lines = self.raw_text.split('\n')
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        
        if non_empty_lines:
            # Assume the first non-empty line with more than 3 words is the event name
            for line in non_empty_lines:
                if len(line.split()) > 2 and len(line) > 10:
                    self.extracted_info['event_name'] = line
                    break
            
            # If no suitable line found, use the first non-empty line
            if not self.extracted_info['event_name'] and non_empty_lines:
                self.extracted_info['event_name'] = non_empty_lines[0]
        
        # Extract date using regex patterns
        date_patterns = [
            r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b',
            r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
            r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?\b'
        ]
        
        for pattern in date_patterns:
            date_matches = re.findall(pattern, self.raw_text, re.IGNORECASE)
            if date_matches:
                self.extracted_info['event_date'] = date_matches[0]
                break
        
        # Extract time using regex
        time_patterns = [
            r'\b(?:\d{1,2}:\d{2})\s*(?:am|pm|AM|PM)\b',
            r'\b(?:\d{1,2})\s*(?:am|pm|AM|PM)\b',
            r'\b(?:\d{1,2}:\d{2})\s*(?:-|to|–)\s*(?:\d{1,2}:\d{2})\s*(?:am|pm|AM|PM)\b',
            r'\b(?:\d{1,2})\s*(?:am|pm|AM|PM)\s*(?:-|to|–)\s*(?:\d{1,2})\s*(?:am|pm|AM|PM)\b'
        ]
        
        for pattern in time_patterns:
            time_matches = re.findall(pattern, self.raw_text, re.IGNORECASE)
            if time_matches:
                self.extracted_info['event_time'] = time_matches[0]
                break
        
        # Extract location (look for address patterns or location keywords)
        location_patterns = [
            r'\b\d+\s+[A-Za-z0-9\s,]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Plaza|Plz|Square|Sq|Highway|Hwy|Broadway|Parkway|Pkwy)\b',
            r'\b(?:at|@)\s+([A-Za-z0-9\s&]+(?:Club|Venue|Bar|Lounge|Hall|Center|Theatre|Theater|Arena|Stadium|Gallery|Museum|Cafe|Restaurant))\b'
        ]
        
        for pattern in location_patterns:
            location_matches = re.findall(pattern, self.raw_text, re.IGNORECASE)
            if location_matches:
                self.extracted_info['event_location'] = location_matches[0]
                break
        
        # Extract hosts/DJs (look for DJ, presented by, featuring, etc.)
        host_patterns = [
            r'\bDJ\s+([A-Za-z0-9\s&]+)\b',
            r'\bfeaturing\s+([A-Za-z0-9\s&]+)\b',
            r'\bpresented by\s+([A-Za-z0-9\s&]+)\b',
            r'\bhosted by\s+([A-Za-z0-9\s&]+)\b'
        ]
        
        hosts = []
        for pattern in host_patterns:
            host_matches = re.findall(pattern, self.raw_text, re.IGNORECASE)
            hosts.extend(host_matches)
        
        if hosts:
            self.extracted_info['event_hosts'] = ', '.join(hosts)
        
        # Extract description (use remaining text that's not already categorized)
        # This is a simplified approach; a more sophisticated NLP approach would be better
        used_text = [
            self.extracted_info['event_name'],
            self.extracted_info['event_date'],
            self.extracted_info['event_time'],
            self.extracted_info['event_location'],
            self.extracted_info['event_hosts']
        ]
        
        # Filter out None values
        used_text = [text for text in used_text if text]
        
        # Create a description from remaining significant text
        remaining_text = self.raw_text
        for text in used_text:
            remaining_text = remaining_text.replace(text, '')
        
        # Clean up the remaining text
        description_lines = [line.strip() for line in remaining_text.split('\n') if line.strip()]
        if description_lines:
            # Join lines that seem to be part of a description (more than 3 words)
            description = ' '.join([line for line in description_lines if len(line.split()) > 3])
            if description:
                self.extracted_info['event_description'] = description
        
        return self.extracted_info
    
    def parse_date(self):
        """Convert extracted date string to a datetime object."""
        if not self.extracted_info['event_date']:
            return None
        
        try:
            # Try to parse the date string
            date_obj = dateutil.parser.parse(self.extracted_info['event_date'], fuzzy=True)
            return date_obj.date()
        except:
            return None
    
    def get_structured_data(self):
        """Return structured data for database storage."""
        if not self.extracted_info['event_name']:
            self.extract_event_info()
        
        return {
            'raw_text': self.raw_text,
            'event_name': self.extracted_info['event_name'],
            'event_location': self.extracted_info['event_location'],
            'event_date': self.parse_date(),
            'event_time': self.extracted_info['event_time'],
            'event_description': self.extracted_info['event_description'],
            'event_hosts': self.extracted_info['event_hosts']
        }

# Helper functions
def allowed_file(filename):
    """Check if the file extension is allowed."""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Routes
@app.route('/')
def index():
    """Render the home page."""
    return render_template('index.html')

@app.route('/edit/<int:event_id>')
def edit_event(event_id):
    """Render the event edit page."""
    return render_template('edit.html', event_id=event_id)

@app.route('/success')
def success():
    """Render the success page."""
    return render_template('success.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file upload and process the image."""
    # Check if the post request has the file part
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    
    # If user does not select file, browser also
    # submit an empty part without filename
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        # Generate a unique filename to avoid collisions
        original_filename = secure_filename(file.filename)
        filename = f"{uuid.uuid4()}_{original_filename}"
        
        # Save the file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Process the image with OCR
        try:
            ocr_processor = OCRProcessor(file_path)
            extracted_data = ocr_processor.get_structured_data()
            
            # Create a new event in the database
            new_event = Event(
                image_path=os.path.join('uploads', filename),
                raw_text=extracted_data['raw_text'],
                event_name=extracted_data['event_name'],
                event_location=extracted_data['event_location'],
                event_date=extracted_data['event_date'],
                event_time=extracted_data['event_time'],
                event_description=extracted_data['event_description'],
                event_hosts=extracted_data['event_hosts']
            )
            
            db.session.add(new_event)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'event_id': new_event.id,
                'extracted_data': new_event.to_dict()
            }), 200
            
        except Exception as e:
            return jsonify({'error': f'Error processing image: {str(e)}'}), 500
    
    return jsonify({'error': 'File type not allowed'}), 400

@app.route('/api/events/<int:event_id>', methods=['GET'])
def get_event(event_id):
    """Get event details by ID."""
    event = Event.query.get(event_id)
    if not event:
        return jsonify({'error': 'Event not found'}), 404
    
    return jsonify({
        'success': True,
        'event': event.to_dict()
    }), 200

@app.route('/api/events/<int:event_id>', methods=['PUT'])
def update_event(event_id):
    """Update event details after user edits."""
    event = Event.query.get(event_id)
    if not event:
        return jsonify({'error': 'Event not found'}), 404
    
    data = request.json
    
    # Update event fields
    if 'event_name' in data:
        event.event_name = data['event_name']
    if 'event_location' in data:
        event.event_location = data['event_location']
    if 'event_date' in data:
        try:
            event.event_date = datetime.strptime(data['event_date'], '%Y-%m-%d').date()
        except:
            pass
    if 'event_time' in data:
        event.event_time = data['event_time']
    if 'event_description' in data:
        event.event_description = data['event_description']
    if 'event_hosts' in data:
        event.event_hosts = data['event_hosts']
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'event': event.to_dict()
    }), 200

@app.route('/api/events/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    """Delete an event."""
    event = Event.query.get(event_id)
    if not event:
        return jsonify({'error': 'Event not found'}), 404
    
    # Delete the image file
    try:
        image_path = os.path.join(app.root_path, event.image_path)
        if os.path.exists(image_path):
            os.remove(image_path)
    except:
        pass
    
    db.session.delete(event)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Event deleted successfully'
    }), 200

@app.route('/api/auth/google')
def google_auth():
    """Initiate Google OAuth flow."""
    # Set the redirect URI dynamically based on the request
    redirect_uri = url_for('oauth2callback', _external=True)
    CLIENT_CONFIG['web']['redirect_uris'] = [redirect_uri]
    
    # Create the flow using the client config
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    
    # Generate the authorization URL
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    
    # Store the state in the session
    session['state'] = state
    
    # Redirect to the authorization URL
    return redirect(authorization_url)

@app.route('/api/auth/google/callback')
def oauth2callback():
    """Handle the OAuth callback."""
    # Verify state
    state = session.get('state', '')
    if state != request.args.get('state', ''):
        return jsonify({'error': 'Invalid state parameter'}), 401
    
    # Set the redirect URI dynamically based on the request
    redirect_uri = url_for('oauth2callback', _external=True)
    CLIENT_CONFIG['web']['redirect_uris'] = [redirect_uri]
    
    # Create the flow using the client config
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        state=state
    )
    
    # Use the authorization code to get credentials
    flow.fetch_token(authorization_response=request.url)
    
    # Store the credentials in the session
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
    # Redirect to the event edit page
    event_id = session.get('event_id', '')
    if event_id:
        return redirect(f'/edit/{event_id}')
    else:
        return redirect('/')

@app.route('/api/calendar/create', methods=['POST'])
def create_calendar_event():
    """Create an event in Google Calendar."""
    # Check if credentials are available
    if 'credentials' not in session:
        return jsonify({'error': 'Not authenticated with Google'}), 401
    
    # Get the event ID from the request
    data = request.json
    event_id = data.get('event_id')
    if not event_id:
        return jsonify({'error': 'Event ID is required'}), 400
    
    # Get the event from the database
    event = Event.query.get(event_id)
    if not event:
        return jsonify({'error': 'Event not found'}), 404
    
    # Build the Google Calendar event
    calendar_event = {
        'summary': event.event_name,
        'location': event.event_location,
        'description': f"{event.event_description or ''}\n\nHosts/DJs: {event.event_hosts or 'Not specified'}"
    }
    
    # Set the start and end times
    if event.event_date:
        start_date = event.event_date
        end_date = event.event_date
        
        # Parse the time if available
        start_time = '19:00:00'  # Default to 7 PM if no time specified
        end_time = '22:00:00'    # Default to 10 PM if no time specified
        
        if event.event_time:
            # Simple parsing for common time formats
            time_str = event.event_time.lower()
            
            # Extract hours and minutes
            if 'pm' in time_str:
                # PM time
                time_parts = time_str.replace('pm', '').strip().split(':')
                hour = int(time_parts[0])
                if hour < 12:
                    hour += 12
                minute = int(time_parts[1]) if len(time_parts) > 1 else 0
                start_time = f"{hour:02d}:{minute:02d}:00"
                end_time = f"{(hour+3)%24:02d}:{minute:02d}:00"  # Default 3 hours duration
            elif 'am' in time_str:
                # AM time
                time_parts = time_str.replace('am', '').strip().split(':')
                hour = int(time_parts[0])
                minute = int(time_parts[1]) if len(time_parts) > 1 else 0
                start_time = f"{hour:02d}:{minute:02d}:00"
                end_time = f"{(hour+3)%24:02d}:{minute:02d}:00"  # Default 3 hours duration
        
        # Set the start and end datetime
        start_datetime = f"{start_date.strftime('%Y-%m-%d')}T{start_time}"
        end_datetime = f"{end_date.strftime('%Y-%m-%d')}T{end_time}"
        
        calendar_event['start'] = {
            'dateTime': start_datetime,
            'timeZone': 'America/New_York'  # NYC timezone
        }
        calendar_event['end'] = {
            'dateTime': end_datetime,
            'timeZone': 'America/New_York'  # NYC timezone
        }
    else:
        # If no date is available, use the current date
        today = datetime.now().strftime('%Y-%m-%d')
        calendar_event['start'] = {
            'date': today
        }
        calendar_event['end'] = {
            'date': today
        }
    
    # Add reminders
    calendar_event['reminders'] = {
        'useDefault': False,
        'overrides': [
            {'method': 'popup', 'minutes': 60},
            {'method': 'email', 'minutes': 1440}  # 24 hours before
        ]
    }
    
    try:
        # Get credentials from the session
        creds_dict = session['credentials']
        credentials = Credentials(
            token=creds_dict['token'],
            refresh_token=creds_dict['refresh_token'],
            token_uri=creds_dict['token_uri'],
            client_id=creds_dict['client_id'],
            client_secret=creds_dict['client_secret'],
            scopes=creds_dict['scopes']
        )
        
        # Build the Google Calendar service
        service = build('calendar', 'v3', credentials=credentials)
        
        # Insert the event
        created_event = service.events().insert(
            calendarId='primary',
            body=calendar_event
        ).execute()
        
        # Update the event in the database with the Google Calendar event ID
        event.google_event_id = created_event['id']
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Event created in Google Calendar',
            'event_link': created_event['htmlLink']
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Error creating calendar event: {str(e)}'}), 500

# Create database tables
with app.app_context():
    db.create_all()

# Run the app
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
