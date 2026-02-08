import PyPDF2  # for PDF text extraction
from io import BytesIO
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from groq import Groq
import re
from datetime import datetime, timedelta
import speech_recognition as sr
from gtts import gTTS
import io
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
import requests
from urllib.parse import urlparse, parse_qs
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import threading
import time
import queue
import base64
from openai import OpenAI
import random
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
from google_auth_oauthlib.flow import Flow

# ═══════════════════════════════════════════════════════════════
# CUSTOM CSS FOR CHAT INPUT STYLING
# ═══════════════════════════════════════════════════════════════
st.markdown("""
    <style>
    /* Change chat input text and textarea color to grey */
    .stChatInput textarea,
    .stChatInput input {
        color: #b0b0b0 !important;
    }
    
    /* Change chat input placeholder color to grey */
    .stChatInput textarea::placeholder,
    .stChatInput input::placeholder {
        color: #808080 !important;
    }
    
    /* Match input background with chatbox */
    .stChatInput {
        background-color: transparent !important;
    }
    </style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS - UI COMPONENTS
# ═══════════════════════════════════════════════════════════════

def display_message(role, content):
    """
    Displays chat message with avatars and copy button.
    
    Args:
        role: "user" or "assistant"
        content: Message text (supports markdown)
    """
    # Avatar URLs
    avatars = {
        "user": "https://api.dicebear.com/7.x/avataaars/svg?seed=user",
        "assistant": "https://api.dicebear.com/7.x/bottts/svg?seed=chef&backgroundColor=FF6B35"
    }
    
    with st.chat_message(role, avatar=avatars.get(role)):
        st.markdown(content)
        
        # Add copy button for assistant messages
        if role == "assistant":
            if st.button("📋 Copy", key=f"copy_{hash(content)}", help="Copy to clipboard"):
                st.code(content, language=None)
                st.toast("Copied! 🎉", icon="✅")

def format_recipe(recipe_text):
    """
    Formats recipe with expandable sections and copy buttons.
    """
    # Ingredients expander
    with st.expander("🥘 Ingredients", expanded=True):
        ingredients = [line for line in recipe_text.split("\n") if line.strip().startswith("-") or line.strip().startswith("•")]
        if ingredients:
            for ing in ingredients:
                st.markdown(ing)
            if st.button("📋 Copy Ingredients", key="copy_ing"):
                st.code("\n".join(ingredients), language=None)
                st.toast("Ingredients copied!", icon="🥘")
        else:
            st.info("No ingredients detected in standard format")
    
    # Steps expander
    with st.expander("👨‍🍳 Cooking Steps", expanded=True):
        steps = [line for line in recipe_text.split("\n") if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith("Step"))]
        if steps:
            for step in steps:
                st.markdown(step)
            if st.button("📋 Copy Steps", key="copy_steps"):
                st.code("\n".join(steps), language=None)
                st.toast("Steps copied!", icon="👨‍🍳")
        else:
            st.info("No steps detected in standard format")
    
    # Full recipe copy
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("📄 Copy Full Recipe", use_container_width=True, type="primary"):
            st.code(recipe_text, language=None)
            st.balloons()
            st.toast("Full recipe copied!", icon="📄")
def auto_extract_ingredients_from_recipe(recipe_text):
    """
    Automatically extracts ingredients list from last recipe.
    Returns: list of ingredient names (strings)
    """
    ingredients = extract_ingredients(recipe_text, jain_mode=st.session_state.jain_mode)
    return [ing['name'] for ing in ingredients]
# ═══════════════════════════════════════════════════════════════
# FIREBASE INITIALIZATION (safe for Streamlit reruns)
# ═══════════════════════════════════════════════════════════════
# ================= FIREBASE INITIALIZATION (safe for Streamlit reruns) =================

APP_NAME = "annapurna-default"

if APP_NAME not in firebase_admin._apps:
    try:
        cred_dict = {
            "type": "service_account",
            "project_id": st.secrets["firebase"]["project_id"],
            "private_key_id": st.secrets["firebase"]["private_key_id"],
            "private_key": st.secrets["firebase"]["private_key"],
            "client_email": st.secrets["firebase"]["client_email"],
            "client_id": st.secrets["firebase"]["client_id"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": st.secrets["firebase"]["client_x509_cert_url"]
        }
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, name=APP_NAME)
    except Exception as e:
        st.error(f"Firebase initialization failed: {str(e)}\nCheck secrets in Streamlit Cloud")
        st.stop()

# Always define db safely
db = firestore.client(app=firebase_admin.get_app(APP_NAME))

# ================= SESSION STATE INITIALIZATION =================
if "is_authenticated" not in st.session_state:
    st.session_state.is_authenticated = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_name" not in st.session_state:
    st.session_state.user_name = None
if "show_onboarding" not in st.session_state:
    st.session_state.show_onboarding = False
if "user_preferences" not in st.session_state:
    st.session_state.user_preferences = {}

# ================= AUTHENTICATION FUNCTIONS =================

def show_login():
    """Display login page with Google OAuth and Guest mode"""
    st.title("🍳 Welcome to Annapurna")
    st.markdown("### Your AI-Powered Cooking Assistant")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Sign in with Google")
        
        # Create Google OAuth URL
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": st.secrets["google_oauth"]["client_id"],
                    "client_secret": st.secrets["google_oauth"]["client_secret"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [st.secrets["google_oauth"]["redirect_uri"]],
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/userinfo.profile",
                "https://www.googleapis.com/auth/userinfo.email"
            ],
            redirect_uri=st.secrets["google_oauth"]["redirect_uri"]
        )
        
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true"
        )
        
        # Google Sign-In Button
        st.markdown(f"""
            <a href="{authorization_url}" target="_self" style="text-decoration:none;">
                <button style="
                    background: #4285F4; 
                    color: white; 
                    padding: 12px 24px; 
                    border: none; 
                    border-radius: 4px; 
                    font-size: 16px; 
                    cursor: pointer; 
                    width: 100%; 
                    display: flex; 
                    align-items: center; 
                    justify-content: center; 
                    gap: 8px;
                    font-weight: 500;
                ">
                    <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" width="18">
                    Sign in with Google
                </button>
            </a>
        """, unsafe_allow_html=True)
        
        st.caption("Secure login via Google")
    
    with col2:
        st.subheader("Or continue as Guest")
        st.info("Quick access without login\n(Data won't be saved)")
        
        if st.button("🚀 Continue as Guest", use_container_width=True):
            st.session_state.user_id = f"guest_{uuid.uuid4().hex[:8]}"
            st.session_state.user_email = "guest@kitchenmate.app"
            st.session_state.user_name = "Guest"
            st.session_state.is_authenticated = True
            st.session_state.show_onboarding = True
            st.rerun()

def onboarding():
    """Show onboarding screen for new users"""
    st.title("⚙️ Quick Setup")
    st.markdown(f"### Welcome, {st.session_state.user_name}! 👋")
    
    with st.form("onboarding_form"):
        diet = st.radio(
            "🥗 Diet Preference",
            ["Pure Veg", "Vegetarian", "Non-Veg", "Vegan", "Jain"],
            help="This helps us customize recipe suggestions"
        )
        
        allergies = st.text_input(
            "🚫 Allergies (comma-separated)",
            placeholder="e.g., peanuts, dairy, shellfish"
        )
        
        submitted = st.form_submit_button("Save & Start Cooking! 🚀", use_container_width=True)
        
        if submitted:
            prefs = {
                "diet": diet,
                "allergies": allergies,
                "created_at": datetime.now().isoformat()
            }
            
            # Save to Firestore (only for non-guest users)
            if not st.session_state.user_email.startswith("guest"):
                try:
                    doc_ref = db.collection("users").document(st.session_state.user_id)
                    doc_ref.set({
                        "email": st.session_state.user_email,
                        "name": st.session_state.user_name,
                        "preferences": prefs
                    }, merge=True)
                    st.success("✅ Preferences saved!")
                except Exception as e:
                    st.warning(f"⚠️ Couldn't save to cloud: {str(e)}")
            
            # Apply preferences to session
            st.session_state.user_preferences = prefs
            st.session_state.allergies = allergies
            
            if diet == "Jain":
                st.session_state.jain_mode = True
            if diet in ["Pure Veg", "Vegan", "Jain"]:
                st.session_state.pure_veg_mode = True
            
            st.session_state.show_onboarding = False
            st.balloons()
            time.sleep(1)
            st.rerun()

def load_user_data():
    """Load user's saved data from Firestore"""
    if st.session_state.user_email.startswith("guest"):
        return  # Skip for guest users
    
    try:
        doc_ref = db.collection("users").document(st.session_state.user_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            
            # Load preferences
            if "preferences" in data:
                prefs = data["preferences"]
                st.session_state.user_preferences = prefs
                st.session_state.allergies = prefs.get("allergies", "")
                
                diet = prefs.get("diet", "")
                if diet == "Jain":
                    st.session_state.jain_mode = True
                if diet in ["Pure Veg", "Vegan", "Jain"]:
                    st.session_state.pure_veg_mode = True
            
            # Load inventory
            if "inventory" in data:
                st.session_state.inventory = data["inventory"]
            if "inventory_prices" in data:
                st.session_state.inventory_prices = data["inventory_prices"]
            if "inventory_expiry" in data:
                st.session_state.inventory_expiry = data["inventory_expiry"]
            if "grocery_list" in data:
                st.session_state.grocery_list = set(data["grocery_list"])
            if "diet_charts" in data:
                st.session_state.diet_charts = data["diet_charts"]
            
    except Exception as e:
        st.warning(f"Couldn't load saved data: {str(e)}")

# ================= AUTH CHECK =================

# Check if user is authenticated
if not st.session_state.is_authenticated:
    show_login()
    st.stop()

# Load user data on first login
if st.session_state.is_authenticated and "data_loaded" not in st.session_state:
    load_user_data()
    
    # Automatic expiration countdown
    today = datetime.now().date()
    
    # Initialize last_opened if missing
    if "last_opened_date" not in st.session_state:
        st.session_state.last_opened_date = today
    
    # Calculate days passed since last open
    days_passed = (today - st.session_state.last_opened_date).days
    
    if days_passed > 0:
        updated = False
        for item, days_left in list(st.session_state.inventory_expiry.items()):
            if isinstance(days_left, (int, float)):
                new_days = days_left - days_passed
                st.session_state.inventory_expiry[item] = max(-30, new_days)  # don't go below -30
                updated = True
        
        if updated:
            # Optional: save updated expiry to Firestore
            if not st.session_state.user_email.startswith("guest"):
                try:
                    db.collection("users").document(st.session_state.user_id).set({
                        "inventory_expiry": dict(st.session_state.inventory_expiry)
                    }, merge=True)
                except:
                    pass  # silent fail
        
        # Update last opened date
        st.session_state.last_opened_date = today
    
    st.session_state.data_loaded = True

# Show onboarding if needed
if st.session_state.show_onboarding:
    onboarding()
    st.stop()

# ================= API KEYS =================
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

# Initialize clients
client = Groq(api_key=GROQ_API_KEY)

openrouter_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

# ================= REST OF YOUR CODE CONTINUES HERE =================
# ================= SESSION STATE =================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "grocery_list" not in st.session_state:
    st.session_state.grocery_list = set()
if "inventory" not in st.session_state:
    st.session_state.inventory = {
        "salt": 500, "chilli powder": 200, "turmeric": 150,
        "rice": 2000, "oil": 1000, "onion": 10, "tomato": 8,
        "paneer": 500, "potato": 2000, "milk": 1000, "garlic": 200, "ginger": 150
    }
if "inventory_prices" not in st.session_state:
    st.session_state.inventory_prices = {}
if "inventory_expiry" not in st.session_state:
    st.session_state.inventory_expiry = {}
if "meal_plan" not in st.session_state:
    st.session_state.meal_plan = {}
if "allergies" not in st.session_state:
    st.session_state.allergies = ""
if "custom_recipes" not in st.session_state:
    st.session_state.custom_recipes = {}
if "show_cooking_check" not in st.session_state:
    st.session_state.show_cooking_check = False
if "show_nutrition" not in st.session_state:
    st.session_state.show_nutrition = False
if "show_substitutes" not in st.session_state:
    st.session_state.show_substitutes = False
if "last_recipe" not in st.session_state:
    st.session_state.last_recipe = ""
if "pure_veg_mode" not in st.session_state:
    st.session_state.pure_veg_mode = False
if "health_mode" not in st.session_state:
    st.session_state.health_mode = False
if "language_mode" not in st.session_state:
    st.session_state.language_mode = "Hinglish"
if "tried_recipes" not in st.session_state:
    st.session_state.tried_recipes = []
if "favourite_recipes" not in st.session_state:
    st.session_state.favourite_recipes = {}
if "diet_charts" not in st.session_state:
    st.session_state.diet_charts = {}
if "unit_system" not in st.session_state:
    st.session_state.unit_system = "metric"
if "servings" not in st.session_state:
    st.session_state.servings = 1
if "voice_enabled" not in st.session_state:
    st.session_state.voice_enabled = False
if "voice_language" not in st.session_state:
    st.session_state.voice_language = "English"
if "cooking_mode" not in st.session_state:
    st.session_state.cooking_mode = False
if "current_step" not in st.session_state:
    st.session_state.current_step = 0
if "cooking_steps" not in st.session_state:
    st.session_state.cooking_steps = []
if "ingredients_shown" not in st.session_state:
    st.session_state.ingredients_shown = False
if "missing_ingredients" not in st.session_state:
    st.session_state.missing_ingredients = []
if "processing_video" not in st.session_state:
    st.session_state.processing_video = False
if "video_recipe" not in st.session_state:
    st.session_state.video_recipe = ""
if "listening_active" not in st.session_state:
    st.session_state.listening_active = False
if "listening_status" not in st.session_state:
    st.session_state.listening_status = "idle"  # idle, listening, recording, processing
if "wake_word_detected" not in st.session_state:
    st.session_state.wake_word_detected = False
if "voice_command_queue" not in st.session_state:
    st.session_state.voice_command_queue = queue.Queue()
if "listening_thread" not in st.session_state:
    st.session_state.listening_thread = None
if "jain_mode" not in st.session_state:
    st.session_state.jain_mode = False
if "new_command_available" not in st.session_state:
    st.session_state.new_command_available = False
if "listening_error" not in st.session_state:
    st.session_state.listening_error = None
if "pending_voice_command" not in st.session_state:
    st.session_state.pending_voice_command = None
# Initialize auth-related session state (prevents AttributeError)
if "is_authenticated" not in st.session_state:
    st.session_state.is_authenticated = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "show_onboarding" not in st.session_state:
    st.session_state.show_onboarding = False
if "user_preferences" not in st.session_state:
    st.session_state.user_preferences = {}
if "gym_diet_chart" not in st.session_state:
    st.session_state.gym_diet_chart = None  # stores analyzed/edited chart summary
if "detected_ingredients" not in st.session_state:
    st.session_state.detected_ingredients = []

# Listen for Firebase login from iframe
st.components.v1.html("""
    <script>
        window.addEventListener('message', function(event) {
            if (event.data.type === 'firebase_login') {
                const url = new URL(window.location);
                url.searchParams.set('auth', 'success');
                url.searchParams.set('uid', event.data.uid);
                url.searchParams.set('email', encodeURIComponent(event.data.email));
                window.location = url;
            }
        });
    </script>
""", height=0)
# ================= VOICE HELPERS =================
def listen_for_wake_word_chunk():
    """Listen for a short audio chunk and check for wake word"""
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 4000  # Adjust for sensitivity
    recognizer.dynamic_energy_threshold = True
    
    try:
        with sr.Microphone() as source:
            # Adjust for ambient noise
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            # Listen for 3 seconds
            audio = recognizer.listen(source, timeout=3, phrase_time_limit=3)
            
            # Transcribe
            text = recognizer.recognize_google(audio).lower()
            
            # Check for wake word variants
            wake_words = ["hey chef", "hey chief", "a chef", "hey chefs"]
            if any(wake_word in text for wake_word in wake_words):
                return True, text
            return False, text
            
    except sr.WaitTimeoutError:
        return False, ""
    except sr.UnknownValueError:
        return False, ""
    except sr.RequestError:
        return False, ""
    except Exception as e:
        return False, ""

def record_voice_command():
    """Record full voice command after wake word detected"""
    recognizer = sr.Recognizer()
    
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            # Listen for command (up to 8 seconds)
            audio = recognizer.listen(source, timeout=2, phrase_time_limit=8)
            text = recognizer.recognize_google(audio)
            return text
    except Exception as e:
        return None

def continuous_listening_loop():
    """Background thread for continuous listening"""
    while st.session_state.get('listening_active', False):
        try:
            if st.session_state.listening_status == "listening":
                # Listen for wake word
                wake_detected, heard_text = listen_for_wake_word_chunk()
                
                if wake_detected:
                    st.session_state.listening_status = "recording"
                    st.session_state.wake_word_detected = True
                    
                    # Small pause
                    time.sleep(0.5)
                    
                    # Record command
                    command = record_voice_command()
                    
                    if command:
                        st.session_state.voice_command_queue.put(command)
                        st.session_state.listening_status = "processing"
                        # Set flag to trigger rerun
                        st.session_state.new_command_available = True
                    else:
                        # No command received, go back to listening
                        st.session_state.listening_status = "listening"
                        st.session_state.wake_word_detected = False
            
            time.sleep(0.2)  # Increased delay to reduce CPU usage
            
        except Exception as e:
            st.session_state.listening_status = "error"
            st.session_state.listening_error = str(e)
            break
    
    # Cleanup when stopped
    st.session_state.listening_status = "idle"

def start_continuous_listening():
    """Start the continuous listening mode"""
    if not st.session_state.listening_active:
        st.session_state.listening_active = True
        st.session_state.listening_status = "listening"
        
        # Start listening thread
        thread = threading.Thread(target=continuous_listening_loop, daemon=True)
        thread.start()
        st.session_state.listening_thread = thread

def stop_continuous_listening():
    """Stop the continuous listening mode"""
    st.session_state.listening_active = False
    st.session_state.listening_status = "idle"
    st.session_state.wake_word_detected = False
    st.session_state.new_command_available = False
    
    # Wait for thread to finish
    if st.session_state.listening_thread and st.session_state.listening_thread.is_alive():
        st.session_state.listening_thread.join(timeout=2)
    
    st.session_state.listening_thread = None

    # ================= NEW: IMAGE DETECTION HELPER =================
def detect_ingredients_from_image(image_bytes):
    try:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        response = openrouter_client.chat.completions.create( 
            model="google/gemini-2.0-flash-exp:free",  # Updated to working model
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "List all visible food ingredients in this image. One item per line. Use simple English names."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            max_tokens=200
        )
        text = response.choices[0].message.content.strip()
        items = [line.strip().lower() for line in text.split("\n") if line.strip()]
        return items
    except Exception as e:
        st.error(f"Detection error: {str(e)}")
        return []
def get_expiry_estimate(item_name):
    """Simple estimate for expiry in days"""
    item = item_name.lower()
    if any(x in item for x in ["tomato", "onion", "cucumber", "spinach", "coriander", "curry leaves"]):
        return random.randint(3, 7)   # fresh veggies
    elif any(x in item for x in ["potato", "carrot", "beetroot", "pumpkin"]):
        return random.randint(10, 20) # root veggies
    elif "milk" in item or "curd" in item:
        return random.randint(2, 5)
    elif "paneer" in item:
        return random.randint(3, 6)
    elif any(x in item for x in ["rice", "dal", "flour", "oil", "spices"]):
        return random.randint(180, 365) # long shelf
    else:
        return random.randint(7, 30)  # default
def detect_youtube_url(text):
    """Detect YouTube URLs in text and extract video ID"""
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:m\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None

def extract_youtube_transcript(video_id):
    """Extract transcript from YouTube video"""
    try:
        # Try to get transcript in English first, then Hindi
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        try:
            transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
        except:
            try:
                transcript = transcript_list.find_transcript(['hi', 'hi-IN'])
            except:
                # Get any available transcript
                transcript = transcript_list.find_generated_transcript(['en', 'hi'])
        
        # Fetch and combine all text
        transcript_data = transcript.fetch()
        full_text = " ".join([entry['text'] for entry in transcript_data])
        return full_text
    
    except TranscriptsDisabled:
        return None
    except NoTranscriptFound:
        return None
    except Exception as e:
        return None

def get_video_title(video_id):
    """Get YouTube video title using oEmbed API"""
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get('title', 'Unknown Video')
    except:
        pass
    return 'Unknown Video'

def get_video_description(video_id):
    """Get YouTube video description using YouTube Data API v3"""
    if not YOUTUBE_API_KEY:
        return None, "⚠️ YouTube API key not configured. Please add your API key in the code."
    
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        
        request = youtube.videos().list(
            part='snippet',
            id=video_id
        )
        response = request.execute()
        
        if response['items']:
            snippet = response['items'][0]['snippet']
            title = snippet.get('title', 'Unknown Video')
            description = snippet.get('description', '')
            return {
                'title': title,
                'description': description
            }, None
        else:
            return None, "Video not found"
            
    except HttpError as e:
        return None, f"API Error: {str(e)}"
    except Exception as e:
        return None, f"Error: {str(e)}"

def extract_recipe_links(description):
    """Extract URLs from video description"""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    urls = re.findall(url_pattern, description)
    
    # Filter out common non-recipe URLs
    recipe_urls = []
    exclude_patterns = ['instagram.com', 'facebook.com', 'twitter.com', 'youtube.com', 'youtu.be']
    
    for url in urls:
        if not any(pattern in url.lower() for pattern in exclude_patterns):
            recipe_urls.append(url)
    
    return recipe_urls

def scrape_recipe_from_url(url):
    """Scrape recipe content from external URL"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            # Simple text extraction (you can enhance this with BeautifulSoup for better parsing)
            text = response.text
            # Remove HTML tags for basic parsing
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:5000]  # Limit to first 5000 chars
        return None
    except Exception as e:
        return None

def parse_recipe_from_transcript(transcript_text, video_title=""):
    """Use AI to extract recipe from transcript"""
    prompt = f"""
You are a recipe extractor. Below is a transcript from a cooking video titled "{video_title}".

Extract the recipe in this format:

**Recipe: [Dish Name]**

**Ingredients:**
- ingredient 1 with quantity
- ingredient 2 with quantity
(list all mentioned)

**Steps:**
1. Step one
2. Step two
(numbered steps)

Transcript:
{transcript_text[:3000]}

Be concise and practical. If ingredients aren't clearly mentioned, make reasonable estimates based on the cooking steps described.
"""
    
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.5,
            max_tokens=800,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error parsing recipe: {str(e)}"

def parse_recipe_from_description(description_text, scraped_content="", video_title=""):
    """Use AI to extract recipe from description + scraped content"""
    combined_text = f"Video Title: {video_title}\n\nDescription:\n{description_text}\n\n"
    
    if scraped_content:
        combined_text += f"Recipe Page Content:\n{scraped_content}"
    
    prompt = f"""
You are a recipe extractor. Extract the complete recipe with exact measurements.

{combined_text[:4000]}

Format the recipe as:

**Recipe: [Dish Name]**

**Ingredients:**
- ingredient 1 with EXACT quantity (e.g., 2 cups, 500g)
- ingredient 2 with EXACT quantity
(list ALL ingredients with measurements)

**Steps:**
1. Detailed step one
2. Detailed step two
(numbered steps)

IMPORTANT: Extract EXACT quantities. Don't estimate - use the measurements provided.
"""
    
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            max_tokens=1000,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error parsing recipe: {str(e)}"

def transcribe_audio(audio_bytes):
    """Convert speech to text using Google Speech Recognition"""
    try:
        recognizer = sr.Recognizer()
        audio = sr.AudioData(audio_bytes, 16000, 2)
        text = recognizer.recognize_google(audio)
        return text
    except sr.UnknownValueError:
        return None
    except sr.RequestError:
        return None
    except Exception as e:
        st.error(f"Transcription error: {str(e)}")
        return None

def text_to_speech(text, lang_code=None):
    """Convert text to speech. If lang_code not provided, uses session state."""
    if lang_code is None:
        lang_code = "mr" if st.session_state.voice_language == "Marathi" else \
                   "hi" if st.session_state.voice_language == "Hindi" else "en"
    try:
        tts = gTTS(text=text, lang=lang_code, slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception as e:
        st.error(f"TTS error: {str(e)}")
        return None

# ================= HELPERS =================
def get_quantity_status(qty):
    if qty >= 500:
        return "High", "green"
    elif qty >= 200:
        return "Medium", "orange"
    else:
        return "Low", "red"

UNIT_CONVERSIONS = {
    "g": {"imperial": ("oz", 0.035274), "metric": ("g", 1.0)},
    "kg": {"imperial": ("lbs", 2.20462), "metric": ("kg", 1.0)},
    "gram": {"imperial": ("oz", 0.035274), "metric": ("g", 1.0)},
    "grams": {"imperial": ("oz", 0.035274), "metric": ("g", 1.0)},
    "ml": {"imperial": ("fl oz", 0.033814), "metric": ("ml", 1.0)},
    "l": {"imperial": ("cups", 4.22675), "metric": ("l", 1.0)},
    "pcs": {"imperial": ("pcs", 1.0), "metric": ("pcs", 1.0)},
    "piece": {"imperial": ("piece", 1.0), "metric": ("piece", 1.0)},
    "pieces": {"imperial": ("pieces", 1.0), "metric": ("pieces", 1.0)},
    "cup": {"imperial": ("cup", 1.0), "metric": ("cup", 1.0)},
    "cups": {"imperial": ("cups", 1.0), "metric": ("cups", 1.0)},
}

def convert_quantity(qty_str, target_system="metric"):
    if qty_str in ["as needed", "to taste", "a pinch"]:
        return qty_str
    try:
        parts = qty_str.split(maxsplit=1)
        num = float(parts[0])
        unit = parts[1].lower() if len(parts) > 1 else ""
        base_unit = unit.rstrip('s')
        if base_unit not in UNIT_CONVERSIONS:
            return qty_str
        conv = UNIT_CONVERSIONS[base_unit][target_system]
        new_unit, factor = conv
        new_num = round(num * factor, 2) if factor != 1.0 else num
        return f"{new_num} {new_unit}"
    except:
        return qty_str

def scale_quantity(qty_str, servings=1):
    if servings <= 1:
        return qty_str
    try:
        parts = qty_str.split(maxsplit=1)
        num = float(parts[0])
        rest = " " + parts[1] if len(parts) > 1 else ""
        return f"{round(num * servings, 1)}{rest}"
    except:
        return qty_str
def generate_weekly_plan_from_chart(chart_summary):
    with st.spinner("Creating your personalized 7-day plan..."):
        plan_prompt = f"""
        You are an expert Indian meal planner for fitness goals.
        
        User's gym diet chart summary:
        {chart_summary}
        
        User's preferences:
        - Allergies: {st.session_state.get('allergies', 'None')}
        - Diet mode: {'Jain' if st.session_state.get('jain_mode') else 'Normal'}
        - Pure Veg: {'Yes' if st.session_state.get('pure_veg_mode') else 'No'}
        
        Generate a realistic 7-day Indian meal plan:
        - Breakfast, Mid-morning snack, Lunch, Evening snack, Dinner
        - Match protein/calorie targets from chart
        - Use simple home ingredients
        - Suggest recipes or simple meals
        
        Format:
        Day 1:
        - Breakfast: [meal] (~X cal, Xg protein)
        - ...
        
        At the end, list missing ingredients not in inventory.
        """
        
        try:
            response = client.chat.completions.create(
                messages=[{"role": "user", "content": plan_prompt}],
                model="llama-3.3-70b-versatile",
                temperature=0.6,
                max_tokens=1500
            )
            plan_text = response.choices[0].message.content.strip()
            
            st.markdown("### Your 7-Day Gym Plan")
            st.markdown(plan_text)
            
            # Extract missing items (simple regex - improve later)
            missing_match = re.search(r"Missing ingredients:(.*)", plan_text, re.DOTALL | re.IGNORECASE)
            if missing_match:
                missing_items = [item.strip() for item in missing_match.group(1).split("\n") if item.strip()]
                for item in missing_items:
                    st.session_state.grocery_list.add(item.lower())
                st.success(f"Added {len(missing_items)} missing items to grocery list!")
            
            # Save plan to meal planner (simplified)
            today = datetime.now().date()
            for i in range(7):
                day_key = (today + timedelta(days=i)).strftime("%Y-%m-%d")
                if day_key not in st.session_state.meal_plan:
                    st.session_state.meal_plan[day_key] = {}
                st.session_state.meal_plan[day_key]["Gym Plan"] = "Generated from chart"
            
            st.success("Plan added to Meal Planner tab!")
            
        except Exception as e:
            st.error(f"Plan generation failed: {str(e)}")
def add_items_from_receipt(receipt_text):
    lines = [line.strip() for line in receipt_text.split("\n") if line.strip() and "|" in line]
    added_count = 0
    
    for line in lines:
        try:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            name = parts[0].lower()
            qty_str = parts[1]
            unit = parts[2].lower()
            price = float(parts[3].replace("₹", "").strip()) if len(parts) > 3 else 0
            
            # Convert to grams/ml/pcs
            qty_num = float(re.search(r'\d*\.?\d+', qty_str).group()) if re.search(r'\d', qty_str) else 500
            if "kg" in unit:
                qty_num *= 1000
            elif "l" in unit:
                qty_num *= 1000
            
            key = name
            st.session_state.inventory[key] = int(qty_num)
            if price > 0:
                st.session_state.inventory_prices[key] = price / (qty_num / 100)  # per 100g/ml
            added_count += 1
            
        except:
            continue
    
    if added_count > 0:
        st.success(f"Added {added_count} items to inventory!")
        st.rerun()
    else:
        st.warning("No valid items found.")

def add_missing_items_from_receipt(receipt_text):
    lines = [line.strip() for line in receipt_text.split("\n") if line.strip() and "|" in line]
    added_count = 0
    
    for line in lines:
        try:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            name = parts[0].lower()
            
            # Skip if already in inventory
            if name in st.session_state.inventory:
                continue
                
            qty_str = parts[1]
            qty_num = float(re.search(r'\d*\.?\d+', qty_str).group()) if re.search(r'\d', qty_str) else 500
            st.session_state.inventory[name] = int(qty_num)
            added_count += 1
            
        except:
            continue
    
    if added_count > 0:
        st.success(f"Added {added_count} missing items!")
        st.rerun()
    else:
        st.info("All items already in inventory!")

# ================= INGREDIENT ACCEPT PATTERNS =================

# Comprehensive food ingredient categories
VEGETABLES = [
    "onion", "tomato", "potato", "garlic", "ginger", "carrot", "beetroot",
    "capsicum", "bell pepper", "cabbage", "cauliflower", "broccoli",
    "spinach", "palak", "methi", "fenugreek", "coriander", "cilantro",
    "curry leaves", "mint", "pudina", "beans", "peas", "corn",
    "cucumber", "radish", "turnip", "pumpkin", "bottle gourd", "lauki",
    "bitter gourd", "karela", "ridge gourd", "turai", "eggplant", "brinjal",
    "okra", "bhindi", "mushroom", "zucchini", "lettuce", "celery",
    "spring onion", "leek", "sweet potato", "yam", "colocasia", "arbi"
]

SPICES = [
    "turmeric", "haldi", "cumin", "jeera", "coriander", "dhaniya",
    "chilli", "chili", "red chilli", "green chilli", "kashmiri chilli",
    "black pepper", "white pepper", "cardamom", "elaichi", "cinnamon",
    "dalchini", "clove", "laung", "bay leaf", "tej patta", "star anise",
    "fennel", "saunf", "fenugreek", "methi", "mustard", "sarson", "rai",
    "asafoetida", "hing", "nutmeg", "jaiphal", "mace", "javitri",
    "carom seeds", "ajwain", "nigella", "kalonji", "sesame", "til",
    "poppy seeds", "khus khus", "garam masala", "chaat masala",
    "pav bhaji masala", "chole masala", "biryani masala", "tandoori masala",
    "curry powder", "sambhar powder", "rasam powder", "chilli powder",
    "coriander powder", "cumin powder", "turmeric powder", "ginger powder",
    "garlic powder", "dried mango", "amchur", "dried pomegranate", "anardana",
    "saffron", "kesar", "vanilla", "oregano", "basil", "thyme", "rosemary",
    "paprika", "cayenne"
]

GRAINS_PULSES = [
    "rice", "basmati rice", "sona masoori", "brown rice", "jasmine rice",
    "wheat", "flour", "atta", "maida", "all purpose flour", "whole wheat",
    "semolina", "sooji", "rava", "besan", "gram flour", "chickpea flour",
    "corn flour", "cornstarch", "rice flour", "ragi", "finger millet",
    "jowar", "sorghum", "bajra", "pearl millet", "oats", "quinoa",
    "dal", "lentil", "moong dal", "mung dal", "toor dal", "arhar dal",
    "chana dal", "masoor dal", "urad dal", "chickpea", "kabuli chana",
    "black chickpea", "kala chana", "rajma", "kidney beans", "black beans",
    "white beans", "pinto beans", "soybean", "peanut", "groundnut",
    "almond", "badam", "cashew", "kaju", "walnut", "akhrot", "pistachio",
    "pista", "raisin", "kishmish", "dates", "khajoor", "coconut", "nariyal"
]

DAIRY_PRODUCTS = [
    "milk", "doodh", "cream", "heavy cream", "fresh cream", "whipping cream",
    "butter", "makhan", "ghee", "clarified butter", "paneer", "cottage cheese",
    "cheese", "cheddar", "mozzarella", "parmesan", "cream cheese",
    "curd", "yogurt", "dahi", "buttermilk", "chaas", "khoya", "mawa",
    "condensed milk", "evaporated milk", "milk powder", "malai"
]

PROTEINS = [
    "chicken", "mutton", "lamb", "goat", "beef", "pork", "fish", "machli",
    "prawn", "shrimp", "crab", "salmon", "tuna", "pomfret", "rohu",
    "egg", "anda", "tofu", "soya chunks", "soy", "tempeh"
]

OILS_FATS = [
    "oil", "tel", "mustard oil", "coconut oil", "olive oil", "sunflower oil",
    "vegetable oil", "sesame oil", "groundnut oil", "peanut oil",
    "ghee", "butter", "margarine", "lard"
]

SWEETENERS = [
    "sugar", "chini", "jaggery", "gur", "brown sugar", "honey", "shahad",
    "maple syrup", "corn syrup", "stevia", "artificial sweetener",
    "palm sugar", "coconut sugar", "date syrup"
]

SAUCES_CONDIMENTS = [
    "tomato sauce", "ketchup", "soy sauce", "vinegar", "sirka",
    "tamarind", "imli", "lemon", "nimbu", "lime", "orange", "pomegranate",
    "tomato paste", "tomato puree", "chilli sauce", "hot sauce",
    "worcestershire sauce", "fish sauce", "oyster sauce", "hoisin sauce",
    "mayonnaise", "mustard sauce", "pickle", "achar", "chutney"
]

BREADS_PASTA = [
    "bread", "pav", "bun", "roti", "chapati", "naan", "paratha",
    "puri", "bhatura", "kulcha", "pasta", "macaroni", "spaghetti",
    "noodles", "vermicelli", "seviyan", "couscous"
]

BEVERAGES = [
    "water", "pani", "tea", "chai", "coffee", "juice", "coconut water",
    "stock", "broth", "vegetable stock", "chicken stock", "bone broth"
]

OTHERS = [
    "salt", "namak", "baking soda", "baking powder", "yeast", "gelatin",
    "agar agar", "corn", "cornmeal", "breadcrumbs", "panko",
    "chocolate", "cocoa", "coffee powder", "tea leaves"
]

# Combine all categories
ALL_FOOD_INGREDIENTS = (
    VEGETABLES + SPICES + GRAINS_PULSES + DAIRY_PRODUCTS + 
    PROTEINS + OILS_FATS + SWEETENERS + SAUCES_CONDIMENTS + 
    BREADS_PASTA + BEVERAGES + OTHERS
)

# Create a set for faster lookup
FOOD_INGREDIENTS_SET = set([item.lower() for item in ALL_FOOD_INGREDIENTS])
# ================= JAIN DIET RESTRICTIONS =================
# Ingredients NOT allowed in Jain diet (grown underground)
JAIN_RESTRICTED_INGREDIENTS = [
    # Root vegetables
    "potato", "potatoes", "aloo", "sweet potato", "shakarkandi",
    "onion", "onions", "pyaz", "spring onion", "scallion", "leek",
    "garlic", "lahsun", "lehsun",
    "ginger", "adrak",
    "radish", "mooli", "daikon",
    "carrot", "carrots", "gajar",
    "beetroot", "beet", "chukandar",
    "turnip", "shalgam",
    "yam", "suran", "jimikand",
    "colocasia", "arbi", "taro root",
    "elephant yam", "suran",
    "turmeric", "haldi",  # Fresh turmeric root
    "ginger garlic paste",
    "peanut", "groundnut", "moongfali",  # Grows underground
]

# Create set for faster lookup
JAIN_RESTRICTED_SET = set([item.lower() for item in JAIN_RESTRICTED_INGREDIENTS])

def is_jain_compatible(ingredient_name):
    """Check if ingredient is compatible with Jain diet"""
    ingredient_name = ingredient_name.lower().strip()
    
    # Check if it contains any restricted ingredient
    for restricted in JAIN_RESTRICTED_SET:
        if restricted in ingredient_name:
            # Exception: turmeric powder is allowed
            if "turmeric" in ingredient_name and "powder" in ingredient_name:
                continue
            return False
    
    return True

def get_jain_substitute(ingredient_name):
    """Get Jain-friendly substitute for restricted ingredient"""
    ingredient_name = ingredient_name.lower()
    
    substitutes = {
        "potato": "raw banana (kachha kela), arrowroot (ararot), or sweet corn",
        "onion": "asafoetida (hing) for flavor, or finely chopped cabbage",
        "garlic": "asafoetida (hing) for flavor",
        "ginger": "dry ginger powder (sonth) or green chilli for heat",
        "radish": "cucumber or white pumpkin (petha)",
        "carrot": "bottle gourd (lauki), red pumpkin, or tomatoes",
        "beetroot": "red pumpkin or tomatoes for color",
        "turnip": "white pumpkin (petha) or bottle gourd",
        "peanut": "cashew, almond, or melon seeds",
        "turmeric": "turmeric powder (powder form is allowed)",
        "ginger garlic paste": "green chilli paste with asafoetida (hing)",
    }
    
    for key, substitute in substitutes.items():
        if key in ingredient_name:
            return substitute
    
    return "Please check Jain diet guidelines for substitute"
# Cooking verbs to reject
COOKING_VERBS = [
    "cook", "stir", "add", "mix", "serve", "fry", "boil", "bake", "heat",
    "preheat", "chop", "slice", "dice", "grate", "grind", "pour", "simmer",
    "use", "put", "take", "keep", "let", "bring", "reduce", "thicken",
    "turn", "flip", "cover", "uncover", "sauté", "roast", "steam",
    "blend", "whisk", "knead", "marinate", "garnish", "season", "taste"
]

def is_valid_food_ingredient(name):
    """Check if the name is a valid food ingredient"""
    name = name.lower().strip()
    
    # Too short
    if len(name) < 3:
        return False
    
    # Check if it's a cooking verb
    if any(name.startswith(verb) for verb in COOKING_VERBS):
        return False
    
    # Check if any known ingredient is in the name
    for ingredient in FOOD_INGREDIENTS_SET:
        if ingredient in name or name in ingredient:
            return True
    
    return False
def extract_ingredients(text, jain_mode=False):
    """Enhanced ingredient extraction with stricter cleaning and Jain check"""
    text = text.lower().strip()
    
    # Isolate ingredients section if possible
    ing_markers = r'(ingredients?:?|सामग्री:?|required items:?|what you need:?)'
    step_markers = r'(steps?:?|instructions?:?|method:?|विधि:?|how to make:?)'
    
    ing_start = re.search(ing_markers, text)
    step_start = re.search(step_markers, text)
    
    if ing_start and step_start and ing_start.start() < step_start.start():
        ing_text = text[ing_start.end():step_start.start()].strip()
    elif ing_start:
        ing_text = text[ing_start.end():].strip()
    else:
        ing_text = text
    
    ingredients = []
    
    # Main patterns (improved to split qty/unit/name cleaner)
    patterns = [
        r'(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)?\s*(g|kg|gram|grams|ml|l|liter|litre|pcs?|piece|pieces|tsp|teaspoon|tbsp|tablespoon|cup|cups|pack|packet|medium|large|small)?\s+([a-z][\w\s\-]{3,})(?=\s*(?:,|\.|;|\n|$|\(|\[|to taste|as needed))',
        r'(half|quarter|a|one|two|three|four|five|six|seven|eight|nine|ten|handful|pinch|some)?\s+([a-z][\w\s\-]{3,})(?=\s*(?:,|\.|;|\n|$|\(|\[|to taste|as needed))',
        r'([a-z][\w\s\-]{3,})\s*(to taste|as needed|as required|a pinch of?|to garnish)',
    ]
    
    for pattern in patterns:
        for match in re.finditer(pattern, ing_text, re.IGNORECASE):
            qty_str = "as needed"
            name = ""
            groups = match.groups()
            
            # Extract qty and name, strip extra words
            if len(groups) >= 3 and groups[2]:
                qty_num = groups[0] or ""
                unit = groups[1] or ""
                name = groups[2].strip()
                qty_str = f"{qty_num} {unit}".strip() if qty_num or unit else "as needed"
            elif len(groups) >= 2 and groups[1]:
                qty_str = groups[0].strip() if groups[0] else "as needed"
                name = groups[1].strip()
            elif groups[0]:
                name = groups[0].strip()
                qty_str = groups[1].strip() if len(groups) > 1 and groups[1] else "as needed"
            
            # Clean name: remove "of", "a", "an", "some" if at start
            name = re.sub(r'^(of|a|an|some)\s+', '', name).strip()
            
            # Skip invalid or short names
            if not name or len(name) < 3:
                continue
            


def extract_steps(text):
    """Extract cooking steps from recipe"""
    text_lower = text.lower()
    
    step_markers = r'(steps?:?|instructions?:?|method:?|विधि:?|how to make:?|procedure:?)'
    step_start = re.search(step_markers, text_lower)
    
    if not step_start:
        return []
    
    steps_text = text[step_start.end():].strip()
    
    step_patterns = [
        r'^\d+[\.\)]\s+(.+?)(?=\n\d+[\.\)]|\Z)',
        r'^[-•]\s+(.+?)(?=\n[-•]|\Z)',
        r'^[a-z]\)\s+(.+?)(?=\n[a-z]\)|\Z)',
    ]
    
    steps = []
    for pattern in step_patterns:
        matches = re.findall(pattern, steps_text, re.MULTILINE | re.IGNORECASE)
        if matches:
            steps = [m.strip() for m in matches if m.strip()]
            break
    
    if not steps:
        steps = [s.strip() for s in steps_text.split('\n\n') if s.strip()]
    
    return steps[:15]

def get_system_prompt():
    base = """You are Annapurna - a chill, friendly Indian cooking assistant.
Be casual and helpful. Use simple language.

CRITICAL RULE: You are a RECIPE GENERATOR, not an echo bot!
- If someone asks for a dish (like "butter chicken", "pasta", "biryani"), ALWAYS give the FULL RECIPE with ingredients and steps
- NEVER just repeat the dish name back
- NEVER say "what would you like to know about [dish]?" - just give the recipe!
- If they say "Give me the recipe for pasta" → Give the full pasta recipe immediately

When giving recipes:
- List ingredients with quantities
- Give clear, numbered steps
- End with something friendly

Remember: Your job is to provide recipes, not ask clarifying questions!"""

    if st.session_state.language_mode == "English":
        base += "\nSpeak ONLY in pure English. No Hindi words at all."
    else:
        base += "\nUse casual Hindi."

    if st.session_state.allergies:
        base += f"\nUser allergies: {st.session_state.allergies}. Avoid these completely!"

    low_items = [k for k, v in st.session_state.inventory.items() if v < 200]
    if low_items:
        base += f"\nUser has LOW stock of: {', '.join(low_items)}. Prefer recipes using little of these or suggest substitutes."

    if st.session_state.jain_mode:
        base += "\nUser follows JAIN diet. NEVER suggest: onion, garlic, ginger, potato, carrot, radish, beetroot, or any root vegetables. Use hing (asafoetida) for flavor instead."

    # ───── NEW: Prioritize expiring items ─────
    expiring_soon = []
    for item, days in st.session_state.inventory_expiry.items():
        if isinstance(days, (int, float)) and 0 < days <= 3:
            expiring_soon.append(f"{item} ({days} days left)")
    
    if expiring_soon:
        base += f"\nUser has items expiring very soon: {', '.join(expiring_soon)}. ALWAYS prioritize using these items first in recipes! Suggest them prominently and use substitutes only if absolutely necessary."

    return base

def get_nutrition_prompt(servings):
    return f"""You are a nutrition calculator. For the given recipe, estimate nutritional values **strictly PER {servings} SERVING(S)**.
Return format:
Calories: X kcal
Protein: X g
Carbs: X g
Fat: X g
Fiber: X g

Be realistic using standard Indian/home-cooked food values. Do NOT give total for whole recipe — only per serving."""

# ================= MAIN APP =================
st.set_page_config(
    page_title="Annapurna - AI Cooking Assistant",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="expanded"
)
# Add this right after your st.set_page_config() in the MAIN APP section
st.markdown("""
<style>
    /* ══════════════════════════════════════════════════════════════
       FORCE CHAT INPUT TO STAY AT BOTTOM (AGGRESSIVE FIX)
       ══════════════════════════════════════════════════════════════ */
    
    /* Target the actual chat input container */
    [data-testid="stChatInput"] {
        position: fixed !important;
        bottom: 0 !important;
        left: 0 !important;
        right: 0 !important;
        background: #f5f5f5 !important;
        padding: 20px !important;
        box-shadow: 0 -4px 20px rgba(0,0,0,0.15) !important;
        border-top: 2px solid #e0e0e0 !important;
        z-index: 999999 !important;
        margin: 0 !important;
    }
    
    /* Also target parent container */
    .stChatFloatingInputContainer {
        position: fixed !important;
        bottom: 0 !important;
        left: 0 !important;
        right: 0 !important;
        background: #f5f5f5 !important;
        padding: 20px !important;
        box-shadow: 0 -4px 20px rgba(0,0,0,0.15) !important;
        border-top: 2px solid #e0e0e0 !important;
        z-index: 999999 !important;
    }
    
    /* Style the input field itself - NO BORDER */
[data-testid="stChatInput"] input {
    border-radius: 24px !important;
    border: none !important;
    background: white !important;
    padding: 12px 20px !important;
    font-size: 16px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08) !important;
}

[data-testid="stChatInput"] input:focus {
    border: none !important;
    box-shadow: 0 0 0 3px rgba(255,107,53,0.15) !important;
    outline: none !important;
}
    
    /* Add huge bottom padding to main content area */
    .main .block-container {
        padding-bottom: 180px !important;
    }
    
    /* Ensure chat messages scroll properly */
    section[data-testid="stVerticalBlock"] {
        padding-bottom: 180px !important;
    }
    
    /* Hide default Streamlit footer that might overlap */
    footer {
        display: none !important;
    }
    
    /* Ensure sidebar doesn't overlap input */
    section[data-testid="stSidebar"] {
        z-index: 99999 !important;
    }
/* ══════════════════════════════════════════════════════════════
       STYLE FILE UPLOAD AS + ICON BUTTON
       ══════════════════════════════════════════════════════════════ */
    
    /* Hide the default file upload UI */
    [data-testid="stFileUploader"] {
        width: 50px !important;
        height: 50px !important;
    }
    
    [data-testid="stFileUploader"] > div {
        background: white !important;
        border-radius: 50% !important;
        width: 50px !important;
        height: 50px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        cursor: pointer !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
        transition: all 0.2s ease !important;
    }
    
    [data-testid="stFileUploader"] > div:hover {
        background: #FF6B35 !important;
        box-shadow: 0 4px 12px rgba(255,107,53,0.3) !important;
        transform: scale(1.05) !important;
    }
    
    /* Style the label as a + icon */
    [data-testid="stFileUploader"] label {
        font-size: 28px !important;
        font-weight: 300 !important;
        margin: 0 !important;
        color: #FF6B35 !important;
        cursor: pointer !important;
    }
    
    [data-testid="stFileUploader"] > div:hover label {
        color: white !important;
    }
    
    /* Hide the drag-drop text */
    [data-testid="stFileUploader"] section {
        display: none !important;
    }
    
    /* Position file uploader in fixed container */
    [data-testid="stFileUploader"] {
        position: fixed !important;
        bottom: 20px !important;
        left: 24px !important;
        z-index: 9999999 !important;
    }
</style>
""", unsafe_allow_html=True)

# ────── EXPIRATION WARNING BANNER ──────
expiring_items = []
expired_items = []

for item, days in st.session_state.inventory_expiry.items():
    if isinstance(days, (int, float)):
        if days <= 0:
            expired_items.append(f"{item} (expired {abs(days)} days ago)")
        elif days <= 3:
            expiring_items.append(f"{item} ({days} days left)")

if expired_items or expiring_items:
    if expired_items:
        banner_text = f"⚠️ Expired items: {', '.join(expired_items)}"
        banner_color = "#ffcccc"  # light red
    else:
        banner_text = f"⏰ Expiring soon: {', '.join(expiring_items)}"
        banner_color = "#fff3cd"  # light orange-yellow
    
    st.markdown(f"""
        <div style="
            background-color: {banner_color};
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 16px;
            text-align: center;
            font-weight: bold;
            color: #333;
        ">
            {banner_text} — Use them soon or remove from inventory!
        </div>
    """, unsafe_allow_html=True)
# Force custom PWA manifest to override Streamlit's default
st.markdown("""
    <link rel="manifest" href="/static/manifest.json">
    <meta name="theme-color" content="#FF6B6B">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Annapurna">
    <link rel="apple-touch-icon" href="/static/icon-192.png">
""", unsafe_allow_html=True)

# ═══ ADD HEADER FUNCTION HERE ═══
def render_header():
    """Renders attractive app header with branding"""
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #FF6B35 0%, #FFB07C 100%);
        padding: 24px 32px;
        border-radius: 0 0 24px 24px;
        box-shadow: 0 4px 20px rgba(255,107,53,0.2);
        margin: -1rem -1rem 2rem -1rem;
        text-align: center;
    ">
        <h1 style="
            color: white;
            font-size: 2.5rem;
            margin: 0;
            font-weight: 700;
            text-shadow: 0 2px 4px rgba(0,0,0,0.1);
        ">
            Annapurna 🍳
        </h1>
        <p style="
            color: rgba(255,255,255,0.95);
            font-size: 1.1rem;
            margin: 8px 0 0 0;
            font-weight: 400;
        ">
            Your AI-powered cooking companion
        </p>
    </div>
    """, unsafe_allow_html=True)
