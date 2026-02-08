# 🍳 Annapurna - AI Voice-Controlled Cooking Assistant

Your personal AI chef with voice control! Ask for recipes, manage inventory, plan meals, and more - all with your voice!

## ✨ Features

- 🎤 **Voice Control** - Say "Annapurna" and give commands (works on cloud too!)
- 💬 **AI Chat** - Powered by Groq's Llama 3.3 70B
- 📅 **Meal Planner** - Plan your weekly meals
- 🛒 **Smart Inventory** - Track ingredients with expiry dates
- 🍲 **Custom Recipes** - Create and save your own recipes
- 📱 **Progressive Web App** - Install on your phone
- 🔥 **Firebase Sync** - Your data syncs across devices
- 🎥 **YouTube Integration** - Extract recipes from cooking videos

## 🚀 Live Demo

**Coming soon!** (After you deploy)

## 📋 Prerequisites

- Python 3.8+
- Firebase account (free)
- Groq API key (free)
- Microphone (for voice features)

## 🛠️ Installation

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR-USERNAME/annapurna.git
cd annapurna
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Firebase

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Create a new project (or use existing)
3. Enable Firestore Database
4. Go to Project Settings → Service Accounts
5. Click "Generate New Private Key"
6. Save the file as `firebase_credentials.json` in the project folder

### 4. Set Up API Keys

Create a `.streamlit/secrets.toml` file:

```toml
[groq]
api_key = "your-groq-api-key-here"

[firebase]
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\nYour key here\n-----END PRIVATE KEY-----\n"
client_email = "your-client-email"
client_id = "your-client-id"
client_x509_cert_url = "your-cert-url"

[google_oauth]
client_id = "your-google-oauth-client-id"
client_secret = "your-google-oauth-secret"
redirect_uri = "http://localhost:8501"
```

**Get Groq API Key:** https://console.groq.com/keys

## 🎤 Voice Control Setup

### For Local Use:

1. Run the voice listener:
```bash
python voice_listener_firebase.py
```

2. In a new terminal, run the app:
```bash
streamlit run hey_chef_chat_firebase.py
```

3. Say "Annapurna" followed by your command!

### For Cloud Use (Streamlit Share):

1. Deploy the app to Streamlit Cloud (see below)
2. On YOUR computer, run:
```bash
python voice_listener_firebase.py
```
3. The cloud app will respond to your voice commands!

**Only YOU can control the cloud app by voice!**

## ☁️ Deploy to Streamlit Cloud

### Step 1: Push to GitHub

1. Create a new repository on GitHub
2. Push your code:
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/annapurna.git
git push -u origin main
```

**IMPORTANT:** Make sure `firebase_credentials.json` is in `.gitignore`!

### Step 2: Deploy on Streamlit

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click "New app"
3. Select your repository
4. Main file: `hey_chef_chat_firebase.py`
5. Click "Deploy"

### Step 3: Add Secrets

1. In Streamlit Cloud, go to your app → Settings (⚙️) → Secrets
2. Copy the contents from your local `.streamlit/secrets.toml`
3. Paste and save

**Done!** Your app is live! 🎉

## 📱 Usage

### Voice Commands (after setup):

```
"Annapurna, how do I make pasta?"
"Annapurna, give me a quick breakfast recipe"
"Annapurna, what can I make with chicken and rice?"
"Annapurna, suggest a vegetarian dinner"
```

### Chat (type):

Just type your questions in the chat box!

### Features:

- **Meal Planner** - Schedule your meals
- **Inventory** - Add/remove ingredients
- **Grocery List** - Auto-generated from recipes
- **Custom Recipes** - Save your favorites
- **YouTube** - Paste a cooking video URL to extract the recipe

## 🔧 Configuration

### Jain Mode

For Jain dietary restrictions, toggle "Jain Mode" in the sidebar.

### Voice Language

Choose between English and Hindi for voice output.

### API Keys

Update your API keys in `.streamlit/secrets.toml` (local) or Streamlit Cloud Secrets (cloud).

## 📂 Project Structure

```
annapurna/
├── hey_chef_chat_firebase.py      # Main Streamlit app
├── voice_listener_firebase.py     # Voice listener (run locally)
├── requirements.txt               # Python dependencies
├── .gitignore                     # Git ignore rules
├── README.md                      # This file
├── start_annapurna_firebase.bat   # Windows starter
├── start_annapurna_firebase.sh    # Mac/Linux starter
└── firebase_credentials.json      # Firebase key (DO NOT COMMIT!)
```

## 🐛 Troubleshooting

### Voice not working?
- Make sure `voice_listener_firebase.py` is running
- Check if "Voice Assistant" is ON in the sidebar
- Verify your microphone is working
- Wait 3-5 seconds after speaking

### Firebase errors?
- Check if `firebase_credentials.json` exists
- Verify Firebase secrets are correct in Streamlit Cloud
- Make sure Firestore is enabled in Firebase Console

### API errors?
- Verify your Groq API key is valid
- Check if you have API credits remaining

## 🤝 Contributing

Contributions welcome! Feel free to:
- Report bugs
- Suggest features
- Submit pull requests

## 📄 License

MIT License - feel free to use for personal or commercial projects!

## 🙏 Acknowledgments

- Groq for the amazing Llama API
- Streamlit for the awesome framework
- Firebase for backend services

## 📞 Support

Having issues? Create an issue on GitHub!

---

Made with ❤️ for cooking enthusiasts who love AI!

**Star ⭐ this repo if you find it useful!**
