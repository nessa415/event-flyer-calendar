# Event Flyer to Calendar App - Cloud Deployment Guide

## Overview
This is the cloud deployment version of the Event Flyer to Calendar application. This guide will help you deploy the application to a cloud platform so you can access it from anywhere without installing anything locally.

## Cloud Deployment Options

### Option 1: Deploy to Render (Recommended)

[Render](https://render.com/) is a cloud platform that offers free web service hosting. Here's how to deploy:

1. **Create a Render account**
   - Go to [render.com](https://render.com/) and sign up for a free account

2. **Create a new Web Service**
   - Click "New" and select "Web Service"
   - Connect your GitHub account or use the "Upload" option
   - If using GitHub, fork this repository first or upload the files to a new repository
   - If using upload, select the zip file containing this application

3. **Configure your service**
   - Name: `event-flyer-calendar` (or any name you prefer)
   - Environment: `Python 3`
   - Build Command: `pip install -r requirements.txt && apt-get update && apt-get install -y tesseract-ocr`
   - Start Command: `gunicorn app:app`
   - Select the Free plan

4. **Set environment variables**
   - Click on "Environment" and add the following variables:
     - `SECRET_KEY`: Generate a random string (e.g., `python -c "import secrets; print(secrets.token_hex(16))"`)
     - `GOOGLE_CLIENT_ID`: Your Google OAuth client ID (see Google Calendar Setup below)
     - `GOOGLE_CLIENT_SECRET`: Your Google OAuth client secret

5. **Deploy**
   - Click "Create Web Service"
   - Wait for the deployment to complete (this may take a few minutes)
   - Once deployed, you can access your application at the URL provided by Render

### Option 2: Deploy to Heroku

1. **Create a Heroku account**
   - Go to [heroku.com](https://heroku.com/) and sign up for a free account
   - Install the [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli)

2. **Prepare your application**
   - Make sure you have the `Procfile` and `requirements.txt` files in your application directory

3. **Deploy to Heroku**
   ```bash
   # Login to Heroku
   heroku login

   # Create a new Heroku app
   heroku create your-app-name

   # Set environment variables
   heroku config:set SECRET_KEY=your_secret_key
   heroku config:set GOOGLE_CLIENT_ID=your_google_client_id
   heroku config:set GOOGLE_CLIENT_SECRET=your_google_client_secret

   # Add Heroku buildpacks for Tesseract OCR
   heroku buildpacks:add --index 1 https://github.com/heroku/heroku-buildpack-apt
   heroku buildpacks:add --index 2 heroku/python

   # Create an Aptfile with Tesseract
   echo "tesseract-ocr" > Aptfile
   echo "tesseract-ocr-eng" >> Aptfile

   # Deploy the application
   git add .
   git commit -m "Deploy to Heroku"
   git push heroku main

   # Open the application
   heroku open
   ```

## Google Calendar Setup

To enable Google Calendar integration, you need to set up OAuth credentials:

1. **Create a Google Cloud project**
   - Go to the [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project

2. **Enable the Google Calendar API**
   - In your project, go to "APIs & Services" > "Library"
   - Search for "Google Calendar API" and enable it

3. **Create OAuth credentials**
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Application type: Web application
   - Name: Event Flyer to Calendar
   - Authorized JavaScript origins: Your application URL (e.g., `https://your-app-name.onrender.com`)
   - Authorized redirect URIs: Your application URL + `/api/auth/google/callback` (e.g., `https://your-app-name.onrender.com/api/auth/google/callback`)
   - Click "Create"

4. **Set environment variables**
   - Copy your Client ID and Client Secret
   - Add them to your cloud platform's environment variables as described above

## Troubleshooting

- **OCR not working?** Make sure the Tesseract installation was successful during deployment
- **Google Calendar integration failing?** Verify your OAuth credentials and redirect URIs
- **Application crashing?** Check the logs in your cloud platform's dashboard

## Need More Help?

If you encounter any issues with the cloud deployment, please let me know and I can provide more detailed troubleshooting or create a simpler deployment option.
