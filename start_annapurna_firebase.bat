@echo off
echo ========================================
echo    Starting Annapurna (Firebase Version)
echo ========================================
echo.

echo [1/2] Starting Voice Listener...
start "Annapurna Voice Listener" python voice_listener_firebase.py

timeout /t 2 /nobreak > nul

echo [2/2] Starting Streamlit App...
start "Annapurna App" streamlit run hey_chef_chat_firebase.py

echo.
echo ========================================
echo    Both services started!
echo ========================================
echo.
echo  Voice Listener: Black terminal window
echo  Streamlit App: Will open in browser
echo.
echo  Say "Annapurna" to give voice commands!
echo.
pause
