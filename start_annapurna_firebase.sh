#!/bin/bash

echo "========================================"
echo "   Starting Annapurna (Firebase Version)"
echo "========================================"
echo ""

echo "[1/2] Starting Voice Listener..."
osascript -e 'tell app "Terminal" to do script "cd \"'$(pwd)'\" && python3 voice_listener_firebase.py"' 2>/dev/null || gnome-terminal -- bash -c "cd $(pwd) && python3 voice_listener_firebase.py; exec bash" 2>/dev/null || xterm -e "cd $(pwd) && python3 voice_listener_firebase.py" 2>/dev/null &

sleep 2

echo "[2/2] Starting Streamlit App..."
streamlit run hey_chef_chat_firebase.py &

echo ""
echo "========================================"
echo "   Both services started!"
echo "========================================"
echo ""
echo "  Voice Listener: New terminal window"
echo "  Streamlit App: Will open in browser"
echo ""
echo "  Say 'Annapurna' to give voice commands!"
echo ""
