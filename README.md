# Smart Voting System Using Face Recognition

## Project Description

Smart Voting System Using Face Recognition is a web-based voting application designed to improve voter authentication and election management using facial recognition and security mechanisms.

## Key Features

* Voter Registration and Login
* Face Registration and Face Recognition
* Face Liveness Detection
* Anti-Spoofing Detection
* OTP Verification using TwoFactor API
* GPS Location Tracking
* Admin Dashboard
* Election and Candidate Management
* Secure Vote Submission
* Prevention of Duplicate Voting
* MongoDB Database Integration

## Technologies Used

* Python
* Flask
* MongoDB
* HTML, CSS and JavaScript
* OpenCV
* DeepFace (Facenet512)
* MediaPipe
* ONNX Runtime
* TwoFactor API

## Requirements

* Python 3.11
* MongoDB
* VS Code
* Git

## Installation

### 1\. Clone the Repository

\\\\ash
git clone YOUR\_GITHUB\_REPOSITORY\_URL
cd smart\_voting\_project\_new
\\\\

### 2\. Create Virtual Environment

\\\\ash
python -m venv venv
\\\\

### 3\. Activate Virtual Environment (Windows)

\\\\powershell
venv\\Scripts\\Activate.ps1
\\\\

### 4\. Install Dependencies

\\\\ash
pip install -r requirements.txt
\\\\

### 5\. Configure Environment Variables

Create a copy of .env.example\\ and rename it to .env.

Add your own secret key and TwoFactor API key in the .env\\ file.

### 6\. Start MongoDB

Make sure MongoDB is installed and running on your system.

### 7\. Run the Application

\\\\ash
python app.py
\\\\

Open your browser:

http://127.0.0.1:5000

## Security Notice

* Never upload your actual .env\\ file.
* Do not upload voter personal documents or face images.
* Configure your own API credentials before running the application.

## Project Status

Developed as a final-year Computer Science Engineering project.

