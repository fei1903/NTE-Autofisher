<img width="1915" height="976" alt="image" src="https://github.com/user-attachments/assets/0494943f-3554-4dc2-8fa1-5d3169e07c0c" />
# NTE AutoFisher

An automatic fishing bot for **NTE** that detects fishing prompts using computer vision.  
Designed to work reliably when the game is in **fullscreen mode** (prevents detection bugs).

> ⚠️ **Important**  
> - Make sure to select **HTGame.exe** as your game process!
> - Do not change any settings unless you fully understand what you are doing.
> - Only works for in‑game resolutions **1920x1080** or **1600x900**.
> - The game must run on your **primary/main display**.

---

## ✨ Features

- Automatically fishes when a fishing prompt appears on screen  
- Works only when the game is in **fullscreen mode**  
- Supports **2 ingame resolutions**:  
  - `1920x1080`  
  - `1600x900`  
- Uses **image recognition** (OpenCV) to detect fishing events  
- Lightweight and runs in the background

---

## 📋 Requirements

- Windows OS (uses `pywin32` for window management)  
- Python 3.7 or higher  
- The game **HTGame.exe** must be running  
- Your screen resolution must match **one of the supported ingame resolutions**  
- Game must be on your **primary/main display**

---

## 🛠️ Installation & Setup

### 1️⃣ Download and extract the source code

Download the latest release (or the ZIP archive) and extract it to a folder of your choice (e.g., `C:\AutoFisher`).

### 2️⃣ Open Command Prompt (CMD) and navigate to the folder

- Open **CMD** (Command Prompt).  
- Type `cd ` (with a space after `cd`) and then **drag and drop the extracted folder** into the CMD window.  
- The path will appear automatically (e.g., `cd "C:\Users\YourName\Downloads\AutoFisher"`).  
- Press **Enter** to go into that directory.

### 3️⃣ Install required packages

Run the following command:

```cmd
pip install opencv-python numpy mss pywin32 psutil
Wait for the installation to finish.
To ensure everything is installed correctly, also run:
pip install -r requirements.txt
Wait until the download and installation complete.
```

## 🚀 How to Run the AutoFisher
Launch HTGame.exe and set the in‑game resolution to either 1920x1080 or 1600x900.
Put the game into fullscreen mode – this is critical; otherwise the script may bug out.
Navigate to a fishing spot and open the fishing UI.
Run the script by double‑clicking fish.py (or execute python fish.py from a terminal opened in the project folder).
The auto fisher will now wait for fishing prompts and automatically reel in catches.
