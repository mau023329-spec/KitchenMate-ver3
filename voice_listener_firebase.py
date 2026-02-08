"""
🎤 Annapurna Voice Listener (FIREBASE VERSION)
This program runs on YOUR computer and listens for "Annapurna"
When it hears you, it saves your command to FIREBASE (not a file!)
This way, the Streamlit Cloud app can see your commands from anywhere!

HOW TO USE:
1. Run this file: python voice_listener_firebase.py
2. Leave it running (don't close the window)
3. Say "Annapurna" followed by your command
4. Your Streamlit app (even on cloud!) will respond!
"""

import speech_recognition as sr
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import os
import json

# ═══════════════════════════════════════════════════════════════
# FIREBASE SETUP
# ═══════════════════════════════════════════════════════════════

print("=" * 60)
print("🔥 Initializing Firebase...")
print("=" * 60)

# Check if firebase credentials file exists
if not os.path.exists("firebase_credentials.json"):
    print()
    print("❌ ERROR: firebase_credentials.json NOT FOUND!")
    print()
    print("📝 INSTRUCTIONS:")
    print("1. Go to Firebase Console: https://console.firebase.google.com")
    print("2. Select your project")
    print("3. Go to Project Settings → Service Accounts")
    print("4. Click 'Generate New Private Key'")
    print("5. Save the downloaded file as 'firebase_credentials.json'")
    print("6. Put it in the same folder as this script")
    print()
    input("Press Enter to exit...")
    exit(1)

# Initialize Firebase
try:
    cred = credentials.Certificate("firebase_credentials.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase connected successfully!")
    print()
except Exception as e:
    print(f"❌ Firebase initialization failed: {str(e)}")
    input("Press Enter to exit...")
    exit(1)

# ═══════════════════════════════════════════════════════════════
# VOICE LISTENER CONFIGURATION
# ═══════════════════════════════════════════════════════════════

WAKE_WORDS = ["annapurna", "anna purna", "anna poorna", "anapurna"]

def save_command_to_firebase(command_text):
    """Save voice command to Firebase for Streamlit to read"""
    try:
        # Create a new document in 'voice_commands' collection
        doc_ref = db.collection('voice_commands').document()
        doc_ref.set({
            'text': command_text,
            'timestamp': datetime.now().isoformat(),
            'processed': False,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        
        print(f"✅ Command saved to Firebase!")
        return True
    except Exception as e:
        print(f"❌ Error saving to Firebase: {e}")
        return False

def listen_for_wake_word():
    """Listen for a short chunk and check for wake word"""
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 4000
    recognizer.dynamic_energy_threshold = True
    
    try:
        with sr.Microphone() as source:
            # Adjust for noise
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            
            # Listen for 3 seconds
            audio = recognizer.listen(source, timeout=3, phrase_time_limit=3)
            
            # Convert to text
            text = recognizer.recognize_google(audio).lower()
            print(f"   Heard: {text}")
            
            # Check for wake word
            for wake_word in WAKE_WORDS:
                if wake_word in text:
                    return True, text
            
            return False, text
            
    except sr.WaitTimeoutError:
        return False, ""
    except sr.UnknownValueError:
        return False, ""
    except sr.RequestError as e:
        print(f"❌ Google Speech Recognition error: {e}")
        return False, ""
    except Exception as e:
        print(f"❌ Error: {e}")
        return False, ""

def record_command():
    """Record the full command after wake word"""
    recognizer = sr.Recognizer()
    
    try:
        with sr.Microphone() as source:
            print("   🎙️  Recording your command...")
            
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            
            # Listen for command (up to 8 seconds)
            audio = recognizer.listen(source, timeout=2, phrase_time_limit=8)
            
            # Convert to text
            text = recognizer.recognize_google(audio)
            print(f"   📝 Command: {text}")
            
            return text
            
    except sr.WaitTimeoutError:
        print("   ⏱️  No command heard (timeout)")
        return None
    except sr.UnknownValueError:
        print("   🤷 Couldn't understand the command")
        return None
    except sr.RequestError as e:
        print(f"   ❌ Google Speech Recognition error: {e}")
        return None
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None

def main():
    """Main listening loop"""
    print("=" * 60)
    print("🎤 Annapurna Voice Listener Started! (Firebase Version)")
    print("=" * 60)
    print()
    print("✅ Ready to listen!")
    print("💡 Say 'Annapurna' followed by your command")
    print("💡 Example: 'Annapurna, how do I make pasta?'")
    print()
    print("🌐 Commands will be sent to Firebase")
    print("📱 Your Streamlit app (anywhere) will receive them!")
    print()
    print("🛑 Press Ctrl+C to stop")
    print("-" * 60)
    print()
    
    while True:
        try:
            # Listen for wake word
            print("🔍 Listening for 'Annapurna'...")
            wake_detected, heard_text = listen_for_wake_word()
            
            if wake_detected:
                print("✅ Wake word detected!")
                print()
                
                # Small pause
                import time
                time.sleep(0.5)
                
                # Record command
                command = record_command()
                
                if command:
                    # Save to Firebase
                    if save_command_to_firebase(command):
                        print(f"📤 Sent to cloud: '{command}'")
                    else:
                        print("❌ Failed to save command")
                    
                    print()
                    print("-" * 60)
                    print()
                else:
                    print("⚠️  No command received, going back to listening...")
                    print()
            
            # Small delay to reduce CPU usage
            import time
            time.sleep(0.1)
            
        except KeyboardInterrupt:
            print()
            print()
            print("=" * 60)
            print("🛑 Voice Listener Stopped!")
            print("=" * 60)
            break
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            print("   Continuing to listen...")
            import time
            time.sleep(1)

if __name__ == "__main__":
    # Check if microphone is available
    try:
        recognizer = sr.Recognizer()
        with sr.Microphone() as source:
            print("✅ Microphone detected!")
            print()
    except Exception as e:
        print("❌ ERROR: No microphone found!")
        print(f"   Details: {e}")
        print()
        print("   Please connect a microphone and try again.")
        input("   Press Enter to exit...")
        exit(1)
    
    # Start listening
    main()