# ================= COMPLETE SIDEBAR SECTION =================

# Make sure theme is initialized early
if "theme" not in st.session_state:
    st.session_state.theme = "light"

def toggle_theme():
    st.session_state.theme = "dark" if st.session_state.theme == "light" else "light"
    st.rerun()  # crucial for style refresh

with st.sidebar:
    st.header("⚙️ Settings")
    # ──── USER INFO ────
    if st.session_state.get("user_email") and st.session_state.user_email != "guest@kitchenmate.app":
        st.write("👤 Logged in as:")
        st.caption(st.session_state.user_email)
    elif st.session_state.get("user_email") == "guest@kitchenmate.app":
        st.info("🚶 Guest Mode")

    st.markdown("---")

    # ──── FIREBASE STATUS ────
    st.caption("🔧 Firebase Status")
    try:
        db.collection("_health_check").document("test").get()
        st.success("✅ Connected")
    except Exception as e:
        st.error("❌ Not Connected")
        with st.expander("See Details"):
            st.write(str(e))

    st.markdown("---")

    # ──── VOICE ASSISTANT ────
    st.subheader("🎤 Voice Assistant")
    voice_enabled = st.toggle(
        "Enable Voice Input/Output",
        value=st.session_state.voice_enabled
    )
    st.session_state.voice_enabled = voice_enabled

    if st.session_state.voice_enabled:
        voice_lang = st.radio(
            "Voice Language",
            ["English", "Hindi", "Marathi"],
            key="voice_lang_select"
        )
        st.session_state.voice_language = voice_lang

    st.markdown("---")

    # ──── ALLERGIES ────
    st.session_state.allergies = st.text_input(
        "🚫 Your Allergies",
        value=st.session_state.allergies,
        placeholder="e.g., peanuts, dairy, shellfish",
        help="I'll avoid these in all recipe suggestions!"
    )

    st.markdown("---")

    # ──── DIET PREFERENCES ────
    st.subheader("🎛️ Diet Preferences")

    # Jain Mode
    new_jain_mode = st.toggle(
        "Jain Mode (No root vegetables)",
        value=st.session_state.jain_mode
    )
    if new_jain_mode != st.session_state.jain_mode:
        st.session_state.jain_mode = new_jain_mode
        st.rerun()

    # Pure Veg Mode
    pure_veg = st.toggle(
        "🌱 Pure Veg Mode",
        value=st.session_state.pure_veg_mode
    )
    if pure_veg != st.session_state.pure_veg_mode:
        st.session_state.pure_veg_mode = pure_veg
        st.rerun()

    # Health Mode
    health = st.toggle(
        "💪 Health Mode (Low oil, sugar)",
        value=st.session_state.health_mode
    )
    if health != st.session_state.health_mode:
        st.session_state.health_mode = health
        st.rerun()

    st.markdown("---")

    # ──── LANGUAGE MODE ────
    st.subheader("🗣️ Language")
    st.session_state.language_mode = st.radio(
        "Response Language",
        ["Hinglish", "English"],
        help="Choose how I should talk to you"
    )

    st.markdown("---")

    # ──── UNITS ────
    st.subheader("📏 Units")
    unit_choice = st.radio(
        "Preferred unit system",
        ["Metric (kg, g, ml)", "American (lbs, oz, cups)"],
        index=0 if st.session_state.unit_system == "metric" else 1
    )
    new_system = "metric" if "Metric" in unit_choice else "imperial"
    if new_system != st.session_state.unit_system:
        st.session_state.unit_system = new_system
        st.rerun()

    st.markdown("---")

    # ──── CUSTOM INGREDIENT ────
    st.subheader("➕ Custom Ingredient")

    with st.form("add_ingredient_form"):
        new_item = st.text_input("Ingredient Name", placeholder="e.g., basmati rice")
        
        col1, col2 = st.columns(2)
        with col1:
            new_qty = st.number_input("Quantity", min_value=0, step=50, value=500)
        with col2:
            unit_type = st.selectbox("Unit", ["g", "ml", "pcs"])

        new_price = st.number_input("Price per 100g/piece (₹)", min_value=0.0, step=1.0, value=0.0)

        submitted = st.form_submit_button("Add to Inventory", use_container_width=True)

        if submitted and new_item:
            key = new_item.lower().strip()
            st.session_state.inventory[key] = new_qty
            if new_price > 0:
                st.session_state.inventory_prices[key] = new_price
            st.success(f"✅ Added {new_item} ({new_qty}{unit_type})")
            st.rerun()

    # Remove ingredient
    if st.session_state.inventory:
        with st.expander("🗑️ Remove Ingredient"):
            remove_item = st.selectbox(
                "Select item to remove",
                [""] + sorted(list(st.session_state.inventory.keys()))
            )
            if remove_item and st.button("Remove", use_container_width=True):
                del st.session_state.inventory[remove_item]
                st.session_state.inventory_prices.pop(remove_item, None)
                st.session_state.inventory_expiry.pop(remove_item, None)
                st.success(f"🗑️ Removed {remove_item}")
                st.rerun()

    st.markdown("---")

    # ──── ROUTINE WEEKLY GROCERY ────
    st.subheader("🛍️ Routine Weekly Grocery")

    if "routine_grocery_items" not in st.session_state:
        st.session_state.routine_grocery_items = [
            "rice", "flour", "oil", "milk", "eggs",
            "vegetables", "spices", "fruits", "dal", "sugar"
        ]

    with st.expander("📝 Customize Routine Items"):
        st.write("**Current routine items:**")

        items_to_remove = []
        for item in st.session_state.routine_grocery_items:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"• {item.capitalize()}")
            with col2:
                if st.button("❌", key=f"remove_routine_{item}"):
                    items_to_remove.append(item)

        for item in items_to_remove:
            st.session_state.routine_grocery_items.remove(item)
            st.rerun()

        new_routine = st.text_input("Add new routine item", placeholder="e.g., bread")
        if st.button("Add") and new_routine:
            if new_routine.lower() not in st.session_state.routine_grocery_items:
                st.session_state.routine_grocery_items.append(new_routine.lower())
                st.success(f"Added {new_routine}")
                st.rerun()

    if st.button("🛒 Add Routine to Grocery List", use_container_width=True):
        st.session_state.grocery_list.update(st.session_state.routine_grocery_items)
        st.success(f"✅ Added {len(st.session_state.routine_grocery_items)} items!")
        st.rerun()

    st.markdown("---")

    # ──── SIGN OUT ────
    if st.button("🚪 Sign Out", use_container_width=True, type="primary"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.success("👋 Signed out successfully!")
        time.sleep(1)
        st.rerun()

    st.markdown("---")
    st.caption("Made by Manas")
    

# Call header
render_header()
# ═══ END HEADER ═══

# New chat button (optional - add before tabs)
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button("🆕 Start Fresh Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

tab1, tab2, tab3, tab4, tab5, tab6, tab_receipt, tab_ingredient_scan, tab_diet = st.tabs([
    "💬 Chat", "📅 Meal Planner", "🛒 Grocery & Inventory",
    "🍲 Custom Recipes", "🔥 Tried Recipes", "❤️ Favourite Recipes",
    "🧾 Receipt Scanner", "📸 Ingredient Scanner", "🥗 Diet Charts"
])

# ────────────── CHAT TAB ──────────────
with tab1:

    # ═══════════════════════════════════════════════════════
    # AUTO-REFRESH FOR VOICE COMMANDS (Non-blocking!)
    # ═══════════════════════════════════════════════════════
    st.subheader("💬 Chat with Annapurna")
   
    st.session_state.servings = st.number_input("Number of servings", min_value=1, max_value=10, value=st.session_state.servings, step=1)
   
    # ────────────── CONTINUOUS LISTENING MODE ──────────────
    if st.session_state.voice_enabled:
        st.markdown("---")
        st.subheader("🎤 Voice Assistant Mode")
        
        # Show status of external voice listener
        import os
        if True:  # Firebase is always available
            st.info("✅ **Firebase Voice Listener Ready** - Say 'Annapurna' on your computer!")
        else:
            st.warning("⚠️ Start voice listener on your computer: `python voice_listener_firebase.py`")
        
        col_listen1, col_listen2 = st.columns([3, 1])
        
        with col_listen1:
            if st.session_state.listening_status == "idle":
                status_text = "🟢 Ready - Click to start listening"
                status_color = "green"
            elif st.session_state.listening_status == "listening":
                status_text = "🔴 Listening for 'Annapurna'..."
                status_color = "red"
            elif st.session_state.listening_status == "recording":
                status_text = "🎙️ Recording your command..."
                status_color = "orange"
            elif st.session_state.listening_status == "processing":
                status_text = "⚙️ Processing..."
                status_color = "blue"
            else:
                status_text = "⚠️ Error"
                status_color = "gray"
            
            st.markdown(f"**Status:** <span style='color:{status_color}; font-size: 18px;'>{status_text}</span>", unsafe_allow_html=True)
        
        with col_listen2:
            if not st.session_state.listening_active:
                if st.button("🎤 Start Listening", type="primary"):
                    start_continuous_listening()
                    st.rerun()
            else:
                if st.button("⏹️ Stop Listening", type="secondary"):
                    stop_continuous_listening()
                    st.rerun()
        

        # Check for voice commands in queue
# ═══════════════════════════════════════════════════════════════
# CHECK FOR VOICE COMMANDS FROM EXTERNAL LISTENER
# ═══════════════════════════════════════════════════════════════
def check_voice_commands_from_firebase():
    """Check if voice listener has sent any commands via Firebase"""
    try:
        # Query for unprocessed commands, ordered by timestamp
        commands_ref = db.collection('voice_commands').where('processed', '==', False).order_by('created_at').limit(1)
        docs = commands_ref.get()
        
        for doc in docs:
            command_data = doc.to_dict()
            command_text = command_data.get('text', '')
            
            # Mark as processed
            doc.reference.update({'processed': True})
            
            return command_text
    except Exception as e:
        # Silently fail if Firebase not available or error occurs
        pass
    
    return None

# Check for voice commands from external listener (Firebase-based)
voice_command_from_file = check_voice_commands_from_firebase()

# Store in session state if detected
if voice_command_from_file:
    st.session_state.pending_voice_command = voice_command_from_file
    st.success(f"🎤 Voice Command Detected: **{voice_command_from_file}**")
    # Force immediate rerun to process the command
    st.rerun()

# Check for voice commands in queue (old threading method - keeping for manual button)
if st.session_state.new_command_available and not st.session_state.voice_command_queue.empty():
    queue_prompt = st.session_state.voice_command_queue.get()
    st.session_state.pending_voice_command = queue_prompt
    st.success(f"👂 Heard: **{queue_prompt}**")
    
    # Reset flags
    st.session_state.new_command_available = False
    st.session_state.listening_status = "listening"
    # Force rerun
    st.rerun()

# Auto-refresh while listening (less frequent to reduce load)
if st.session_state.listening_active and st.session_state.listening_status in ["listening", "recording"]:
    time.sleep(1)  # Increased from 0.5 to 1 second
    st.rerun()

# Automatic voice command polling using st_autorefresh
# Only runs when voice is enabled - provides smooth voice command detection
if st.session_state.voice_enabled:
    # Refresh every 3 seconds to check for voice commands
    # This won't interfere with chat input as long as user isn't actively typing
    st_autorefresh(interval=3000, key="voice_poll_refresh")

# Show error if any
if st.session_state.listening_error:
    st.error(f"❌ Listening error: {st.session_state.listening_error}")
    if st.button("Clear Error"):
        st.session_state.listening_error = None
        st.rerun()

st.markdown("---")
st.info("💡 **How to use:** Click 'Start Listening', then say 'Annapurna' followed by your question!")

    # Show chat history
for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
   
    # Voice Input Section
video_id = None

# Show chat history with custom styling
for msg in st.session_state.messages:
    display_message(msg["role"], msg["content"])
# ────────────────────────────────────────────────
# FIXED CHAT INPUT + FILE UPLOAD BUTTON ON LEFT
# ────────────────────────────────────────────────

# 1. ULTRA-AGGRESSIVE CSS TO REMOVE ALL WHITE BACKGROUNDS
st.markdown("""
<style>
    /* ═══════════════════════════════════════════════════════ */
    /* NUCLEAR OPTION: REMOVE ALL WHITE BACKGROUNDS */
    /* ═══════════════════════════════════════════════════════ */
    
    /* Force dark theme globally */
    .stApp {
        background-color: #0E1117 !important;
    }
    
    /* Remove ALL white backgrounds from Streamlit elements */
    .main, .block-container, section, div[data-testid="stVerticalBlock"],
    div[data-testid="stHorizontalBlock"], .element-container {
        background-color: transparent !important;
    }
    
    /* Chat messages - COMPLETE transparency */
    .stChatMessage {
        background-color: transparent !important;
        background: transparent !important;
    }
    
    /* Chat message content - subtle colored tint */
    [data-testid="stChatMessageContent"] {
        background-color: rgba(28, 131, 225, 0.08) !important;
        background: rgba(28, 131, 225, 0.08) !important;
        border-radius: 16px !important;
        padding: 12px 18px !important;
        border: 1px solid rgba(28, 131, 225, 0.15) !important;
    }
    
    /* User messages - Blue */
    div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageContent"]) {
        background-color: transparent !important;
    }
    
    /* Force user message style */
    .stChatMessage:nth-child(odd) [data-testid="stChatMessageContent"] {
        background-color: rgba(28, 131, 225, 0.12) !important;
        border-color: rgba(28, 131, 225, 0.25) !important;
    }
    
    /* Force assistant message style */
    .stChatMessage:nth-child(even) [data-testid="stChatMessageContent"] {
        background-color: rgba(255, 107, 53, 0.08) !important;
        border-color: rgba(255, 107, 53, 0.2) !important;
    }
    
    /* ═══════════════════════════════════════════════════════ */
    /* CHAT INPUT AREA - REMOVE WHITE CONTAINER */
    /* ═══════════════════════════════════════════════════════ */
    
    /* Chat input container */
    .stChatInputContainer, [data-testid="stChatInputContainer"] {
        background-color: transparent !important;
        background: transparent !important;
        border-top: 1px solid rgba(250, 250, 250, 0.1) !important;
    }
    
    /* Pinned bottom chat container - DARK */
    .pinned-chat-bar {
        position: fixed !important;
        bottom: 0 !important;
        left: 0 !important;
        right: 0 !important;
        background: rgba(14, 17, 23, 0.98) !important;  /* Match Streamlit dark */
        padding: 16px 24px !important;
        box-shadow: 0 -6px 24px rgba(0,0,0,0.5) !important;
        border-top: 1px solid rgba(255, 107, 53, 0.2) !important;
        z-index: 999 !important;
        display: flex !important;
        align-items: center !important;
        gap: 12px !important;
        backdrop-filter: blur(10px) !important;
    }

    /* Main content padding */
    .main .block-container {
        padding-bottom: 140px !important;
        background-color: transparent !important;
    }

    /* ═══════════════════════════════════════════════════════ */
    /* FUNCTIONAL FILE UPLOAD BUTTON */
    /* ═══════════════════════════════════════════════════════ */
    
    /* Make the actual file uploader button beautiful */
    [data-testid="stFileUploader"] {
        width: 50px !important;
        height: 50px !important;
    }
    
    /* ═══════════════════════════════════════════════════════ */
    /* CHAT INPUT BOX */
    /* ═══════════════════════════════════════════════════════ */

    /* Chat input */
    [data-testid="stChatInput"] {
        flex: 1 !important;
    }

    [data-testid="stChatInput"] > div {
        border-radius: 999px !important;
        border: 2px solid rgba(255, 176, 124, 0.3) !important;
        background: rgba(255, 248, 240, 0.05) !important;
        transition: all 0.2s;
    }
    
    [data-testid="stChatInput"] > div:focus-within {
        border-color: rgba(255, 107, 53, 0.5) !important;
        box-shadow: 0 0 0 3px rgba(255, 107, 53, 0.1) !important;
        background: rgba(255, 248, 240, 0.08) !important;
    }

    [data-testid="stChatInput"] input {
        border: none !important;
        background: transparent !important;
        color: #b0b0b0 !important;
    }
    
    [data-testid="stChatInput"] input::placeholder {
        color: #808080 !important;
    }

    [data-testid="stChatInput"] input:focus {
        box-shadow: 0 0 0 3px rgba(255,107,53,0.2) !important;
        outline: none !important;
    }
    
    /* ═══════════════════════════════════════════════════════ */
    /* REMOVE WHITE FROM OTHER ELEMENTS */
    /* ═══════════════════════════════════════════════════════ */
    
    /* Info boxes */
    .stInfo, .stSuccess, .stWarning, .stError {
        background-color: rgba(28, 131, 225, 0.1) !important;
    }
    
    /* Expanders */
    .streamlit-expanderHeader {
        background-color: transparent !important;
    }
    
    /* Buttons */
    .stButton > button {
        background-color: transparent !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
    }
    
    /* Fixed chat input container at bottom */
    .stChatInputContainer {
        position: fixed !important;
        bottom: 0 !important;
        left: 0 !important;
        right: 0 !important;
        background: linear-gradient(to top, rgba(14, 17, 23, 1) 80%, rgba(14, 17, 23, 0)) !important;
        padding: 20px 16px 10px 16px !important;
        z-index: 999 !important;
        border-top: 1px solid rgba(250, 250, 250, 0.1) !important;
    }
    
    /* Chat messages container - add bottom padding */
    [data-testid="stChatMessage"] {
        margin-bottom: 10px !important;
    }
    
    /* Last message visible above input */
    .main .block-container {
        padding-bottom: 150px !important;
    }
    
    /* Chat input styling */
    .stChatInput textarea {
        background-color: rgba(28, 31, 38, 0.6) !important;
        border: 1px solid rgba(250, 250, 250, 0.1) !important;
        border-radius: 12px !important;
        color: #b0b0b0 !important;
    }
    
    .stChatInput textarea::placeholder {
        color: #808080 !important;
    }
    
    /* File uploader button - Orange + style */
    [data-testid="stFileUploader"] button {
        background: linear-gradient(135deg, #FF6B35 0%, #FF8C42 100%) !important;
        border: none !important;
        border-radius: 50% !important;
        width: 42px !important;
        height: 42px !important;
        min-width: 42px !important;
        padding: 0 !important;
        box-shadow: 0 4px 12px rgba(255, 107, 53, 0.3) !important;
        transition: all 0.2s ease !important;
    }
    
    [data-testid="stFileUploader"] button:hover {
        transform: scale(1.05) !important;
        box-shadow: 0 6px 16px rgba(255, 107, 53, 0.4) !important;
    }
    
    [data-testid="stFileUploader"] button span {
        display: none !important;
    }
    
    [data-testid="stFileUploader"] button::before {
        content: "+" !important;
        font-size: 24px !important;
        color: white !important;
        display: block !important;
        line-height: 42px !important;
    }
    
    [data-testid="stFileUploader"] {
        width: 50px !important;
    }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# FIXED CHAT INPUT + FILE UPLOAD BAR (Bottom-Pinned Layout)
# ═══════════════════════════════════════════════════════════════

# Create columns: small for upload button, large for chat input
col_upload, col_input = st.columns([0.06, 0.94])

with col_upload:
    # Orange + button for file upload
    uploaded_file = st.file_uploader(
        label="📎",
        type=["jpg", "jpeg", "png", "pdf", "txt"],
        accept_multiple_files=False,
        key="pinned_file_uploader",
        label_visibility="collapsed"
    )

with col_input:
    # Chat input
    chat_input_prompt = st.chat_input(
        placeholder="🔍 Ask me anything... recipes, substitutes, tips...",
        key="main_chat_input"
    )


# Priority: voice command > chat input
if st.session_state.get('pending_voice_command'):
    prompt = st.session_state.pending_voice_command
    # Clear it so it doesn't reprocess
    st.session_state.pending_voice_command = None
elif chat_input_prompt:
    prompt = chat_input_prompt
else:
    prompt = None

# ═══════════════════════════════════════════════════════════════
# FILE UPLOAD HANDLING
# ═══════════════════════════════════════════════════════════════

if uploaded_file is not None:
    st.session_state.messages.append({
        "role": "user",
        "content": f"Uploaded: **{uploaded_file.name}**"
    })

    with st.chat_message("user"):
        st.markdown(f"Uploaded: **{uploaded_file.name}**")
        if uploaded_file.type.startswith("image/"):
            st.image(uploaded_file)
        else:
            st.write("PDF uploaded")

    with st.chat_message("assistant"):
        with st.spinner("Analyzing file... 📊"):
            chart_text = ""

            # Extract text from file
            if uploaded_file.type == "application/pdf":
                try:
                    pdf_reader = PyPDF2.PdfReader(BytesIO(uploaded_file.read()))
                    for page in pdf_reader.pages:
                        chart_text += page.extract_text() + "\n"
                except Exception as e:
                    chart_text = f"Error reading PDF: {str(e)}"
            else:
                chart_text = "Image uploaded - text extraction pending OCR implementation"

            # Decide if it's a diet chart or receipt based on filename
            is_receipt = any(word in uploaded_file.name.lower() for word in ["receipt", "bill", "grocery", "kiranastore"])

            if is_receipt:
                analysis_prompt = f"""
                You are a smart grocery receipt scanner.
                Extract ALL food items, quantities and prices from this receipt text:
                {chart_text[:4000]}

                Output format (only this, no extra text):
                Item name | Quantity | Unit | Price (₹)
                Paneer | 500 | g | 180
                Tomatoes | 2 | kg | 80
                ...

                Skip non-food items (soap, bags, etc.).
                Use standard units (g, kg, ml, L, pcs).
                """
            else:
                analysis_prompt = f"""
                You are a nutrition & fitness expert. Analyze this gym diet chart text:
                {chart_text[:4000]}

                Extract and summarize in this structured format:
                Daily Calories: X kcal
                Protein target: X g
                Carbs: X g / Low/Medium/High
                Fats: X g
                Meals per day: X
                Key rules / foods to avoid: ...
                Special notes / restrictions: ...

                Return ONLY the structured summary - no extra text.
                """

            try:
                response = client.chat.completions.create(
                    messages=[{"role": "user", "content": analysis_prompt}],
                    model="llama-3.3-70b-versatile",
                    temperature=0.4,
                    max_tokens=500
                )
                summary = response.choices[0].message.content.strip()

                # Editable summary
                st.markdown("**AI Analysis (edit if needed):**")
                edited_summary = st.text_area(
                    label="",
                    value=summary,
                    height=180,
                    key=f"edit_{uploaded_file.name}_{int(time.time())}"  # unique key
                )

                col1, col2 = st.columns(2)

                if col1.button("💾 Save / Add to Inventory"):
                    if is_receipt:
                        add_items_from_receipt(edited_summary)
                    else:
                        st.session_state.gym_diet_chart = edited_summary
                        if not st.session_state.user_email.startswith("guest"):
                            db.collection("users").document(st.session_state.user_id).set({
                                "gym_diet_chart": edited_summary,
                                "chart_updated": datetime.now().isoformat()
                            }, merge=True)
                        st.success("Saved!")

                if col2.button("📅 Generate Weekly Plan" if not is_receipt else "➕ Add Missing Items"):
                    if is_receipt:
                        add_missing_items_from_receipt(edited_summary)
                    else:
                        generate_weekly_plan_from_chart(edited_summary)

            except Exception as e:
                st.error(f"Analysis failed: {str(e)}")
                st.info("Try uploading again or paste text manually.")
    # Manual voice recording (if not using continuous mode)

if st.session_state.voice_enabled and not st.session_state.listening_active and not video_id and not prompt:
        st.markdown("#### Or Record Manually:")
        col_v1, col_v2 = st.columns([4, 1])
        with col_v1:
            audio_input = st.audio_input("🎤 Record your question...")
        with col_v2:
            st.write("")  # spacing
            process_voice = st.button("🎙️ Send Voice")
        
        if process_voice and audio_input:
            with st.spinner("🎧 Listening..."):
                audio_bytes = audio_input.getvalue()
                prompt = transcribe_audio(audio_bytes)
                
                if prompt:
                    st.success(f"👂 You said: **{prompt}**")
                else:
                    st.error("❌ Could not understand. Please speak clearly.")
    
    # ────────────── YOUTUBE VIDEO PROCESSING ──────────────
if video_id:
        st.session_state.processing_video = True
        
        with st.chat_message("user"):
            st.markdown(f"🎥 YouTube Video Link")
        
        with st.chat_message("assistant"):
            with st.spinner("📹 Analyzing video..."):
                
                # Step 1: Get video description using YouTube API
                video_data, error = get_video_description(video_id)
                
                if error:
                    st.error(f"❌ {error}")
                    if "API key" in error:
                        st.info("""
                        **How to add YouTube API key:**
                        1. Get key from: https://console.cloud.google.com
                        2. Find this line in code: `YOUTUBE_API_KEY = ""`
                        3. Replace with: `YOUTUBE_API_KEY = "YOUR_KEY_HERE"`
                        """)
                    st.session_state.processing_video = False
                    st.stop()
                
                video_title = video_data['title']
                description = video_data['description']
                
                st.markdown(f"**Video:** {video_title}")
                
                # Step 2: Check if description has ingredients
                if len(description) > 100:
                    st.info("📝 Found detailed description!")
                    
                    # Step 3: Extract recipe links from description
                    recipe_links = extract_recipe_links(description)
                    
                    scraped_content = ""
                    if recipe_links:
                        st.info(f"🔗 Found recipe link: {recipe_links[0][:50]}...")
                        with st.spinner("🌐 Fetching recipe from link..."):
                            scraped_content = scrape_recipe_from_url(recipe_links[0])
                            if scraped_content:
                                st.success("✅ Recipe page loaded!")
                    
                    # Step 4: Parse recipe from description + scraped content
                    with st.spinner("🤖 Extracting exact ingredients..."):
                        recipe = parse_recipe_from_description(description, scraped_content, video_title)
                        st.markdown(recipe)
                        
                        st.session_state.last_recipe = recipe
                        st.session_state.video_recipe = recipe
                        st.session_state.messages.append({"role": "user", "content": f"YouTube: {video_title}"})
                        st.session_state.messages.append({"role": "assistant", "content": recipe})
                        
                        # Voice output
                        if st.session_state.voice_enabled:
                            lang_code = "hi" if st.session_state.voice_language == "Hindi" else "en"
                            audio_fp = text_to_speech(recipe, lang_code)
                            if audio_fp:
                                st.audio(audio_fp, format="audio/mp3", autoplay=False)
                
                else:
                    # Fallback to transcript if description is too short
                    st.info("📝 Description is short, trying transcript...")
                    transcript = extract_youtube_transcript(video_id)
                    
                    if transcript:
                        st.success("✅ Transcript extracted!")
                        with st.spinner("🤖 Converting transcript to recipe..."):
                            recipe = parse_recipe_from_transcript(transcript, video_title)
                            st.markdown(recipe)
                            
                            st.session_state.last_recipe = recipe
                            st.session_state.video_recipe = recipe
                            st.session_state.messages.append({"role": "user", "content": f"YouTube: {video_title}"})
                            st.session_state.messages.append({"role": "assistant", "content": recipe})
                            
                            if st.session_state.voice_enabled:
                                lang_code = "hi" if st.session_state.voice_language == "Hindi" else "en"
                                audio_fp = text_to_speech(recipe, lang_code)
                                if audio_fp:
                                    st.audio(audio_fp, format="audio/mp3", autoplay=False)
                    else:
                        st.warning("⚠️ No transcript or description available.")
                        st.info("💡 Try asking me to suggest a similar recipe instead!")
        
        st.session_state.processing_video = False
        st.rerun()
   
if prompt:
        st.session_state.show_cooking_check = False
        st.session_state.show_nutrition = False
        st.session_state.show_substitutes = False
        st.session_state.ingredients_shown = False
       
        # Smart prompt enhancement for short commands
        # If user just says a dish name (1-3 words, no question words), make it a recipe request
        prompt_lower = prompt.lower().strip()
        question_words = ['how', 'what', 'why', 'when', 'where', 'can', 'should', 'make', 'cook', 'prepare', 'recipe', 'give', 'tell', 'show']
        word_count = len(prompt_lower.split())
        
        # If it's a short phrase (1-3 words) without question words, assume they want a recipe
        if word_count <= 3 and not any(qword in prompt_lower for qword in question_words):
            enhanced_prompt = f"Give me the complete recipe for {prompt} with all ingredients and step-by-step instructions."
            st.info(f"💡 Understood: You want a recipe for **{prompt}**")
        else:
            enhanced_prompt = prompt
       
        allergy_note = f"User allergies: {st.session_state.allergies}. Avoid these!" if st.session_state.allergies else ""
        full_prompt = enhanced_prompt + " " + allergy_note
        if st.session_state.servings > 1:
            full_prompt += f" (for {st.session_state.servings} people)"
       
        st.session_state.messages.append({"role": "user", "content": full_prompt})
        with st.chat_message("user"):
            st.markdown(enhanced_prompt)  # Show enhanced version, not original
        with st.chat_message("assistant"):
            with st.spinner(random.choice([
    "Simmering your recipe… 🍲",
    "Chopping ingredients… 🔪",
    "Mixing flavors… 🥄",
    "Heating the pan… 🍳",
    "Tasting for perfection… 👨‍🍳"
])):
    # your streaming code here
                try:
                    stream = client.chat.completions.create(
                        messages=[{"role": "system", "content": get_system_prompt()}, *st.session_state.messages],
                        model="llama-3.3-70b-versatile",
                        temperature=0.75,
                        max_tokens=700,
                        stream=True
                    )
                    response = ""
                    placeholder = st.empty()
                    for chunk in stream:
                        if chunk.choices[0].delta.content:
                            response += chunk.choices[0].delta.content
                            placeholder.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    st.session_state.last_recipe = response
                   
                    if st.session_state.voice_enabled and response:
                        lang_code = "hi" if st.session_state.voice_language == "Hindi" else "en"
                        audio_fp = text_to_speech(response, lang_code)
                        if audio_fp:
                            st.audio(audio_fp, format="audio/mp3", autoplay=False)
                    # Resume listening if in continuous mode
                    if st.session_state.listening_active:
                        time.sleep(2)
                        st.session_state.listening_status = "listening"
                        st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")
                    if st.session_state.listening_active:
                        st.session_state.listening_status = "listening"
    
if st.button("😴 Feeling Lazy? Suggest from Inventory"):
    inventory_str = ", ".join(st.session_state.inventory.keys())
    lazy_prompt = f"Suggest a simple recipe using only these ingredients: {inventory_str}. Keep it easy and quick."
    
    st.session_state.messages.append({"role": "user", "content": lazy_prompt})
    
    with st.chat_message("user"):
        st.markdown(lazy_prompt)
    
    with st.chat_message("assistant"):
        with st.spinner(random.choice([
            "Simmering your recipe… 🍲",
            "Chopping ingredients… 🔪",
            "Mixing flavors… 🥄",
            "Heating the pan… 🍳",
            "Tasting for perfection… 👨‍🍳"
        ])):
            try:
                stream = client.chat.completions.create(
                    messages=[{"role": "system", "content": get_system_prompt()}, *st.session_state.messages],
                    model="llama-3.3-70b-versatile",
                    temperature=0.75,
                    max_tokens=700,
                    stream=True
                )
                
                response = ""
                placeholder = st.empty()
                
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        response += chunk.choices[0].delta.content
                        placeholder.markdown(response)
                
                # Save the final response
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.session_state.last_recipe = response
                
                # Voice output if enabled
                if st.session_state.voice_enabled and response:
                    lang_code = "hi" if st.session_state.voice_language == "Hindi" else "en"
                    audio_fp = text_to_speech(response, lang_code)
                    if audio_fp:
                        st.audio(audio_fp, format="audio/mp3", autoplay=False)
                
                # Resume continuous listening if active
                if st.session_state.listening_active:
                    time.sleep(2)
                    st.session_state.listening_status = "listening"
                    st.rerun()
                    
            except Exception as e:
                st.error(f"Error: {str(e)}")
                if st.session_state.listening_active:
                    st.session_state.listening_status = "listening"
   
if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
    col1, col2, col3, col4 = st.columns([2,2,2,2])
    with col1:
        if st.button("🍳 Start Cooking"):
            # Auto-extract ingredients from recipe
            auto_ingredients = auto_extract_ingredients_from_recipe(st.session_state.last_recipe)
            
            if not auto_ingredients:
                st.error("❌ Could not detect ingredients. Try rephrasing the recipe.")
            else:
                # Check which are missing from inventory
                missing_items = []
                for item in auto_ingredients:
                    found = False
                    for inv_key in st.session_state.inventory:
                        if inv_key in item or item in inv_key:
                            found = True
                            break
                    if not found:
                        missing_items.append(item)
                
                # Store for later use
                st.session_state.detected_ingredients = auto_ingredients
                st.session_state.missing_ingredients = missing_items
                st.session_state.show_cooking_check = True
                st.session_state.show_nutrition = False
                st.session_state.show_substitutes = False
                st.rerun()
    
    with col2:
        if st.button("🥗 Calculate Nutrition"):
            st.session_state.show_nutrition = True
            st.session_state.show_cooking_check = False
            st.session_state.show_substitutes = False
            st.rerun()
    
    with col3:
        if st.button("❤️ Favourite"):
            recipe_name = f"Recipe {len(st.session_state.favourite_recipes) + 1}"
            st.session_state.favourite_recipes[recipe_name] = st.session_state.last_recipe
            st.success(f"Added to Favourites: {recipe_name}")
    
    with col4:
        if st.button("🔄 Substitutes"):
            st.session_state.show_substitutes = True
            st.session_state.show_cooking_check = False
            st.session_state.show_nutrition = False
            st.rerun()
    
    # ═══ RECIPE FORMATTER (keep this as-is) ═══
    if st.session_state.last_recipe:
        st.markdown("---")
        format_recipe(st.session_state.last_recipe)
   
if st.session_state.show_cooking_check and not st.session_state.cooking_mode:
    st.markdown("---")
    st.subheader("🍳 Ingredient Check")
    
    # Use pre-detected ingredients
    detected_ingredients = st.session_state.get('detected_ingredients', [])
    missing = st.session_state.get('missing_ingredients', [])
    
    if not detected_ingredients:
        st.error("❌ No ingredients detected. Please try again.")
        if st.button("Close"):
            st.session_state.show_cooking_check = False
            st.rerun()
    else:
        # ⭐ JAIN MODE WARNING ⭐
        if st.session_state.jain_mode:
            non_jain = [item for item in detected_ingredients if not is_jain_compatible(item)]
            if non_jain:
                st.warning(f"⚠️ **Jain Alert:** This recipe contains: {', '.join(non_jain)}")
                st.info("**Suggested substitutes:**")
                for item in non_jain:
                    substitute = get_jain_substitute(item)
                    st.write(f"• {item.capitalize()} → {substitute}")
                st.markdown("---")
        
        # Show all ingredients with availability status
        st.write("### Detected Ingredients:")
        for item in detected_ingredients:
            found = False
            for inv_key in st.session_state.inventory:
                if inv_key in item or item in inv_key:
                    found = True
                    current_qty = st.session_state.inventory[inv_key]
                    status, color = get_quantity_status(current_qty)
                    st.markdown(f"✅ **{item.capitalize()}**: Available <span style='color:{color};'>[{status}]</span>", unsafe_allow_html=True)
                    break
            if not found:
                st.markdown(f"❌ **{item.capitalize()}**: Missing")
        
        st.markdown("---")
        
        # Handle missing ingredients
        if missing:
            st.error(f"**⚠️ Missing {len(missing)} ingredients:**")
            st.write(", ".join([m.capitalize() for m in missing]))
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("❌ Cancel Cooking"):
                    st.session_state.show_cooking_check = False
                    st.rerun()
            
            with col2:
                if st.button("➕ Add to Grocery List"):
                    for item in missing:
                        st.session_state.grocery_list.add(item.lower())
                    st.success(f"✅ Added {len(missing)} items to grocery list!")
                    st.session_state.show_cooking_check = False
                    st.rerun()
            
            with col3:
                if st.button("🍳 Cook Anyway"):
                    # Extract steps and start cooking
                    st.session_state.cooking_steps = extract_steps(st.session_state.last_recipe)
                    if st.session_state.cooking_steps:
                        st.session_state.cooking_mode = True
                        st.session_state.current_step = 0
                        st.session_state.show_cooking_check = False
                        st.rerun()
                    else:
                        st.error("Could not extract cooking steps from recipe")
        
        else:
            # All ingredients available
            st.success("✅ All ingredients available! Ready to start?")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("❌ Cancel"):
                    st.session_state.show_cooking_check = False
                    st.rerun()
            
            with col2:
                if st.button("👨‍🍳 Start Step-by-Step Cooking", type="primary"):
                    st.session_state.cooking_steps = extract_steps(st.session_state.last_recipe)
                    if st.session_state.cooking_steps:
                        st.session_state.cooking_mode = True
                        st.session_state.current_step = 0
                        st.session_state.show_cooking_check = False
                        st.rerun()
                    else:
                        st.error("Could not extract steps from recipe")

if st.session_state.show_nutrition and not st.session_state.cooking_mode:
        st.markdown("---")
        st.subheader(f"🥗 Nutrition per {st.session_state.servings} serving(s)")
        with st.spinner("Calculating nutrition..."):
            try:
                stream = client.chat.completions.create(
                    messages=[{"role": "system", "content": get_nutrition_prompt(st.session_state.servings)},
                              {"role": "user", "content": st.session_state.last_recipe}],
                    model="llama-3.3-70b-versatile",
                    temperature=0.5,
                    max_tokens=500,
                    stream=True
                )
                response = ""
                placeholder = st.empty()
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        response += chunk.choices[0].delta.content
                        placeholder.markdown(response)
                
                if st.session_state.voice_enabled and response:
                    lang_code = "hi" if st.session_state.voice_language == "Hindi" else "en"
                    audio_fp = text_to_speech(response, lang_code)
                    if audio_fp:
                        st.audio(audio_fp, format="audio/mp3", autoplay=False)
            except Exception as e:
                st.error(f"Error: {str(e)}")
        if st.button("Close Nutrition"):
            st.session_state.show_nutrition = False
            st.rerun()

if st.session_state.show_substitutes and not st.session_state.cooking_mode:
        st.markdown("---")
        st.subheader("🔄 Ingredient Substitutes")
        ingredients = extract_ingredients(st.session_state.last_recipe)
        missing = [ing['name'] for ing in ingredients if not any(k in ing['name'] or ing['name'] in k for k in st.session_state.inventory)]
        if missing:
            st.markdown(f"**Finding alternatives for:** {', '.join(missing)}")
            with st.spinner("Looking for Indian alternatives..."):
                try:
                    sub_prompt = f"Practical Indian substitutes for: {', '.join(missing)}. One or two options each."
                    stream = client.chat.completions.create(
                        messages=[{"role": "user", "content": sub_prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.6,
                        max_tokens=400,
                        stream=True
                    )
                    resp = ""
                    placeholder = st.empty()
                    for chunk in stream:
                        if chunk.choices[0].delta.content:
                            resp += chunk.choices[0].delta.content
                            placeholder.markdown(resp)
                    
                    if st.session_state.voice_enabled and resp:
                        lang_code = "hi" if st.session_state.voice_language == "Hindi" else "en"
                        audio_fp = text_to_speech(resp, lang_code)
                        if audio_fp:
                            st.audio(audio_fp, format="audio/mp3", autoplay=False)
                except Exception as e:
                    st.error(str(e))
        else:
            st.info("No missing ingredients!")
        if st.button("Close Substitutes"):
            st.session_state.show_substitutes = False
            st.rerun()

    # ────────────── COOKING MODE ──────────────
if st.session_state.cooking_mode:
        st.markdown("---")
        st.subheader("👨‍🍳 Step-by-Step Cooking Guide")
        
        if st.session_state.cooking_steps:
            total_steps = len(st.session_state.cooking_steps)
            current = st.session_state.current_step
            
            st.markdown(f"### Step {current + 1} of {total_steps}")
            step_text = st.session_state.cooking_steps[current]
            st.markdown(f"**{step_text}**")
            
        
        # Voice output for step (already there, but ensure autoplay)
        if st.session_state.voice_enabled:
            lang_code = "hi" if st.session_state.voice_language == "Hindi" else "en"
            audio_fp = text_to_speech(step_text, lang_code)
            if audio_fp:
                st.audio(audio_fp, format="audio/mp3", autoplay=True)  # ← autoplay=True
            # ───── NEW: TIMER FEATURE ─────
        # Parse time from step text
        time_pattern = r'(?:for|about|around|approximately)?\s*(\d+(?:\.\d+)?)\s*(minute|minutes|min|hour|hours|hr|second|seconds|sec|overnight)'
        match = re.search(time_pattern, step_text.lower())
        
        timer_key = f"timer_{current}"
        if match:
            amount = float(match.group(1))
            unit = match.group(2).lower()
            
            if unit in ["minute", "minutes", "min"]:
                seconds = int(amount * 60)
            elif unit in ["hour", "hours", "hr"]:
                seconds = int(amount * 3600)
            elif unit in ["second", "seconds", "sec"]:
                seconds = int(amount)
            elif unit == "overnight":
                seconds = 8 * 3600  # rough 8 hours
            else:
                seconds = 0
            
            if seconds > 0:
                st.markdown(f"**Suggested timer:** {amount} {unit}")
                
                if f"timer_running_{current}" not in st.session_state:
                    st.session_state[f"timer_running_{current}"] = False
                    st.session_state[f"timer_remaining_{current}"] = seconds
                
                col_timer1, col_timer2 = st.columns([3, 1])
                with col_timer1:
                    if not st.session_state[f"timer_running_{current}"]:
                        if st.button("⏱️ Start Timer"):
                            st.session_state[f"timer_running_{current}"] = True
                            st.session_state[f"timer_start_{current}"] = time.time()
                            st.rerun()
                    else:
                        elapsed = time.time() - st.session_state[f"timer_start_{current}"]
                        remaining = max(0, st.session_state[f"timer_remaining_{current}"] - elapsed)
                        
                        if remaining > 0:
                            progress = 1 - (remaining / st.session_state[f"timer_remaining_{current}"])
                            st.progress(progress)
                            mins, secs = divmod(int(remaining), 60)
                            st.markdown(f"**Time left:** {mins:02d}:{secs:02d}")
                            st.rerun()  # auto-refresh every second
                        else:
                            st.success("🎉 Time's up!")
                            st.balloons()
                            st.session_state[f"timer_running_{current}"] = False
                            # Play beep sound (browser alert sound)
                            st.markdown(
                                '<audio autoplay><source src="data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=" type="audio/wav"></audio>',
                                unsafe_allow_html=True
                            )
                
                with col_timer2:
                    if st.session_state[f"timer_running_{current}"]:
                        if st.button("Pause"):
                            st.session_state[f"timer_remaining_{current}"] -= (time.time() - st.session_state[f"timer_start_{current}"])
                            st.session_state[f"timer_running_{current}"] = False
                            st.rerun()
                        if st.button("Reset"):
                            st.session_state[f"timer_running_{current}"] = False
                            st.rerun()
        
        # ───── END OF TIMER FEATURE ─────
            # Step controls
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("⬅️ Previous" if current > 0 else "⬅️ First"):
                    if current > 0:
                        st.session_state.current_step -= 1
                        st.rerun()
            
            with col2:
                if st.button("🔄 Repeat"):
                    if st.session_state.voice_enabled:
                        lang_code = "hi" if st.session_state.voice_language == "Hindi" else "en"
                        audio_fp = text_to_speech(step_text, lang_code)
                        if audio_fp:
                            st.audio(audio_fp, format="audio/mp3", autoplay=True)
                    st.info(f"🔄 Repeating: {step_text}")
            
            with col3:
                if st.button("➡️ Next" if current < total_steps - 1 else "✅ Done!"):
                    if current < total_steps - 1:
                        st.session_state.current_step += 1
                        st.rerun()
                    else:
                        st.session_state.cooking_mode = False
                        st.session_state.current_step = 0
                        st.session_state.cooking_steps = []
                        st.rerun()
            
            with col4:
                if st.button("⛔ Exit Cooking"):
                    st.session_state.cooking_mode = False
                    st.session_state.current_step = 0
                    st.session_state.cooking_steps = []
                    st.session_state.show_cooking_check = False
                    st.rerun()
            
            # Voice commands if enabled
            if st.session_state.voice_enabled:
                st.markdown("---")
st.info("🎤 Say: next, previous, repeat, start timer, pause timer, resume timer, reset timer, done")

if st.button("🎤 Voice Command", type="primary"):
        with st.spinner("Listening..."):
            audio_input = st.audio_input("Speak now (next / repeat / timer commands)...")
            if audio_input:
                audio_bytes = audio_input.getvalue()
                command = transcribe_audio(audio_bytes)
                
                if command:
                    command = command.lower().strip()
                    st.success(f"Heard: **{command}**")
                            
                            # Process voice command
                    if any(word in command for word in ["next", "next step", "continue", "ahead"]):
                        if current < total_steps - 1:
                            st.session_state.current_step += 1
                            st.rerun()
                        else:
                            st.balloons()
                            st.success("All steps completed!")
                            st.session_state.cooking_mode = False
                            st.rerun()
                    
                    elif any(word in command for word in ["previous", "back", "last"]):
                        if current > 0:
                            st.session_state.current_step -= 1
                            st.rerun()
                        else:
                            st.info("Already at first step")
                    
                    elif any(word in command for word in ["repeat", "again", "repeat step"]):
                        if st.session_state.voice_enabled:
                            lang_code = "hi" if st.session_state.voice_language == "Hindi" else "en"
                            audio_fp = text_to_speech(step_text, lang_code)
                            if audio_fp:
                                st.audio(audio_fp, format="audio/mp3", autoplay=True)
                        st.info("Repeating current step")
                    
                    elif any(word in command for word in ["start timer", "timer on", "begin timer"]):
                        # Start timer logic (if timer exists for this step)
                        if f"timer_remaining_{current}" in st.session_state and st.session_state[f"timer_remaining_{current}"] > 0:
                            st.session_state[f"timer_running_{current}"] = True
                            st.session_state[f"timer_start_{current}"] = time.time()
                            st.success("Timer started!")
                            st.rerun()
                        else:
                            st.warning("No timer set for this step")
                    
                    elif any(word in command for word in ["pause timer", "stop timer"]):
                        if st.session_state.get(f"timer_running_{current}", False):
                            elapsed = time.time() - st.session_state[f"timer_start_{current}"]
                            st.session_state[f"timer_remaining_{current}"] -= elapsed
                            st.session_state[f"timer_running_{current}"] = False
                            st.success("Timer paused")
                            st.rerun()
                    
                    elif "resume" in command:
                        if f"timer_remaining_{current}" in st.session_state and st.session_state[f"timer_remaining_{current}"] > 0:
                            st.session_state[f"timer_running_{current}"] = True
                            st.session_state[f"timer_start_{current}"] = time.time()
                            st.success("Timer resumed!")
                            st.rerun()
                    
                    elif "reset" in command:
                        if f"timer_remaining_{current}" in st.session_state:
                            st.session_state[f"timer_running_{current}"] = False
                            st.rerun()
                            st.info("Timer reset")
                    
                    elif any(word in command for word in ["done", "finish", "complete"]):
                        st.balloons()
                        st.success("Cooking completed!")
                        st.session_state.cooking_mode = False
                        st.rerun()
                    
                    else:
                        st.warning(f"Didn't understand: '{command}'\nTry: next, previous, repeat, start timer, pause timer, done")
                else:
                     st.error("Couldn't hear clearly. Try again.")
# ────────────── MEAL PLANNER ──────────────
with tab2:
    st.subheader("📅 Meal Planner")
    tomorrow = datetime.now() + timedelta(days=1)
    selected_date = st.date_input("Plan for:", value=tomorrow)
    date_key = selected_date.strftime("%Y-%m-%d")
    meals = ["Breakfast", "Morning Snack", "Lunch", "Evening Snack", "Dinner"]
    planned = st.session_state.meal_plan.get(date_key, {})
    for meal in meals:
        with st.expander(f"🍽️ {meal}"):
            dish = st.text_input(f"What for {meal}?", value=planned.get(meal, ""), key=f"meal_{date_key}_{meal}")
            if dish and st.button(f"Save {meal}", key=f"save_{date_key}_{meal}"):
                if date_key not in st.session_state.meal_plan:
                    st.session_state.meal_plan[date_key] = {}
                st.session_state.meal_plan[date_key][meal] = dish
                st.success(f"{meal} saved: {dish}")
    if date_key in st.session_state.meal_plan:
        st.markdown("### Planned Meals")
        for m, d in st.session_state.meal_plan[date_key].items():
            st.write(f"**{m}**: {d}")

# ────────────── GROCERY & INVENTORY ──────────────
with tab3:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🥫 Your Inventory")
        for item, qty in sorted(st.session_state.inventory.items()):
            status, color = get_quantity_status(qty)
            price = st.session_state.inventory_prices.get(item, None)
            price_str = f" (₹{price}/100g)" if price else ""
            st.markdown(f"- {item.capitalize()}: {qty} <span style='color:{color};'>[{status}]{price_str}</span>", unsafe_allow_html=True)
    with col2:
        st.subheader("🛒 Grocery List")
        if not st.session_state.grocery_list:
            st.info("List khali hai!")
        else:
            to_add = []
            for item in sorted(st.session_state.grocery_list):
                if st.checkbox(f"{item.capitalize()}", key=f"grocery_check_{item}"):
                    to_add.append(item)
            if to_add:
                for item in to_add:
                    st.session_state.inventory[item.lower()] = 500
                    st.session_state.grocery_list.remove(item)
                st.success(f"Added {len(to_add)} items to inventory!")
                st.rerun()
        if st.button("Clear Grocery"):
            st.session_state.grocery_list.clear()
            st.rerun()

    expiry_option = st.radio("Expiry Date", ["Estimate for me", "Manual input"])

    if st.button("Add Item") and new_item:
        key = new_item.lower().strip()
        st.session_state.inventory[key] = new_qty
        if new_price > 0:
            st.session_state.inventory_prices[key] = new_price

        if expiry_option == "Estimate for me":
            days = get_expiry_estimate(key)
            st.session_state.inventory_expiry[key] = days
            st.success(f"Added {new_item} ({new_qty}) — estimated expiry in ~{days} days")
        else:
            days = st.number_input("Days until expiry", min_value=1, step=1, key="manual_days")
            st.session_state.inventory_expiry[key] = days
            st.success(f"Added {new_item} ({new_qty}) — expires in {days} days")

        st.rerun()

    # Show current inventory with expiry
    if st.session_state.inventory:
        st.markdown("### Current Inventory")
        for item, qty in sorted(st.session_state.inventory.items()):
            expiry_days = st.session_state.inventory_expiry.get(item, None)
            if expiry_days is not None:
                if expiry_days < 0:
                    status = f"Expired ({expiry_days} days ago)"
                    color = "red"
                elif expiry_days <= 3:
                    status = f"Urgent ({expiry_days} days left)"
                    color = "orange"
                else:
                    status = f"OK ({expiry_days} days left)"
                    color = "green"
                st.markdown(f"- **{item.capitalize()}**: {qty}g/ml  <span style='color:{color}'>{status}</span>", unsafe_allow_html=True)
            else:
                st.write(f"- {item.capitalize()}: {qty}g/ml")
# ────────────── CUSTOM RECIPES ──────────────
with tab4:
    st.subheader("🍲 Custom Recipes")
    with st.expander("➕ Create New Custom Recipe"):
        name = st.text_input("Recipe Name")
        ingredients = st.text_area("Ingredients")
        steps = st.text_area("Steps")
       
        if st.button("Save Custom Recipe") and name and ingredients and steps:
            st.session_state.custom_recipes[name] = {"ingredients": ingredients, "steps": steps}
            st.success(f"Saved: {name}")
    if st.session_state.custom_recipes:
        st.markdown("### Your Custom Recipes")
        for name, data in st.session_state.custom_recipes.items():
            with st.expander(name):
                st.write("**Ingredients:**", data["ingredients"])
                st.write("**Steps:**", data["steps"])

# ────────────── TRIED RECIPES ──────────────
with tab5:
    st.subheader("🔥 Tried Recipes")
    if not st.session_state.tried_recipes:
        st.info("No recipes tried yet! Cook something to see here.")
    else:
        for idx, entry in enumerate(reversed(st.session_state.tried_recipes), 1):
            stars = "★" * entry["rating"] + "☆" * (5 - entry["rating"])
            with st.expander(f"Recipe {idx} – {entry['date']} – {stars}"):
                st.markdown(entry["recipe"])

# ────────────── FAVOURITE RECIPES ──────────────
with tab6:
    st.subheader("❤️ Favourite Recipes")
    if not st.session_state.favourite_recipes:
        st.info("No favourites yet! Heart a recipe to add.")
    else:
        for name, recipe in st.session_state.favourite_recipes.items():
            with st.expander(name):
                st.markdown(recipe)

# ────────────── NEW TAB: SCAN INGREDIENTS (OpenRouter) ──────────────
# ────────────── RECEIPT SCANNER TAB ──────────────
with tab_receipt:
    st.subheader("🧾 Receipt Scanner")
    st.info("Upload receipt photo → AI extracts food items → Review & add to inventory")
    
    col_cam, col_upload = st.columns(2)
    with col_cam:
        receipt_camera = st.camera_input("Take photo of receipt", key="receipt_camera")
    with col_upload:
        receipt_upload = st.file_uploader("Or upload receipt", type=["jpg", "jpeg", "png", "pdf"], key="receipt_upload")
    
    receipt_img = receipt_camera or receipt_upload
    
    if receipt_img is not None:
        st.image(receipt_img, caption="Your receipt", use_column_width=True)
        
        if st.button("🔍 Scan Receipt with AI", key="scan_receipt_btn"):
            with st.spinner("Analyzing receipt..."):
                image_bytes = receipt_img.getvalue()
                detected_items = detect_ingredients_from_image(image_bytes)
                
                if detected_items:
                    st.success(f"✅ Found {len(detected_items)} food items!")
                    
                    # Store in session state for editing
                    if "receipt_items" not in st.session_state:
                        st.session_state.receipt_items = {}
                    
                    st.markdown("### 📝 Review Detected Items:")
                    st.caption("Check items to add, uncheck to skip. You can also edit quantities.")
                    
                    cols = st.columns(3)
                    for idx, item in enumerate(detected_items):
                        with cols[idx % 3]:
                            item_name = item.lower()
                            
                            # Checkbox for selection
                            selected = st.checkbox(
                                f"**{item.capitalize()}**",
                                value=True,
                                key=f"receipt_check_{item_name}"
                            )
                            
                            # Quantity input (only shown if selected)
                            if selected:
                                qty = st.number_input(
                                    "Quantity (g/ml)",
                                    min_value=1,
                                    value=500,
                                    step=50,
                                    key=f"receipt_qty_{item_name}"
                                )
                                st.session_state.receipt_items[item_name] = qty
                            elif item_name in st.session_state.receipt_items:
                                del st.session_state.receipt_items[item_name]
                    
                    st.markdown("---")
                    
                    if st.session_state.receipt_items:
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            if st.button("✅ Add to Inventory", type="primary", use_container_width=True):
                                for item, qty in st.session_state.receipt_items.items():
                                    st.session_state.inventory[item] = qty
                                st.success(f"✨ Added {len(st.session_state.receipt_items)} items to inventory!")
                                st.session_state.receipt_items = {}
                                st.rerun()
                        
                        with col2:
                            if st.button("🛒 Add to Grocery List", use_container_width=True):
                                for item in st.session_state.receipt_items.keys():
                                    st.session_state.grocery_list.add(item)
                                st.success(f"✨ Added {len(st.session_state.receipt_items)} items to grocery!")
                                st.session_state.receipt_items = {}
                                st.rerun()
                else:
                    st.warning("⚠️ No food items detected. Try a clearer photo or different angle.")

# ────────────── INGREDIENT SCANNER TAB ──────────────
with tab_ingredient_scan:
    st.subheader("📸 Ingredient Scanner")
    st.info("Take photo of ingredients → AI identifies them → Review & add to inventory")
    
    col_cam, col_upload = st.columns(2)
    with col_cam:
        ing_camera = st.camera_input("Take photo of ingredients", key="ing_camera")
    with col_upload:
        ing_upload = st.file_uploader("Or upload photo", type=["jpg", "jpeg", "png"], key="ing_upload")
    
    ing_img = ing_camera or ing_upload
    
    if ing_img is not None:
        st.image(ing_img, caption="Your ingredients", use_column_width=True)
        
        if st.button("🔍 Detect Ingredients with AI", key="detect_ing_btn"):
            with st.spinner("Analyzing photo..."):
                image_bytes = ing_img.getvalue()
                detected_items = detect_ingredients_from_image(image_bytes)
                
                if detected_items:
                    st.success(f"✅ Detected {len(detected_items)} ingredients!")
                    
                    # Store in session state for editing
                    if "scanned_ingredients" not in st.session_state:
                        st.session_state.scanned_ingredients = {}
                    
                    st.markdown("### 📝 Review Detected Ingredients:")
                    st.caption("Check items to add, uncheck to skip. Edit quantities as needed.")
                    
                    cols = st.columns(3)
                    for idx, item in enumerate(detected_items):
                        with cols[idx % 3]:
                            item_name = item.lower()
                            
                            # Checkbox for selection
                            selected = st.checkbox(
                                f"**{item.capitalize()}**",
                                value=True,
                                key=f"ing_check_{item_name}"
                            )
                            
                            # Quantity input (only shown if selected)
                            if selected:
                                qty = st.number_input(
                                    "Quantity (g/ml)",
                                    min_value=1,
                                    value=500,
                                    step=50,
                                    key=f"ing_qty_{item_name}"
                                )
                                st.session_state.scanned_ingredients[item_name] = qty
                            elif item_name in st.session_state.scanned_ingredients:
                                del st.session_state.scanned_ingredients[item_name]
                    
                    st.markdown("---")
                    
                    if st.session_state.scanned_ingredients:
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            if st.button("✅ Add to Inventory", type="primary", use_container_width=True, key="add_scanned_inv"):
                                for item, qty in st.session_state.scanned_ingredients.items():
                                    st.session_state.inventory[item] = qty
                                st.success(f"✨ Added {len(st.session_state.scanned_ingredients)} items to inventory!")
                                st.session_state.scanned_ingredients = {}
                                st.rerun()
                        
                        with col2:
                            if st.button("🛒 Add to Grocery List", use_container_width=True, key="add_scanned_grocery"):
                                for item in st.session_state.scanned_ingredients.keys():
                                    st.session_state.grocery_list.add(item)
                                st.success(f"✨ Added {len(st.session_state.scanned_ingredients)} items to grocery!")
                                st.session_state.scanned_ingredients = {}
                                st.rerun()
                else:
                    st.warning("⚠️ No ingredients detected. Try a clearer photo.")

# ────────────── DIET CHARTS TAB ──────────────
with tab_diet:
    st.subheader("🥗 Diet Charts")
    st.info("Create personalized diet plans and meal schedules")
    
    # Create new diet chart
    with st.expander("➕ Create New Diet Chart", expanded=False):
        chart_name = st.text_input("Diet Chart Name", placeholder="e.g., Weight Loss Plan, Muscle Gain, Keto Diet")
        
        col1, col2 = st.columns(2)
        with col1:
            diet_type = st.selectbox(
                "Diet Type",
                ["Custom", "Weight Loss", "Weight Gain", "Maintenance", "Keto", "Vegan", "High Protein", "Low Carb"]
            )
        with col2:
            duration = st.selectbox("Duration", ["1 Week", "2 Weeks", "1 Month", "3 Months", "Ongoing"])
        
        st.markdown("#### 🍽️ Meal Schedule")
        
        # Days of week
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        meals = ["Breakfast", "Mid-Morning Snack", "Lunch", "Evening Snack", "Dinner"]
        
        diet_schedule = {}
        
        day_tabs = st.tabs(days)
        for day_idx, day in enumerate(days):
            with day_tabs[day_idx]:
                diet_schedule[day] = {}
                for meal in meals:
                    diet_schedule[day][meal] = st.text_area(
                        f"{meal}",
                        placeholder=f"Enter {meal.lower()} items...",
                        height=80,
                        key=f"diet_{day}_{meal}"
                    )
        
        notes = st.text_area("Additional Notes", placeholder="Special instructions, supplements, etc.")
        
        if st.button("💾 Save Diet Chart", type="primary", use_container_width=True):
            if chart_name:
                st.session_state.diet_charts[chart_name] = {
                    "type": diet_type,
                    "duration": duration,
                    "schedule": diet_schedule,
                    "notes": notes,
                    "created": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                st.success(f"✅ Saved: {chart_name}")
                st.rerun()
            else:
                st.error("Please enter a diet chart name!")
    
    # Display existing diet charts
    if st.session_state.diet_charts:
        st.markdown("---")
        st.markdown("### 📋 Your Diet Charts")
        
        for chart_name, chart_data in st.session_state.diet_charts.items():
            with st.expander(f"📊 {chart_name} ({chart_data['type']} - {chart_data['duration']})", expanded=False):
                st.caption(f"Created: {chart_data['created']}")
                
                # Edit mode toggle
                edit_mode = st.checkbox(f"✏️ Edit this chart", key=f"edit_{chart_name}")
                
                if edit_mode:
                    st.markdown("#### Edit Meal Schedule")
                    
                    updated_schedule = {}
                    day_tabs_edit = st.tabs(days)
                    
                    for day_idx, day in enumerate(days):
                        with day_tabs_edit[day_idx]:
                            updated_schedule[day] = {}
                            for meal in meals:
                                current_value = chart_data['schedule'].get(day, {}).get(meal, "")
                                updated_schedule[day][meal] = st.text_area(
                                    f"{meal}",
                                    value=current_value,
                                    height=80,
                                    key=f"edit_{chart_name}_{day}_{meal}"
                                )
                    
                    updated_notes = st.text_area(
                        "Notes",
                        value=chart_data.get('notes', ''),
                        key=f"edit_notes_{chart_name}"
                    )
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("💾 Save Changes", key=f"save_{chart_name}", use_container_width=True):
                            st.session_state.diet_charts[chart_name]['schedule'] = updated_schedule
                            st.session_state.diet_charts[chart_name]['notes'] = updated_notes
                            st.success("✅ Changes saved!")
                            st.rerun()
                    
                    with col2:
                        if st.button("🗑️ Delete Chart", key=f"delete_{chart_name}", use_container_width=True):
                            del st.session_state.diet_charts[chart_name]
                            st.success("✅ Chart deleted!")
                            st.rerun()
                
                else:
                    # View mode
                    st.markdown("#### 📅 Weekly Schedule")
                    
                    view_day_tabs = st.tabs(days)
                    for day_idx, day in enumerate(days):
                        with view_day_tabs[day_idx]:
                            for meal in meals:
                                meal_content = chart_data['schedule'].get(day, {}).get(meal, "")
                                if meal_content:
                                    st.markdown(f"**{meal}:**")
                                    st.write(meal_content)
                                    st.markdown("---")
                    
                    if chart_data.get('notes'):
                        st.markdown("#### 📝 Notes")
                        st.info(chart_data['notes'])
    else:
        st.info("📝 No diet charts yet. Create your first one above!")

# ────────────────────────────────────────────────
#  AUTO-SAVE INVENTORY & RELATED DATA TO FIRESTORE
# ────────────────────────────────────────────────

if st.session_state.get("is_authenticated", False) and st.session_state.get("user_id"):
    try:
        user_data = {
            "inventory": dict(st.session_state.inventory),  # convert to plain dict for JSON
            "inventory_prices": dict(st.session_state.inventory_prices),
            "inventory_expiry": dict(st.session_state.inventory_expiry),
            "grocery_list": list(st.session_state.grocery_list),
            "diet_charts": dict(st.session_state.diet_charts),  # Save diet charts
            "last_updated": datetime.now().isoformat()
        }
        
        # Save (merge = True means update only these fields, don't overwrite others)
        db.collection("users").document(st.session_state.user_id).set(
            user_data,
            merge=True
        )
        
        # Optional: show tiny success message (remove if annoying)
        # st.caption("Inventory auto-saved ✓")
        
    except Exception as e:
        # Silent fail (don't break app), but log for you
        print(f"Auto-save failed: {str(e)}")
# Improved floating PWA install button
st.markdown("""
    <script>
    let deferredPrompt;
    
    window.addEventListener('beforeinstallprompt', (e) => {
        // Prevent default mini-infobar
        e.preventDefault();
        // Store the event for later use
        deferredPrompt = e;
        console.log('PWA install prompt ready');
        
        // Show floating button
        const btn = document.createElement('button');
        btn.innerHTML = '📲 Install App';
        btn.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 9999;
            padding: 12px 20px;
            background: #FF6B6B;
            color: white;
            border: none;
            border-radius: 50px;
            font-weight: bold;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            cursor: pointer;
        `;
        
        btn.onclick = () => {
            deferredPrompt.prompt();
            deferredPrompt.userChoice.then((choice) => {
                if (choice.outcome === 'accepted') {
                    console.log('Installed!');
                }
                deferredPrompt = null;
                btn.remove();
            });
        };
        
        document.body.appendChild(btn);
    });
    </script>
""", unsafe_allow_html=True)
# ────────────────────────────────────────────────
#  Visible "Install App" Button for PWA
# ────────────────────────────────────────────────

st.markdown("---")

st.subheader("📲 Make Annapurna Your App!")

st.info("""
Want quick access like a real app?  
Install it to your phone home screen — works offline too!
""")

# Big install button
if st.button("📱 Install Annapurna App", type="primary", use_container_width=True):
    st.markdown("""
        <script>
        if (window.deferredPrompt) {
            window.deferredPrompt.prompt();
            window.deferredPrompt.userChoice.then((choiceResult) => {
                if (choiceResult.outcome === 'accepted') {
                    console.log('User accepted the install prompt');
                } else {
                    console.log('User dismissed the install prompt');
                }
                window.deferredPrompt = null;
            });
        } else {
            alert("Install prompt not available. On mobile: tap browser menu → 'Add to Home Screen'");
        }
        </script>
    """, unsafe_allow_html=True)
    st.success("Install prompt triggered! If nothing happens, check your browser menu → 'Add to Home Screen'")

# Fallback message for desktop users
st.caption("""
Desktop: This feature works best on mobile Chrome/Safari.  
Mobile: Look for 'Install' in address bar or browser menu.
""")

# Footer
st.markdown("---")
st.caption("Annapurna By Manas  • Chat + Meal Planner + Grocery + Custom Recipes + Tried + Favourites • " + datetime.now().strftime("%Y-%m-%d"))